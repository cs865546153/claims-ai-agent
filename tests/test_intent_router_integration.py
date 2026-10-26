"""意图路由接入主链路的适配与回落测试。"""

import asyncio
import json
import time
from typing import Any

import httpx
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from agent_core.intent.adapter import AssistantIntentRouter
from agent_core.intent.contracts import RouteDecision
from agent_core.intent.factory import IntentConfig, build_intent_classifier
from agent_core.intent.registry import DomainRegistry
from agents.assistant_agent import active_domain_from_history, build_assistant_graph
from app import build_assistant_intent_router
from models.workbench import ChatTurn


def _state(question: str, history: list[Any] | None = None) -> dict[str, Any]:
    return {
        'question': question,
        'claim_id': None,
        'documents': [],
        'history': history or [],
        'material_round': 0,
        'context': '[]',
        'started': time.monotonic(),
        'events': [],
    }


class FakeRouter:
    """返回固定决策的路由替身，可记录入参或注入异常。"""

    engine_label = 'router(primary=jev,fallback=llm,shadow=none)'

    def __init__(self, *, decision: RouteDecision | None = None, error: Exception | None = None) -> None:
        self.decision = decision
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def classify(self, *, question: str, history=(), attachments=(), active_domain=None):  # noqa: ANN001
        self.calls.append({
            'question': question,
            'history': list(history),
            'attachments': list(attachments),
            'active_domain': active_domain,
        })
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        from agent_core.intent.adapter import AssistantRoute

        return AssistantRoute(
            intent=self.decision.intent,
            confidence=self.decision.confidence,
            policy_id=self.decision.slots.get('policy_id'),
            decision=self.decision,
        )


class FakeModel:
    """只验证协议；系统提示不是意图分类器时返回固定分类 JSON。"""

    model_name = 'fake-intent'

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ANN001 - 测试替身
        self.calls += 1
        return AIMessage(content=self.content)


class FakeService:
    async def policy(self, claim_data: dict[str, Any]) -> dict[str, Any]:
        return {'policy_id': claim_data.get('policy_id'), 'status': '有效', 'coverage': 100000}


class FakeEngine:
    """意图引擎替身（协议：classify(request)），用于验证适配层。"""

    engine_name = 'jev'

    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision
        self.requests: list[Any] = []

    async def classify(self, request):  # noqa: ANN001 - 测试替身
        self.requests.append(request)
        return self.decision


def test_router_adapter_maps_history_and_policy_id() -> None:
    async def scenario() -> None:
        engine = FakeEngine(RouteDecision(
            domain='claims', intent='保单查询', confidence=0.94, engine='jev',
        ))
        router = AssistantIntentRouter(engine)
        route = await router.classify(
            question='帮我查一下保单 POL-2024-001 还有效吗？',
            history=[ChatTurn(role='user', content='你好')],
            attachments=[],
            active_domain='claims',
        )
        assert route.intent == '保单查询'
        assert route.confidence == 0.94
        assert route.policy_id == 'POL-2024-001'
        request = engine.requests[0]
        assert request.message == '帮我查一下保单 POL-2024-001 还有效吗？'
        assert request.history[0].content == '你好'
        assert request.active_domain == 'claims'
        assert router.engine_label.startswith('router(')

    asyncio.run(scenario())


def test_router_adapter_skips_policy_id_for_other_intents() -> None:
    async def scenario() -> None:
        engine = FakeEngine(RouteDecision(
            domain='claims', intent='条款咨询', confidence=0.9, engine='jev',
        ))
        route = await AssistantIntentRouter(engine).classify(
            question='POL-2024-001 这个保险保不保自然灾害？',
        )
        assert route.policy_id is None

    asyncio.run(scenario())


def test_assistant_graph_uses_router_decision() -> None:
    async def scenario() -> None:
        decision = RouteDecision(
            domain='general', intent='一般咨询', confidence=0.97,
            engine='jev', warnings=['cjk_without_translation'],
        )
        router = FakeRouter(decision=decision)
        graph = build_assistant_graph(
            classifier=FakeModel('{"intent":"材料审核","confidence":0.5}'),
            general_model=FakeModel('unused'),
            assistant_model=FakeModel('unused'),
            service=FakeService(),
            intent_router=router,
        )
        state = await graph.ainvoke(_state('Python 列表推导式是什么？'))

        assert state['intent'] == '一般咨询'
        assert state['stage'] == 'general'
        classification = next(event['trace'] for event in state['events']
                              if event.get('trace', {}).get('node') == 'classification'
                              and event['trace']['status'] == 'done')
        assert classification['engine'] == 'jev'
        assert classification['route']['domain'] == 'general'
        assert classification['route']['warnings'] == ['cjk_without_translation']
        intent_event = next(event for event in state['events'] if 'intent' in event)
        assert intent_event['intent_engine'] == 'jev'

    asyncio.run(scenario())


def test_assistant_graph_falls_back_to_builtin_classifier() -> None:
    async def scenario() -> None:
        router = FakeRouter(error=RuntimeError('jev down'))
        model = FakeModel('{"intent":"一般咨询","confidence":0.88}')
        graph = build_assistant_graph(
            classifier=model,
            general_model=FakeModel('unused'),
            assistant_model=FakeModel('unused'),
            service=FakeService(),
            intent_router=router,
        )
        state = await graph.ainvoke(_state('你好'))

        assert model.calls == 1
        assert state['intent'] == '一般咨询'
        classification = next(event['trace'] for event in state['events']
                              if event.get('trace', {}).get('node') == 'classification'
                              and event['trace']['status'] == 'done')
        assert classification['engine'] == 'llm-prompt'
        assert 'RuntimeError' in classification['route_error']

    asyncio.run(scenario())


