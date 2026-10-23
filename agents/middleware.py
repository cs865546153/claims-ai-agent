"""主项目中间件入口；官方 Deep Agents 中间件位于独立环境示例。

分两层：
- 接入层：EnterpriseHttpMiddleware（请求 ID / 认证 / 限流 / 审计 / 异常兜底），对每个 HTTP 请求生效；
- 模型调用层：MiddlewareChain（三专家的限流 / 缓存 / 熔断 / 降级）。
"""
from agents.audit_store import AuditStore
from agents.http_middleware import EnterpriseHttpMiddleware, HttpRateLimiter
from agents.middleware_audit import AuditLogMiddleware, ComplianceMiddleware, MiddlewareChain, mask_pii

PIIMaskMiddleware = ComplianceMiddleware
AuditMiddleware = AuditLogMiddleware
__all__ = [
    'PIIMaskMiddleware',
    'AuditMiddleware',
    'MiddlewareChain',
    'mask_pii',
    'AuditStore',
    'EnterpriseHttpMiddleware',
    'HttpRateLimiter',
]
