"""统一日志配置与模型/图执行追踪。

默认输出到 stderr，与 uvicorn 日志同一终端；可通过环境变量调整：

- ``LOG_LEVEL``：日志级别，默认 INFO。
- ``LOG_FILE``：追加写入文件，默认只输出到终端。
- ``LOG_JSON``：1/true 时输出 JSON Lines，便于 Loki/ELK 采集。
- ``LOG_MODEL_IO``：0/false 关闭模型参数、输入与输出日志，默认开启。
- ``LOG_MODEL_CONTENT_CHARS``：单条消息/输出的预览上限，默认 800；0 表示不记录正文。
- ``LOG_HTTP_BODY``：0/false 关闭请求体摘要日志；生产环境默认关闭。
- ``LOG_LLM_HTTP``：1/true 打开 httpx/openai 传输层日志（仅 URL 与状态，不含报文正文）。

模型与请求日志统一经过 ``mask_pii``，避免密钥、手机号、身份证、银行卡落入日志。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

# 请求 ID 由接入层中间件写入，日志格式统一展示，便于与响应头、审计库串联。
request_id_var: ContextVar[str] = ContextVar('request_id', default='-')

_TEXT_FORMAT = '%(asctime)s %(levelname)-5s %(name)s [%(request_id)s] %(message)s'
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
_APP_LOGGERS = ('claims', 'agents', 'tools', 'adapters', 'models', 'app')
# 第三方 SDK 默认只报 WARNING；打开 LOG_LLM_HTTP 时才显示传输层请求。
_NOISY_LOGGERS = ('httpx', 'httpcore', 'openai', 'urllib3', 'langchain',
                  'langchain_core', 'langchain_openai', 'watchfiles', 'multipart')

_CONFIGURED = False
_CONFIG_LOCK = threading.Lock()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {'0', 'false', 'no', 'off', ''}


def _level(value: str | int | None) -> int:
    """非法配置回退 INFO，日志配置本身不能拖垮服务。"""
    if isinstance(value, int):
        return value
    name = (value or os.getenv('LOG_LEVEL') or 'INFO').strip().upper()
    if name.isdigit():
        return int(name)
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


class _RequestFilter(logging.Filter):
    """给缺少 request_id 的记录补当前请求 ID，格式化器无需感知上下文。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, 'request_id', None):
            record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    """JSON Lines：保留原始消息与异常栈，不展开额外字段。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, 'request_id', '-'),
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _apply_levels(level: int) -> None:
    """应用日志器级别；只调级别，不动 uvicorn/pytest 自己的 handler。"""
    for name in _APP_LOGGERS:
        logging.getLogger(name).setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if _env_bool('LOG_LLM_HTTP', False):
        logging.getLogger('httpx').setLevel(logging.INFO)
        logging.getLogger('httpcore').setLevel(logging.INFO)


def configure_logging(path: str | None = None, *, level: str | int | None = None,
                      force: bool = False) -> None:
    """配置根日志器；重复调用只更新级别，避免热重载后重复输出。"""
    global _CONFIGURED
    with _CONFIG_LOCK:
        target = _level(level)
        root = logging.getLogger()
        if _CONFIGURED and not force:
            root.setLevel(target)
            _apply_levels(target)
            return

        for handler in list(root.handlers):
            if getattr(handler, '_claims_managed', False):
                root.removeHandler(handler)
                handler.close()

        formatter: logging.Formatter
        if _env_bool('LOG_JSON', False):
            formatter = _JsonFormatter()
        else:
            formatter = logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT)

        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(_RequestFilter())
        stream._claims_managed = True  # type: ignore[attr-defined]
        root.addHandler(stream)

        file_path = path or os.getenv('LOG_FILE', '').strip()
        if file_path:
            file_handler = logging.FileHandler(file_path, encoding='utf-8')
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_RequestFilter())
            file_handler._claims_managed = True  # type: ignore[attr-defined]
            root.addHandler(file_handler)

        root.setLevel(target)
        _apply_levels(target)
        _CONFIGURED = True
        logging.getLogger('claims.logging').info(
            'logging.configured level=%s file=%s json=%s model_io=%s',
            logging.getLevelName(target), file_path or '-',
            _env_bool('LOG_JSON', False), _env_bool('LOG_MODEL_IO', True),
        )


def _mask(value: Any) -> Any:
    """延迟导入脱敏实现：logging_setup 被 config 引用，不能反向依赖 agents 包。"""
    try:
        from agents.middleware_audit import mask_pii
    except Exception:  # noqa: BLE001 - 日志脱敏失败不能影响业务
        return value
    try:
        return mask_pii(value)
    except Exception:  # noqa: BLE001
        return value


def _as_text(content: Any) -> str:
    """把消息内容压成文本；多模态只保留类型标记，避免写入 base64。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get('text')
                parts.append(text if isinstance(text, str) else f"[{item.get('type', 'part')}]")
            else:
                parts.append(f'[{type(item).__name__}]')
        return ' '.join(parts)
    return str(content)


