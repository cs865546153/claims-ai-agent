"""测试隔离：默认关闭主链路意图路由。

单元测试用假模型验证协议，不应访问真实 JEV 服务；需要验证接入的用例
（`tests/test_intent_router_integration.py`）自行用 monkeypatch 打开。
环境变量优先级高于 `.env`，因此本文件放在收集阶段即可生效。
"""
import os

os.environ.setdefault("INTENT_ROUTER_ENABLED", "false")
