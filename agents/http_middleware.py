"""统一 HTTP 中间件：请求 ID → 认证 → 限流 → 审计 → 异常兜底。

与 agents/middleware_audit.MiddlewareChain 的分工：
- 本模块是「接入层管线」，对每个 HTTP 请求生效，新增路由自动继承；
- MiddlewareChain 是「模型调用层」，只负责三专家的限流/缓存/熔断/降级。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from starlette.datastructures import MutableHeaders

from agents.middleware_audit import RateLimitMiddleware, mask_pii
from logging_setup import request_id_var, retrieval_diagnostics_var

LOGGER = logging.getLogger('claims.http')

_REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]{8,64}$')
_SKIP_AUDIT_PATHS = {'/health', '/ready', '/metrics', '/favicon.ico', '/'}
_SKIP_AUDIT_PREFIXES = ('/static/',)
_MAX_AUDIT_BODY = 2048
_MAX_AUDIT_INPUT = 65536


def _header(scope: dict[str, Any], name: str) -> str:
    target = name.lower().encode('latin-1')
    for key, value in scope.get('headers', ()):
        if key.lower() == target:
            return value.decode('latin-1')
    return ''


def _request_id(scope: dict[str, Any]) -> str:
    """复用上游传入的请求 ID（便于网关串联），非法值一律重新生成。"""
    incoming = _header(scope, 'x-request-id')
    return incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex


def _client_ip(scope: dict[str, Any]) -> str:
    forwarded = _header(scope, 'x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    client = scope.get('client')
    return client[0] if client else 'unknown'


def _ip_hash(ip: str) -> str:
    """审计只存哈希：既可关联同一来源，又不落原始 IP。"""
    return hashlib.sha256(ip.encode('utf-8')).hexdigest()[:16]


def _is_protected(path: str) -> bool:
    """演示接口保持公开（生产环境自身返回 404），其余 /api/ 均要求认证。"""
    return path.startswith('/api/') and not path.startswith('/api/demo/')


def _limit_kind(path: str) -> str:
    if path == '/api/assistant/stream':
        return 'stream'
    if path.startswith('/api/documents/'):
        return 'documents'
    return 'general'


def _log_body_enabled() -> bool:
    """请求体摘要默认只在非生产环境记录，生产需显式开启。"""
    value = os.getenv('LOG_HTTP_BODY')
    if value is None:
        return os.getenv('APP_ENV', 'development') != 'production'
    return value.strip().lower() not in {'0', 'false', 'no', 'off', ''}


class HttpRateLimiter:
    """接入层限流：按「身份 + 来源 IP + 接口类别」分桶，默认值可通过环境变量调整。

    当前为进程内实现；多副本部署时应替换为 Redis 原子脚本（接口保持不变）。
    """

    def __init__(self, *, general_per_minute: int = 1200, stream_per_minute: int = 120,
                 documents_per_minute: int = 120, enabled: bool = True) -> None:
        self.enabled = enabled
        self.limiters = {
            'general': RateLimitMiddleware(capacity=max(1, general_per_minute),
                                           refill_per_second=max(1, general_per_minute) / 60),
            'stream': RateLimitMiddleware(capacity=max(1, stream_per_minute),
                                          refill_per_second=max(1, stream_per_minute) / 60),
            'documents': RateLimitMiddleware(capacity=max(1, documents_per_minute),
                                             refill_per_second=max(1, documents_per_minute) / 60),
        }

    @classmethod
    def from_env(cls) -> 'HttpRateLimiter':
        return cls(
            general_per_minute=int(os.getenv('HTTP_RATE_LIMIT_PER_MINUTE', '1200')),
            stream_per_minute=int(os.getenv('HTTP_STREAM_RATE_LIMIT_PER_MINUTE', '120')),
            documents_per_minute=int(os.getenv('HTTP_DOCUMENT_RATE_LIMIT_PER_MINUTE', '120')),
            enabled=os.getenv('HTTP_RATE_LIMIT_ENABLED', 'true').lower() not in {'0', 'false', 'no'},
        )

    def check(self, key: str, kind: str) -> None:
        if self.enabled:
            self.limiters[kind].check(key)


class EnterpriseHttpMiddleware:
    """纯 ASGI 实现：不缓冲响应，兼容 SSE 流式输出。"""

    def __init__(self, app: Any, *, max_body_bytes: int | None = None,
                 rate_limiter: HttpRateLimiter | None = None) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes or int(os.getenv('HTTP_MAX_BODY_BYTES', str(64 * 1024 * 1024)))
        self.rate_limiter = rate_limiter or HttpRateLimiter.from_env()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        token = request_id_var.set(request_id)
        retrieval_sink: list[dict[str, Any]] = []
        retrieval_token = retrieval_diagnostics_var.set(retrieval_sink)
        path = scope.get('path', '')
        method = scope.get('method', 'GET')
        started = time.monotonic()
        response_state: dict[str, Any] = {}
        actor = 'anonymous'
        body_excerpt: Any = None
        error: str | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message['type'] == 'http.response.start':
                response_state['status'] = message['status']
                MutableHeaders(scope=message).setdefault('X-Request-ID', request_id)
            await send(message)

        try:
            actor = self._authenticate(scope, path)
            if isinstance(actor, tuple):  # (status, message) 认证失败
                error = 'authentication_failed'
                await self._reject(send, actor[0], actor[1], request_id)
                return

            size_error = self._check_size(scope)
            if size_error is not None:
                error = 'payload_too_large'
                await self._reject(send, 413, size_error, request_id)
                return

            self.rate_limiter.check(f'{actor}:{_ip_hash(_client_ip(scope))}', _limit_kind(path))

            if self._should_buffer(scope):
                body, receive = await self._read_body(receive)
                body_excerpt = self._summarize(body)

            await self.app(scope, receive, send_wrapper)
        except RuntimeError as exc:
            error = 'rate_limited' if str(exc) == 'rate_limit_exceeded' else type(exc).__name__
            if str(exc) == 'rate_limit_exceeded' and 'status' not in response_state:
                await self._reject(send, 429, '请求过于频繁，请稍后重试', request_id, retry_after=1)
            elif 'status' not in response_state:
                LOGGER.exception('unhandled runtime error request_id=%s', request_id)
                await self._reject(send, 500, '服务内部错误', request_id)
        except Exception as exc:  # noqa: BLE001 - 兜底必须覆盖任意未处理异常
            error = type(exc).__name__
            LOGGER.exception('unhandled error request_id=%s path=%s', request_id, path)
            if 'status' not in response_state:
                await self._reject(send, 500, '服务内部错误', request_id)
        finally:
            try:
                status = int(response_state.get('status', 500))
                await self._audit(scope, request_id, actor, method, path, status,
                                  (time.monotonic() - started) * 1000, body_excerpt, error,
                                  retrieval=retrieval_sink)
            finally:
                retrieval_diagnostics_var.reset(retrieval_token)
                request_id_var.reset(token)

    def _authenticate(self, scope: dict[str, Any], path: str) -> str | tuple[int, str]:
        api_key = _header(scope, 'x-api-key')
        reviewer_key = _header(scope, 'x-reviewer-key')
        expected = os.getenv('CLAIMS_API_KEY', '')
        expected_reviewer = os.getenv('REVIEWER_API_KEY', '')
        production = os.getenv('APP_ENV') == 'production'

        actor = 'anonymous'
        if reviewer_key and expected_reviewer and hmac.compare_digest(reviewer_key, expected_reviewer):
            actor = 'reviewer'
        elif api_key and expected and hmac.compare_digest(api_key, expected):
            actor = 'api-client'

        if not _is_protected(path):
            return actor
        if expected:
            if not api_key or not hmac.compare_digest(api_key, expected):
                return 401, 'API认证失败'
        elif production:
            return 503, '生产环境尚未配置API认证'
        return actor

    def _check_size(self, scope: dict[str, Any]) -> str | None:
        raw = _header(scope, 'content-length')
        if raw.isdigit() and int(raw) > self.max_body_bytes:
            return f'请求体超过上限 {self.max_body_bytes} 字节'
        return None

    @staticmethod
    def _should_buffer(scope: dict[str, Any]) -> bool:
        content_type = _header(scope, 'content-type').lower()
        raw = _header(scope, 'content-length')
        return content_type.startswith('application/json') and raw.isdigit() and int(raw) <= _MAX_AUDIT_INPUT

    async def _read_body(self, receive: Any) -> tuple[bytes, Any]:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                break
            chunks.append(message.get('body', b''))
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        replayed = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            # 不能伪造 http.disconnect：StreamingResponse 会监听断连事件，
            # 一旦收到就会取消 SSE 流，导致响应体为空。这里交还给底层 receive。
            return await receive()

        return body, replay

    @staticmethod
    def _summarize(body: bytes) -> Any:
        """审计只保留脱敏后的摘要，避免把原始凭证写进库。"""
        if not body:
            return None
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return mask_pii(body[:200].decode('utf-8', 'replace'))
        return mask_pii(parsed)

    @staticmethod
    def _should_audit(path: str) -> bool:
        return path not in _SKIP_AUDIT_PATHS and not path.startswith(_SKIP_AUDIT_PREFIXES)

    async def _audit(self, scope: dict[str, Any], request_id: str, actor: str, method: str,
                     path: str, status: int, latency_ms: float, body: Any, error: str | None,
                     *, retrieval: list[dict[str, Any]] | None = None) -> None:
        if not self._should_audit(path):
            return
        body_text = ''
        if body is not None and _log_body_enabled():
            rendered = json.dumps(body, ensure_ascii=False, default=str)
            body_text = ' body=' + (rendered[:1000] + '…' if len(rendered) > 1000 else rendered)
        LOGGER.info('http.request method=%s path=%s status=%s actor=%s latency_ms=%.1f error=%s%s',
                    method, path[:200], status, actor, latency_ms, error or '-', body_text)
        store = getattr(scope.get('app').state, 'audit', None)
        if store is None:
            return
        details = {
            'method': method,
            'path': path[:200],
            'query': mask_pii(scope.get('query_string', b'').decode('latin-1'))[:200],
            'ip_hash': _ip_hash(_client_ip(scope)),
            'user_agent': _header(scope, 'user-agent')[:120],
            'body': body,
            'error': error,
        }
        if retrieval:
            details['retrieval'] = retrieval
        try:
            await asyncio.to_thread(
                store.record,
                request_id=request_id, actor=actor, action=method, resource=path[:200],
                status=status, latency_ms=latency_ms, details=details,
            )
        except Exception:  # noqa: BLE001 - 审计失败不能影响业务响应
            LOGGER.exception('audit write failed request_id=%s', request_id)

    @staticmethod
    async def _reject(send: Any, status: int, detail: str, request_id: str,
                      *, retry_after: int | None = None) -> None:
        payload = json.dumps({'detail': detail, 'request_id': request_id}, ensure_ascii=False).encode('utf-8')
        headers = [
            (b'content-type', b'application/json; charset=utf-8'),
            (b'content-length', str(len(payload)).encode()),
            (b'x-request-id', request_id.encode()),
        ]
        if retry_after is not None:
            headers.append((b'retry-after', str(retry_after).encode()))
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({'type': 'http.response.body', 'body': payload})