def _truncate(text: str, limit: int) -> str:
    if limit > 0 and len(text) > limit:
        return text[:limit] + f'…(+{len(text) - limit})'
    return text


class ModelCallLogger(BaseCallbackHandler):
    """记录每次模型调用的任务、参数、输入、耗时、token 与输出预览。

    handler 挂在模型实例上，因此同步、异步、流式以及 LangGraph 内部调用都能覆盖。
    ``raise_error`` 默认为 False：日志失败只写调试信息，不改变模型调用结果。
    """

    def __init__(self, *, content_chars: int | None = None) -> None:
        self.logger = logging.getLogger('claims.llm')
        env_chars = os.getenv('LOG_MODEL_CONTENT_CHARS', '800').strip()
        self.content_chars = content_chars if content_chars is not None else (
            int(env_chars) if env_chars.isdigit() else 800)
        self._starts: dict[str, tuple[float, str, str]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return _env_bool('LOG_MODEL_IO', True)

    def _preview(self, value: Any) -> str:
        if self.content_chars == 0:
            return '[正文已关闭]'
        return _truncate(_mask(_as_text(value)), self.content_chars)

    def _render_messages(self, messages: list[list[BaseMessage]]) -> list[dict[str, str]]:
        rendered: list[dict[str, str]] = []
        for batch in messages:
            for message in batch:
                rendered.append({
                    'role': getattr(message, 'type', type(message).__name__),
                    'content': self._preview(message.content),
                })
        return rendered

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[BaseMessage]], *,
                            run_id: Any, metadata: dict[str, Any] | None = None,
                            invocation_params: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if not self.enabled:
            return
        try:
            params = dict(invocation_params or {})
            params.pop('_type', None)
            params.pop('stream', None)
            model = str(params.get('model') or params.get('model_name') or 'unknown')
            task = str((metadata or {}).get('task') or (metadata or {}).get('tier') or '-')
            with self._lock:
                self._starts[str(run_id)] = (time.monotonic(), model, task)
            self.logger.info(
                'model.call.start model=%s task=%s messages=%d params=%s input=%s',
                model, task, sum(len(batch) for batch in messages),
                json.dumps(_mask(params), ensure_ascii=False, default=str),
                json.dumps(self._render_messages(messages), ensure_ascii=False),
            )
        except Exception:  # noqa: BLE001 - 可观测性失败不影响模型调用
            self.logger.debug('model.call.start log failed', exc_info=True)

    def on_llm_end(self, response: LLMResult, *, run_id: Any, **kwargs: Any) -> None:
        if not self.enabled:
            return
        try:
            started = self._pop(run_id)
            elapsed = (time.monotonic() - started[0]) * 1000 if started else -1
            model, task = (started[1], started[2]) if started else ('unknown', '-')
            generation = response.generations[0][0] if response.generations else None
            message = getattr(generation, 'message', None)
            usage = self._usage(response, message)
            finish = self._finish_reason(generation, message)
            output = self._preview(getattr(message, 'content', '') or
                                   (getattr(generation, 'text', '') if generation else ''))
            tool_calls = getattr(message, 'tool_calls', None) or []
            self.logger.info(
                'model.call.end model=%s task=%s latency_ms=%.1f tokens=%s finish=%s tool_calls=%s output=%s',
                model, task, elapsed, json.dumps(usage, ensure_ascii=False), finish or '-',
                json.dumps([call.get('name', '?') for call in tool_calls], ensure_ascii=False), output,
            )
        except Exception:  # noqa: BLE001
            self.logger.debug('model.call.end log failed', exc_info=True)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        if not self.enabled:
            return
        started = self._pop(run_id)
        elapsed = (time.monotonic() - started[0]) * 1000 if started else -1
        model, task = (started[1], started[2]) if started else ('unknown', '-')
        self.logger.error('model.call.error model=%s task=%s latency_ms=%.1f error=%s: %s',
                          model, task, elapsed, type(error).__name__, self._preview(str(error)))

    def _pop(self, run_id: Any) -> tuple[float, str, str] | None:
        with self._lock:
            return self._starts.pop(str(run_id), None)

    @staticmethod
    def _usage(response: LLMResult, message: Any) -> dict[str, int]:
        usage = (response.llm_output or {}).get('token_usage') or {}
        prompt = int(usage.get('prompt_tokens') or 0)
        completion = int(usage.get('completion_tokens') or 0)
        total = int(usage.get('total_tokens') or (prompt + completion))
        native = getattr(message, 'usage_metadata', None) if message is not None else None
        if not total and native:
            prompt = int(native.get('input_tokens') or 0)
            completion = int(native.get('output_tokens') or 0)
            total = int(native.get('total_tokens') or (prompt + completion))
        if not total:
            return {}
        return {'prompt': prompt, 'completion': completion, 'total': total}

    @staticmethod
    def _finish_reason(generation: Any, message: Any) -> str | None:
        metadata = getattr(message, 'response_metadata', None) or {}
        reason = metadata.get('finish_reason')
        if reason is None:
            info = getattr(generation, 'generation_info', None) or {}
            reason = info.get('finish_reason')
        return str(reason) if reason is not None else None