def test_hybrid_jev_router_drives_graph_end_to_end() -> None:
    """真实 Hybrid + JEV 适配器（MockTransport）驱动对话图，验证接入链路可用。"""

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body['model'] == 'ateve-jev-v1'
            return httpx.Response(200, json={
                'answers': {
                    'domain': {
                        'choice': 'claims',
                        'probabilities': {'claims': 0.97, 'investment': 0.02, 'general': 0.01},
                        'confidence': 0.97,
                    },
                    'intent': {
                        'choice': 'claims:保单查询',
                        'probabilities': {'claims:保单查询': 0.95, 'claims:条款咨询': 0.04},
                        'confidence': 0.95,
                    },
                },
            })

        config = IntentConfig(
            primary='jev', fallback=None, shadow=None,
            jev_base_url='https://example.test/jev', jev_api_key='test-key',
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            classifier = build_intent_classifier(
                config, registry=DomainRegistry.default(), jev_client=client,
            )
            router = AssistantIntentRouter(classifier)
            graph = build_assistant_graph(
                classifier=FakeModel('{"intent":"一般咨询","confidence":0.5}'),
                general_model=FakeModel('unused'),
                assistant_model=FakeModel('unused'),
                service=FakeService(),
                intent_router=router,
            )
            state = await graph.ainvoke(_state('帮我查一下保单 POL-2024-001 还有效吗？'))
            await classifier.aclose()

        assert state['intent'] == '保单查询'
        assert state['policy_id'] == 'POL-2024-001'
        assert any('POL-2024-001' in event.get('content', '') for event in state['events'])
        classification = next(event['trace'] for event in state['events']
                              if event.get('trace', {}).get('node') == 'classification'
                              and event['trace']['status'] == 'done')
        assert classification['engine'] == 'jev'
        assert classification['route']['domain'] == 'claims'

    asyncio.run(scenario())


def test_active_domain_from_history() -> None:
    history = [
        ChatTurn(role='user', content='我的车被追尾了'),
        ChatTurn(role='assistant', content='请先报案', intent='理赔报案'),
    ]
    assert active_domain_from_history(history) == 'claims'
    assert active_domain_from_history([
        ChatTurn(role='assistant', content='好的', intent='投资咨询'),
    ]) == 'investment'
    assert active_domain_from_history([
        ChatTurn(role='assistant', content='好的', intent='一般咨询'),
    ]) is None
    assert active_domain_from_history([]) is None


class FakeIntentSettings:
    """IntentConfig.from_settings 的最小配置面。"""

    intent_router_enabled = True
    intent_engine = 'shadow'
    intent_primary = None
    intent_fallback = None
    intent_shadow = None
    intent_confidence_threshold = 0.8
    intent_margin_threshold = 0.2
    intent_translate_to_english = False
    jev_base_url = 'https://example.test/jev'
    jev_api_key = SecretStr('')
    jev_model = 'ateve-jev-v1'
    jev_timeout_s = 5.0


def test_build_router_respects_switch_and_missing_key() -> None:
    async def scenario() -> None:
        disabled = FakeIntentSettings()
        disabled.intent_router_enabled = False
        assert build_assistant_intent_router(disabled, intent_model=FakeModel('{}')) is None

        router = build_assistant_intent_router(FakeIntentSettings(), intent_model=FakeModel('{}'))
        assert router is not None
        # 没配 JEV key 时影子被跳过，主路由仍是 LLM。
        assert 'primary=llm' in router.engine_label
        assert 'shadow=none' in router.engine_label
        await router.aclose()

    asyncio.run(scenario())


def test_http_stream_uses_wired_router(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture
    """通过真实 /api/assistant/stream 验证 app.py 的注入与 SSE trace。"""
    from fastapi.testclient import TestClient

    from app import create_app

    # conftest 默认关闭路由；本用例显式打开，并固定用 LLM 引擎避免访问 JEV。
    monkeypatch.setenv('INTENT_ROUTER_ENABLED', 'true')
    monkeypatch.setenv('INTENT_ENGINE', 'llm')
    monkeypatch.delenv('JEV_API_KEY', raising=False)

    class RouterModel:
        model_name = 'fake-router'

        def __init__(self) -> None:
            self.system_prompts: list[str] = []

        async def ainvoke(self, messages):  # noqa: ANN001 - 测试替身
            self.system_prompts.append(messages[0].content)
            return AIMessage(content='{"domain":"general","intent":"一般咨询","confidence":0.95}')

        async def astream(self, messages):  # noqa: ANN001 - 测试替身
            yield AIMessage(content='你好。')

    model = RouterModel()
    with TestClient(create_app(database=':memory:', intent_model=model, general_model=model)) as client:
        assert client.app.state.intent_router is not None
        response = client.post('/api/assistant/stream', json={
            'question': '你好', 'documents': [], 'history': [],
        })
        assert response.status_code == 200
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith('data: ')]
        classification = next(event['trace'] for event in events
                              if event.get('trace', {}).get('node') == 'classification'
                              and event['trace']['status'] == 'done')
        assert classification['engine'] == 'llm'
        intent_event = next(event for event in events if 'intent' in event)
        assert intent_event['intent'] == '一般咨询'
        assert intent_event['intent_engine'] == 'llm'
        assert any('跨领域意图路由器' in prompt for prompt in model.system_prompts)
