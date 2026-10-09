"""FastAPI入口：真实状态机、持久检查点、补材料、审核恢复和可观测指标。"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
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
from agents.claim_agent import WorkflowServices, build_claim_graph
from agents.middleware_audit import configure_logging, mask_pii, RateLimitMiddleware
from agents.observability import tracing_config
from config import ClaimLLMFactory, get_model
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
) -> FastAPI:
    cfg = Settings()
    if cfg.business_mode == 'demo':
        from tools.policy_store import ensure_policy_store
        backend = DemoBackend(policy_store=ensure_policy_store())
    else:
        backend = BusinessBackend()
    service = services or WorkflowServices(backend)
    limiter = RateLimitMiddleware()
    locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        if os.getenv('APP_ENV') == 'production' and (not os.getenv('CLAIMS_API_KEY') or not os.getenv('REVIEWER_API_KEY')):
            raise RuntimeError('生产环境必须配置CLAIMS_API_KEY和REVIEWER_API_KEY')
        path = database or os.getenv('CLAIMS_CHECKPOINT_DB') or '.data/checkpoints.sqlite'
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        configure_logging()
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await saver.setup()
            application.state.graph = build_claim_graph(service, saver)
            yield

    application = FastAPI(title='理赔 Agent 服务', version='0.3.0', lifespan=lifespan)
    application.add_middleware(CORSMiddleware,
        allow_origins=[value.strip() for value in os.getenv('CORS_ALLOW_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(',')],
        allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization', 'X-API-Key', 'X-Reviewer-Key'])
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
        """识别意图后，将理赔问题和一般问题路由到对应模型提示（LangGraph 多节点编排）。"""
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
                    service=service,
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
            except Exception:
                yield sse({'trace': mask_pii({'node': stage, 'status': 'error',
                                              'elapsed_ms': round((time.monotonic() - started) * 1000),
                                              'output': {'error': '调用失败，未返回有效结果'}})})
                ERRORS.labels('assistant_model').inc()
                yield sse({'error': '意图识别或问答模型暂不可用，请检查本地推理服务'})

        return StreamingResponse(
            events(),
            media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    return application


app = create_app()