class GraphTraceLogger(BaseCallbackHandler):
    """按 ``langgraph_node`` 记录节点开始/结束与耗时，不记录状态正文。

    LangGraph 的元数据会被子 Runnable 继承，因此通过父子 run 关系去重，
    只记录真正的节点执行，避免每个内部步骤都重复一条。
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger('claims.graph')
        self._starts: dict[str, tuple[str, float]] = {}
        self._descendants: set[str] = set()
        self._lock = threading.Lock()

    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: Any,
                       parent_run_id: Any = None, metadata: dict[str, Any] | None = None,
                       **kwargs: Any) -> None:
        key = str(run_id)
        parent = str(parent_run_id) if parent_run_id else None
        with self._lock:
            if parent and parent in self._descendants:
                self._descendants.add(key)
                return
            node = (metadata or {}).get('langgraph_node')
            if not node or str(node).startswith('__'):
                return
            self._starts[key] = (str(node), time.monotonic())
            self._descendants.add(key)
        self.logger.info('graph.node.start node=%s', node)

    def on_chain_end(self, outputs: Any, *, run_id: Any, **kwargs: Any) -> None:
        self._finish(str(run_id), None)

    def on_chain_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        self._finish(str(run_id), error)

    def _finish(self, key: str, error: BaseException | None) -> None:
        with self._lock:
            started = self._starts.pop(key, None)
            self._descendants.discard(key)
        if started is None:
            return
        node, begin = started
        elapsed = (time.monotonic() - begin) * 1000
        if error is None:
            self.logger.info('graph.node.end node=%s latency_ms=%.1f', node, elapsed)
        else:
            self.logger.error('graph.node.error node=%s latency_ms=%.1f error=%s: %s',
                              node, elapsed, type(error).__name__, _truncate(_mask(str(error)), 500))


MODEL_CALL_LOGGER = ModelCallLogger()
GRAPH_TRACE_LOGGER = GraphTraceLogger()
