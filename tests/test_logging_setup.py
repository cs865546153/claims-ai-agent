"""统一日志：根日志器、脱敏、模型参数与 token 记录。"""

import json
import logging

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from logging_setup import ModelCallLogger, configure_logging


@pytest.fixture(autouse=True)
def reset_logging():
    """每个用例强制重建 handler，避免全局配置影响其他测试。"""
    yield
    configure_logging(force=True, level='INFO')


def test_configure_logging_is_idempotent() -> None:
    configure_logging(force=True, level='INFO')
    managed = [h for h in logging.getLogger().handlers if getattr(h, '_claims_managed', False)]
    configure_logging()
    again = [h for h in logging.getLogger().handlers if getattr(h, '_claims_managed', False)]
    assert len(managed) == len(again) == 1


def test_app_logger_info_is_emitted(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging(force=True, level='INFO')
    caplog.set_level(logging.INFO, logger='claims.http')
    logging.getLogger('claims.http').info('request accepted')
    assert 'request accepted' in caplog.text


def test_model_call_logs_parameters_and_masks_pii(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging(force=True, level='INFO')
    caplog.set_level(logging.INFO, logger='claims.llm')

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload['temperature'] == 0.2
        assert payload['max_completion_tokens'] == 100
        return httpx.Response(200, json={
            'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'demo',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': '已收到案件'}}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 5, 'total_tokens': 17},
        })

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        model = ChatOpenAI(model='demo', temperature=0.2, max_tokens=100, seed=42,
                           base_url='http://127.0.0.1:8000/v1', api_key='test',
                           http_client=client, callbacks=[ModelCallLogger()],
                           metadata={'task': 'coverage'})
        model.invoke([HumanMessage(content='手机号13812345678，请分析责任')])

    assert 'model.call.start' in caplog.text
    assert 'task=coverage' in caplog.text
    assert '手机号[手机号]' in caplog.text
    assert '13812345678' not in caplog.text
    assert 'model.call.end' in caplog.text
    assert '"total": 17' in caplog.text
    assert 'finish=stop' in caplog.text
    assert 'output=已收到案件' in caplog.text


def test_model_io_can_be_disabled(monkeypatch: pytest.MonkeyPatch,
                                   caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv('LOG_MODEL_IO', 'false')
    caplog.set_level(logging.INFO, logger='claims.llm')
    logger = ModelCallLogger()
    logger.on_chat_model_start({}, [[HumanMessage(content='敏感内容')]], run_id='run-1')
    assert 'model.call.start' not in caplog.text
