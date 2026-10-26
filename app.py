"""FastAPI入口：真实状态机、持久检查点、补材料、审核恢复和可观测指标。"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from adapters.business import BusinessBackend, DemoBackend
from adapters.investment import DemoInvestmentBackend, InvestmentBackend
from agents.audit_store import AuditStore
from agents.http_middleware import EnterpriseHttpMiddleware
from agents.claim_agent import WorkflowServices, build_claim_graph
from agents.investment_agent import (
    InvestmentServices,
    build_demo_trace,
    build_investment_graph,
    investment_advice_from_state,
    investment_initial_state,
    investment_state_to_response,
    run_demo_investment,
)
from agents.middleware_audit import configure_logging, mask_pii, RateLimitMiddleware
from agents.observability import tracing_config
from config import ClaimLLMFactory, get_model
from models.investment import (
    DemoInvestmentRunResponse,
    InvestmentConfirmation,
    InvestmentRAGQuery,
    InvestmentRAGResponse,
    InvestmentRequest,
    InvestmentResponse,
    InvestmentReviewInput,
)
from models.knowledge import (
    KnowledgeAnswerResponse,
    KnowledgeRAGQuery,
    KnowledgeSearchResponse,
)
from models.schemas import ClaimRequest, ClaimResponse
from models.workbench import AssistantRequest, DemoClaimRunResponse, DocumentBatchResponse
from monitoring import metrics, REQUESTS, ERRORS, LATENCY, CONFIDENCE, ITERATIONS, TOKENS
from settings import Settings
from tools.document_analysis import (
    MAX_DOCUMENT_BYTES,
    DocumentModelOutputError,
    DocumentValidationError,
    analyze_document,
)


logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal['ok'] = 'ok'


class Supplement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    policy_id: str = Field(min_length=1, max_length=64)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['review', 'accept', 'reject']
    reviewer: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)
    clause_basis: list[str] = Field(default_factory=list)


def create_app(
    services: WorkflowServices | None = None,
    *,
    database: str | None = None,
    document_text_model: Any = None,
    document_vision_model: Any = None,
    assistant_model: Any = None,
    intent_model: Any = None,
    general_model: Any = None,
    investment_model: Any = None,
    investment_services: InvestmentServices | None = None,
    investment_rag: Any = None,
    knowledge_rag: Any = None,
    knowledge_model: Any = None,
) -> FastAPI:
    cfg = Settings()
    if cfg.business_mode == 'demo':
        from tools.policy_store import ensure_policy_store
        from tools.demo_clauses import build_demo_clause_retriever
        backend = DemoBackend(policy_store=ensure_policy_store())
        service = services or WorkflowServices(backend, clause_retriever=build_demo_clause_retriever())
    else:
        backend = BusinessBackend()
        service = services or WorkflowServices(backend)
    investment_service = investment_services or InvestmentServices(
        DemoInvestmentBackend() if cfg.business_mode == 'demo' else InvestmentBackend()
    )
    effective_investment_rag = investment_rag
    if effective_investment_rag is None and cfg.investment_rag_enabled:
        try:
            from tools.investment_rag import get_investment_rag
            effective_investment_rag = get_investment_rag()
        except Exception:  # noqa: BLE001 - 投资知识库损坏不应阻断理赔主链路
            logger.exception('投资知识库初始化失败，已关闭投资 RAG')
    effective_knowledge_rag = knowledge_rag
    if effective_knowledge_rag is None and cfg.knowledge_rag_enabled:
        try:
            from tools.knowledge_rag import get_knowledge_rag
            effective_knowledge_rag = get_knowledge_rag()
        except Exception:  # noqa: BLE001 - 通用知识库损坏不应阻断既有业务
            logger.exception('通用知识库初始化失败，已关闭 /api/rag')
    limiter = RateLimitMiddleware()
    locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        # 先配置日志，后续启动校验与业务日志才不会被默认级别丢弃。
        configure_logging()
        if os.getenv('APP_ENV') == 'production':
            claims_key = os.getenv('CLAIMS_API_KEY', '')
            reviewer_key = os.getenv('REVIEWER_API_KEY', '')
            if not claims_key or not reviewer_key:
                raise RuntimeError('生产环境必须配置CLAIMS_API_KEY和REVIEWER_API_KEY')
            weak = {'changeme', 'secret', 'password', 'test', 'dev', 'admin', '123456'}
            for name, value in (('CLAIMS_API_KEY', claims_key), ('REVIEWER_API_KEY', reviewer_key)):
                if len(value) < 16 or value.lower() in weak:
                    raise RuntimeError(f'生产环境 {name} 过弱：至少 16 位且不能是常见口令')
            if Path('.env').exists():
                logger.warning('生产环境检测到 .env 文件：请改用环境变量或密钥管理（Vault/KMS）注入')
        path = database or os.getenv('CLAIMS_CHECKPOINT_DB') or '.data/checkpoints.sqlite'
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        audit_path = (os.getenv('CLAIMS_AUDIT_DB')
                      or (':memory:' if path == ':memory:' else '.data/audit.sqlite'))
        audit = AuditStore(audit_path)
        application.state.audit = audit
        try:
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                await saver.setup()
                application.state.graph = build_claim_graph(service, saver)
                application.state.investment_graph = build_investment_graph(investment_service, saver)
                yield
        finally:
            audit.close()

    application = FastAPI(title='智能业务助手服务', version='0.3.0', lifespan=lifespan)
    # 注册顺序即嵌套顺序：后添加的在外层。CORS 必须最外层，错误响应才带 CORS 头。
    application.add_middleware(EnterpriseHttpMiddleware)
    application.add_middleware(CORSMiddleware,
        allow_origins=[value.strip() for value in os.getenv('CORS_ALLOW_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(',')],
        allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization', 'X-API-Key', 'X-Reviewer-Key', 'X-Request-ID'])
    static_dir = Path(__file__).resolve().parent / 'static'
    application.mount('/static', StaticFiles(directory=static_dir), name='static')

    def authenticate(x_api_key: str = Header(default='')) -> None:
        expected = os.getenv('CLAIMS_API_KEY', '')
        if os.getenv('APP_ENV') == 'production' and not expected:
            raise HTTPException(503, '生产环境尚未配置API认证')
        if expected and not hmac.compare_digest(x_api_key, expected):
            raise HTTPException(401, 'API认证失败')

    def authenticate_reviewer(x_reviewer_key: str = Header(default='')) -> None:
        expected = os.getenv('REVIEWER_API_KEY', '')
        if not expected:
            raise HTTPException(503, '尚未配置审核员认证')
        if not hmac.compare_digest(x_reviewer_key, expected):
            raise HTTPException(403, '需要授权审核员')

    def graph_config(claim_id: str) -> dict[str, Any]:
        return {'configurable': {'thread_id': claim_id}}

    def investment_graph_config(request_id: str) -> dict[str, Any]:
        return {'configurable': {'thread_id': f'investment:{request_id}'}, 'recursion_limit': 30}

    def interrupt_value(snapshot: Any) -> dict[str, Any] | None:
        """兼容 StateSnapshot 与 ainvoke 返回值中的 interrupt 表达。"""
        if isinstance(snapshot, dict):
            for item in snapshot.get('__interrupt__') or ():
                value = getattr(item, 'value', item)
                if isinstance(value, dict):
                    return value
        for task in getattr(snapshot, 'tasks', ()) or ():
            for item in getattr(task, 'interrupts', ()) or ():
                value = getattr(item, 'value', None)
                if isinstance(value, dict):
                    return value
        return None

    def interrupt_kind(snapshot: Any) -> str | None:
        value = interrupt_value(snapshot)
        return str(value.get('kind')) if value else None

    def investment_request_from_state(state: dict[str, Any]) -> InvestmentRequest:
        return InvestmentRequest(
            request_id=state['request_id'],
            question=state.get('question') or '投资请求',
            intent=state.get('intent') or '投资咨询',
            risk_profile=state.get('risk_profile'),
            portfolio_id=state.get('portfolio_id'),
            product_id=state.get('product_id'),
            amount=state.get('amount'),
            confirmed=bool(state.get('confirmed')),
        )

    async def status(claim_id: str) -> ClaimResponse:
        snapshot = await application.state.graph.aget_state(graph_config(claim_id))
        state = snapshot.values
        if not state:
            raise HTTPException(404, '未找到案件')
        pending = snapshot.next
        phase = 'awaiting_information' if 'intake' in pending else 'awaiting_review' if 'review' in pending else state.get('phase', 'pending')
        return ClaimResponse(claim_id=claim_id,
            decision='pending' if phase == 'awaiting_information' else 'review' if phase == 'awaiting_review' else state.get('decision', 'pending'),
            phase=phase, confidence=state.get('confidence'), demo=getattr(service.backend, 'demo', False),
            message=mask_pii(state.get('message') or ('需要补充保单编号' if phase == 'awaiting_information' else '等待人工审核')))

    async def invoke(claim_id: str, payload: Any) -> ClaimResponse:
        config, handler = tracing_config(claim_id, cfg)
        start = time.monotonic()
        try:
            limiter.check(claim_id)
            await application.state.graph.ainvoke(payload, config=config)
            result = await status(claim_id)
            REQUESTS.labels(result.decision).inc()
            if result.confidence is not None:
                CONFIDENCE.observe(result.confidence)
            snapshot = await application.state.graph.aget_state(graph_config(claim_id))
            ITERATIONS.observe(len(snapshot.values.get('expert_results', [])) + snapshot.values.get('rounds', 0))
            usage = config['callbacks'][0].snapshot()
            TOKENS.labels('input').inc(usage['prompt_tokens'])
            TOKENS.labels('output').inc(usage['completion_tokens'])
            return result
        except HTTPException:
            raise
        except ValueError as exc:
            ERRORS.labels('validation').inc()
            raise HTTPException(422, '审核输入或模型结果不符合契约') from exc
        except Exception as exc:
            ERRORS.labels(type(exc).__name__).inc()
            if str(exc) == 'rate_limit_exceeded':
                raise HTTPException(429, '该案件请求过于频繁') from exc
            raise HTTPException(503, '处理链路暂不可用，请查询案件状态或转人工') from exc
        finally:
            LATENCY.observe(time.monotonic() - start)
            if handler is not None:
                await asyncio.to_thread(handler.flush)

    @application.get('/health', response_model=HealthResponse, tags=['健康检查'])
    async def health() -> HealthResponse:
        return HealthResponse()

    @application.get('/ready', tags=['健康检查'])
    async def ready(response: Response) -> dict[str, Any]:
        """就绪探针：依赖（图与审计库）未就绪时返回 503，与存活探针区分。"""
        audit = getattr(application.state, 'audit', None)
        checks = {
            'graph': hasattr(application.state, 'graph'),
            'audit': bool(audit is not None and await asyncio.to_thread(audit.ping)),
        }
        ok = all(checks.values())
        if not ok:
            response.status_code = 503
        return {'status': 'ready' if ok else 'not_ready', 'checks': checks}

    @application.get('/', include_in_schema=False)
    async def workbench() -> FileResponse:
        return FileResponse(static_dir / 'index.html')

    @application.get('/favicon.ico', include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @application.get('/metrics', dependencies=[Depends(authenticate)])
    async def export_metrics() -> Response:
        return Response(content=metrics(), media_type='text/plain; version=0.0.4')

    @application.post('/api/demo/claims/process', response_model=DemoClaimRunResponse, tags=['本地演示'])
    async def process_demo_claim() -> DemoClaimRunResponse:
        """使用固定合成数据运行真实状态机，不连接真实业务或执行付款。"""
        if cfg.app_env == 'production':
            raise HTTPException(404, '演示接口在生产环境不可用')
        from claims_agent import DemoServices
        from demos.mock_claim import build_mock_claim

        claim, documents = build_mock_claim()
        claim_data = claim.model_dump(mode='json')
        graph = build_claim_graph(DemoServices())
        state = await graph.ainvoke(
            {'claim_id': claim.claim_id, 'claim_data': claim_data, 'rounds': 0, 'expert_results': []},
            config={'configurable': {'thread_id': claim.claim_id}, 'recursion_limit': 30, 'max_concurrency': 3},
        )
        opinions = {item['expert']: item for item in state['expert_results']}
        trace = [
            {'node': 'claim_intake', 'status': 'done', 'summary': '报案字段完整，可提交正式工作流',
             'input': claim_data, 'output': {'phase': 'ready', 'missing_structured_fields': []}},
            {'node': 'claim_documents', 'status': 'done', 'summary': '已核查 1 份合成单证',
             'input': {'documents': [item.model_dump() for item in documents]},
             'output': {'recognized_count': 1, 'average_extraction_confidence': 0.97, 'warning_count': 0}},
            {'node': 'claim_followup', 'status': 'skipped', 'summary': '基础材料齐全，无需回流追问',
             'input': {'round': 0}, 'output': {'complete': True}},
            {'node': 'claim_policy', 'status': 'done', 'summary': '演示保单与保障责任核验完成',
             'input': {'policy_id': claim.policy_id},
             'output': {'policy': state['policy_info'], 'verification': state['verified']}},
            *(
                {'node': f'claim_{role}', 'status': 'done',
                 'summary': f"建议 {opinions[role]['recommendation']} · 置信度 {opinions[role]['confidence']:.0%}",
                 'input': {'role': role, 'claim_id': claim.claim_id}, 'output': opinions[role]}
                for role in ('damage', 'risk', 'liability')
            ),
            {'node': 'claim_confidence', 'status': 'done',
             'summary': f"三专家最低置信度 {state['confidence']:.0%}",
             'input': {'method': 'min(expert_confidence)',
                       'expert_scores': {role: opinions[role]['confidence'] for role in opinions}},
             'output': {'confidence': state['confidence'], 'risk_score': state['risk_score']}},
            {'node': 'claim_decision', 'status': 'done', 'summary': '规则校验通过，形成自动受理建议',
             'input': {'amount': str(claim.amount),
                       'coverage_verified': state['verified'].get('coverage_verified'),
                       'confidence': state['confidence'], 'risk_score': state['risk_score']},
             'output': {'decision': state['decision'], 'phase': state['phase']}},
        ]
        result = ClaimResponse(
            claim_id=claim.claim_id, decision=state['decision'], phase=state['phase'],
            confidence=state['confidence'], demo=True, message=state['message'],
        )
        return DemoClaimRunResponse(
            claim=claim, documents=documents, result=result, trace=trace,
        )

    @application.post('/api/demo/claims/process-live', response_model=DemoClaimRunResponse, tags=['本地演示'])
    async def process_demo_claim_live() -> DemoClaimRunResponse:
        """用内存条款 + 真实模型跑完整状态机，演示判责 RAG 检索全过程。"""
        if cfg.app_env == 'production':
            raise HTTPException(404, '演示接口在生产环境不可用')
        from demos.mock_claim import build_mock_claim

        claim, documents = build_mock_claim()
        claim_data = claim.model_dump(mode='json')
        graph = build_claim_graph(service)
        state = await graph.ainvoke(
            {'claim_id': claim.claim_id, 'claim_data': claim_data, 'rounds': 0, 'expert_results': []},
            config={'configurable': {'thread_id': claim.claim_id}, 'recursion_limit': 30, 'max_concurrency': 3},
        )
        opinions = {item.get('expert'): item for item in state.get('expert_results', [])}

        def summary(role: str) -> str:
            opinion = opinions.get(role)
            if not opinion:
                return '专家结果缺失'
            text = f"建议 {opinion.get('recommendation')} · 置信度 {opinion.get('confidence', 0):.0%}"
            if opinion.get('clause_ids'):
                text += f" · 引用条款 {', '.join(opinion['clause_ids'])}"
            return text

        trace = [
            {'node': 'claim_intake', 'status': 'done', 'summary': '报案字段完整，可提交正式工作流',
             'input': claim_data, 'output': {'phase': 'ready', 'missing_structured_fields': []}},
            {'node': 'claim_documents', 'status': 'done', 'summary': '已核查 1 份合成单证',
             'input': {'documents': [item.model_dump() for item in documents]},
             'output': {'recognized_count': 1, 'average_extraction_confidence': 0.97, 'warning_count': 0}},
            {'node': 'claim_followup', 'status': 'skipped', 'summary': '基础材料齐全，无需回流追问',
             'input': {'round': 0}, 'output': {'complete': True}},
            {'node': 'claim_policy', 'status': 'done', 'summary': '保单与保障责任核验完成',
             'input': {'policy_id': claim.policy_id},
             'output': {'policy': state.get('policy_info'), 'verification': state.get('verified')}},
            *(
                {'node': f'claim_{role}', 'status': 'done', 'summary': summary(role),
                 'input': {'role': role, 'claim_id': claim.claim_id}, 'output': opinions.get(role)}
                for role in ('damage', 'risk', 'liability')
            ),
            {'node': 'claim_confidence', 'status': 'done',
             'summary': f"三专家最低置信度 {state.get('confidence', 0):.0%}",
             'input': {'method': 'min(expert_confidence)',
                       'expert_scores': {role: opinions[role].get('confidence') for role in opinions}},
             'output': {'confidence': state.get('confidence'), 'risk_score': state.get('risk_score')}},
            {'node': 'claim_decision', 'status': 'done', 'summary': '规则校验完成，形成审核建议',
             'input': {'amount': str(claim.amount),
                       'coverage_verified': state.get('verified', {}).get('coverage_verified'),
                       'confidence': state.get('confidence'), 'risk_score': state.get('risk_score')},
             'output': {'decision': state.get('decision'), 'phase': state.get('phase')}},
        ]
        result = ClaimResponse(
            claim_id=claim.claim_id, decision=state.get('decision', 'review'), phase=state.get('phase', 'complete'),
            confidence=state.get('confidence'), demo=True, message=state.get('message', ''),
        )
        return DemoClaimRunResponse(claim=claim, documents=documents, result=result, trace=trace)

    @application.post('/api/demo/investment/process', response_model=DemoInvestmentRunResponse, tags=['本地演示'])
    async def process_demo_investment() -> DemoInvestmentRunResponse:
        """使用固定合成组合运行投资域图，不连接券商、不执行真实下单。"""
        if cfg.app_env == 'production':
            raise HTTPException(404, '演示接口在生产环境不可用')
        request, state, result = await run_demo_investment()
        return DemoInvestmentRunResponse(
            request=request,
            result=result,
            advice=investment_advice_from_state(state),
            trace=build_demo_trace(state, request),
        )

    @application.post('/api/investment/rag/search', response_model=InvestmentRAGResponse,
                      dependencies=[Depends(authenticate)], tags=['投资域'])
    async def search_investment_rag(body: InvestmentRAGQuery) -> InvestmentRAGResponse:
        """只读检索投资知识库；返回引用，不生成交易建议。"""
        if effective_investment_rag is None:
            raise HTTPException(503, '投资知识库未启用')
        result = await asyncio.to_thread(effective_investment_rag, body.question, body.top_k)
        return InvestmentRAGResponse(**result)

    @application.get('/api/rag/domains', dependencies=[Depends(authenticate)], tags=['RAG'])
    async def list_rag_domains() -> dict[str, Any]:
        """列出已配置的知识库 domain；不触发向量库连接。"""
        if effective_knowledge_rag is None:
            raise HTTPException(503, '知识库 RAG 未启用')
        return {'domains': effective_knowledge_rag.domains()}

    @application.post('/api/rag/search', response_model=KnowledgeSearchResponse,
                      dependencies=[Depends(authenticate)], tags=['RAG'])
    async def search_knowledge_rag(body: KnowledgeRAGQuery) -> KnowledgeSearchResponse:
        """多路召回 + RRF + rerank，返回 Top-K 片段和引用。"""
        if effective_knowledge_rag is None:
            raise HTTPException(503, '知识库 RAG 未启用')
        from tools.knowledge_rag import KnowledgeBaseUnavailable
        try:
            result = await asyncio.to_thread(
                effective_knowledge_rag.retrieve,
                body.domain,
                body.question,
                body.top_k,
                filters=body.filters or None,
            )
        except KeyError as exc:
            raise HTTPException(404, f'未知知识库：{body.domain}') from exc
        except KnowledgeBaseUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return KnowledgeSearchResponse(**result)

    @application.post('/api/rag/answer', response_model=KnowledgeAnswerResponse,
                      dependencies=[Depends(authenticate)], tags=['RAG'])
    async def answer_knowledge_rag(body: KnowledgeRAGQuery) -> KnowledgeAnswerResponse:
        """检索后调用 LLM 生成答案，并校验 citation_ids 只能来自检索结果。"""
        if effective_knowledge_rag is None:
            raise HTTPException(503, '知识库 RAG 未启用')
        from tools.knowledge_rag import KnowledgeAnswerError, KnowledgeBaseUnavailable
        model = knowledge_model or ClaimLLMFactory.create(
            'main', temperature=0.2, max_tokens=1500, response_format='json_object', stop=()
        )
        try:
            result = await effective_knowledge_rag.answer(
                body.domain,
                body.question,
                model,
                body.top_k,
                filters=body.filters or None,
            )
        except KeyError as exc:
            raise HTTPException(404, f'未知知识库：{body.domain}') from exc
        except KnowledgeBaseUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except KnowledgeAnswerError as exc:
            raise HTTPException(502, str(exc)) from exc
        return KnowledgeAnswerResponse(**result)

    @application.post('/api/investment/process', response_model=InvestmentResponse,
                      dependencies=[Depends(authenticate)], tags=['投资域'])
    async def process_investment(request: InvestmentRequest) -> InvestmentResponse:
        """投资咨询直接形成建议；交易指令在二次确认前暂停，不执行下单。"""
        async with locks.setdefault(f'investment:{request.request_id}', asyncio.Lock()):
            config = investment_graph_config(request.request_id)
            snapshot = await application.state.investment_graph.aget_state(config)
            if snapshot.values:
                return investment_state_to_response(
                    snapshot.values, request, interrupted=interrupt_kind(snapshot)
                )
            state = await application.state.investment_graph.ainvoke(
                investment_initial_state(request), config=config
            )
            return investment_state_to_response(
                state, request, interrupted=interrupt_kind(state)
            )

    @application.post('/api/investment/{request_id}/confirm', response_model=InvestmentResponse,
                      dependencies=[Depends(authenticate)], tags=['投资域'])
    async def confirm_investment(request_id: str, body: InvestmentConfirmation) -> InvestmentResponse:
        """二次确认交易指令；确认后进入人工审批，仍未下单。"""
        async with locks.setdefault(f'investment:{request_id}', asyncio.Lock()):
            config = investment_graph_config(request_id)
            snapshot = await application.state.investment_graph.aget_state(config)
            if not snapshot.values:
                raise HTTPException(404, '未找到投资请求')
            request = investment_request_from_state(snapshot.values)
            if interrupt_kind(snapshot) != 'trade_confirmation':
                raise HTTPException(409, '当前请求不处于交易二次确认阶段')
            state = await application.state.investment_graph.ainvoke(
                Command(resume=body.model_dump()), config=config
            )
            return investment_state_to_response(
                state, request, interrupted=interrupt_kind(state)
            )

    @application.post('/api/investment/{request_id}/review', response_model=InvestmentResponse,
                      dependencies=[Depends(authenticate), Depends(authenticate_reviewer)], tags=['投资域'])
    async def review_investment(request_id: str, body: InvestmentReviewInput) -> InvestmentResponse:
        """人工审批交易指令；只有 approve 且适配器实际执行时才标记 executed。"""
        if body.decision == 'reject' and not body.reason:
            raise HTTPException(422, '拒绝交易必须记录理由')
        async with locks.setdefault(f'investment:{request_id}', asyncio.Lock()):
            config = investment_graph_config(request_id)
            snapshot = await application.state.investment_graph.aget_state(config)
            if not snapshot.values:
                raise HTTPException(404, '未找到投资请求')
            request = investment_request_from_state(snapshot.values)
            if interrupt_kind(snapshot) != 'investment_review':
                raise HTTPException(409, '当前请求不处于人工审批阶段')
            state = await application.state.investment_graph.ainvoke(
                Command(resume=mask_pii(body.model_dump())), config=config
            )
            return investment_state_to_response(
                state, request, interrupted=interrupt_kind(state)
            )

    @application.post('/api/claims/process', response_model=ClaimResponse, dependencies=[Depends(authenticate)])
    async def process_claim(request: ClaimRequest) -> ClaimResponse:
        async with locks.setdefault(request.claim_id, asyncio.Lock()):
            existing = await application.state.graph.aget_state(graph_config(request.claim_id))
            if existing.values:
                # 同案号不同内容不能悄悄覆盖检查点。
                if existing.values['claim_data'] != mask_pii(request.model_dump(mode='json')):
                    raise HTTPException(409, '案件已存在；请使用补材料或审核接口')
                return await status(request.claim_id)
            return await invoke(request.claim_id, {'claim_id': request.claim_id,
                'claim_data': mask_pii(request.model_dump(mode='json')), 'rounds': 0, 'expert_results': []})

    @application.get('/api/claims/{claim_id}', response_model=ClaimResponse, dependencies=[Depends(authenticate)])
    async def get_claim(claim_id: str) -> ClaimResponse:
        return await status(claim_id)

    @application.post('/api/claims/{claim_id}/supplement', response_model=ClaimResponse, dependencies=[Depends(authenticate)])
    async def supplement(claim_id: str, body: Supplement) -> ClaimResponse:
        async with locks.setdefault(claim_id, asyncio.Lock()):
            current = await status(claim_id)
            if current.phase != 'awaiting_information':
                raise HTTPException(409, '当前案件不处于补材料阶段')
            return await invoke(claim_id, Command(resume=body.model_dump()))

    @application.post('/api/claims/{claim_id}/review', response_model=ClaimResponse,
                      dependencies=[Depends(authenticate), Depends(authenticate_reviewer)])
    async def review(claim_id: str, body: ReviewInput) -> ClaimResponse:
        if body.decision == 'reject' and not body.clause_basis:
            raise HTTPException(422, '拒赔必须提供核实后的条款依据')
        async with locks.setdefault(claim_id, asyncio.Lock()):
            current = await status(claim_id)
            if current.phase != 'awaiting_review':
                raise HTTPException(409, '当前案件不处于人工审核阶段')
            return await invoke(claim_id, Command(resume=mask_pii(body.model_dump())))

    @application.post('/api/documents/analyze', response_model=DocumentBatchResponse,
                      dependencies=[Depends(authenticate)], tags=['工作台'])
    async def analyze_documents(files: list[UploadFile] = File(...)) -> DocumentBatchResponse:
        """在内存中识别理赔附件，原文件不会写入服务器磁盘。"""
        if not 1 <= len(files) <= 6:
            raise HTTPException(422, '每次必须上传 1 至 6 个附件')
        payloads: list[tuple[str | None, bytes]] = []
        for upload in files:
            content = await upload.read(MAX_DOCUMENT_BYTES + 1)
            payloads.append((upload.filename, content))
            await upload.close()
        text_llm = document_text_model or get_model('extraction')
        vision_llm = document_vision_model or ClaimLLMFactory.create(
            'vision', temperature=0, max_tokens=2000, response_format='json_object', stop=()
        )
        try:
            results = await asyncio.gather(*(
                analyze_document(name, content, text_model=text_llm, vision_model=vision_llm)
                for name, content in payloads
            ))
            return DocumentBatchResponse(documents=results)
        except DocumentValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except DocumentModelOutputError as exc:
            ERRORS.labels('document_output').inc()
            raise HTTPException(502, '单证识别结果格式无效，请重试') from exc
        except Exception as exc:
            ERRORS.labels('document_model').inc()
            raise HTTPException(503, '单证识别模型暂不可用，请检查本地推理服务') from exc

    @application.post('/api/assistant/stream', dependencies=[Depends(authenticate)], tags=['工作台'])
    async def assistant_stream(body: AssistantRequest) -> StreamingResponse:
        """识别意图后，将理赔、投资和一般问题路由到对应模型提示（LangGraph 多节点编排）。"""
        from agents.assistant_agent import build_assistant_graph, chat_content

        context = json.dumps(
            mask_pii([document.model_dump() for document in body.documents]),
            ensure_ascii=False,
        )
        classifier = intent_model or get_model('classification')
        effective_general = general_model or ClaimLLMFactory.create(
            'main', temperature=0.6, max_tokens=1500, response_format='text', stop=()
        )
        effective_assistant = assistant_model or get_model('customer_service')
        effective_investment = investment_model or ClaimLLMFactory.create(
            'main', temperature=0.4, max_tokens=1800, response_format='text', stop=()
        )

        def model_inputs(model: Any, messages: list[Any]) -> dict[str, Any]:
            return {
                'model': getattr(model, 'model_name', '测试模型'),
                'temperature': getattr(model, 'temperature', None),
                'max_tokens': getattr(model, 'max_tokens', None),
                'messages': [{'role': message.type, 'content': message.content} for message in messages],
            }

        async def events():
            started = time.monotonic()
            stage = 'classification'

            def sse(payload: dict[str, Any]) -> str:
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            try:
                graph = build_assistant_graph(
                    classifier=classifier,
                    general_model=effective_general,
                    assistant_model=effective_assistant,
                    investment_model=effective_investment,
                    service=service,
                    investment_rag=effective_investment_rag,
                )
                state = await graph.ainvoke({
                    'question': body.question,
                    'claim_id': body.claim_id,
                    'documents': body.documents,
                    'history': body.history,
                    'material_round': body.material_round,
                    'context': context,
                    'started': started,
                    'events': [],
                })
                stage = state.get('stage', 'claims')
                for event in state.get('events', []):
                    if 'trace' in event:
                        yield sse({'trace': mask_pii(event['trace'])})
                    elif 'intent' in event:
                        yield sse(event)
                    elif 'material_status' in event:
                        yield sse(event)
                    elif 'content' in event:
                        yield sse({'content': mask_pii(event['content'])})
                if state.get('needs_llm_answer', False):
                    llm = state['llm']
                    messages = state['messages']
                    answer_started = time.monotonic()
                    yield sse({'trace': mask_pii({'node': stage, 'status': 'running',
                                                  'model': getattr(llm, 'model_name', '回答模型'),
                                                  'input': model_inputs(llm, messages)})})
                    answer_parts: list[str] = []
                    async for chunk in llm.astream(messages):
                        content = chat_content(chunk)
                        if content:
                            answer_parts.append(content)
                            yield sse({'content': mask_pii(content)})
                    yield sse({'trace': mask_pii({'node': stage, 'status': 'done',
                                                  'elapsed_ms': round((time.monotonic() - answer_started) * 1000),
                                                  'output': {'content': ''.join(answer_parts)}})})
                yield sse({'done': True})
            except Exception as exc:
                logger.exception(
                    'assistant model call failed at stage=%s provider=%s',
                    stage,
                    cfg.model_provider,
                )
                yield sse({'trace': mask_pii({'node': stage, 'status': 'error',
                                              'elapsed_ms': round((time.monotonic() - started) * 1000),
                                              'output': {'error': '调用失败，未返回有效结果',
                                                         'error_type': type(exc).__name__}})})
                ERRORS.labels('assistant_model').inc()
                yield sse({'error': (
                    f'模型调用失败（阶段：{stage}，类型：{type(exc).__name__}），'
                    f'请检查 {cfg.model_provider} 模型服务配置、模型名称和网络连接'
                )})

        return StreamingResponse(
            events(),
            media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    return application


app = create_app()
