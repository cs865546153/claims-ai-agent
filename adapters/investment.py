"""投资域业务适配器：真实接口未配置时显式失败，演示数据明确标记。"""

from collections.abc import Callable
from typing import Any


class InvestmentBackend:
    """投资业务适配器注册表；不猜测券商、基金平台或行情协议。"""

    demo = False

    def __init__(self, adapters: dict[str, Callable[..., dict[str, Any]]] | None = None) -> None:
        self.adapters = adapters or {}

    def call(self, action: str, **parameters: Any) -> dict[str, Any]:
        if action in self.adapters:
            return self.adapters[action](**parameters)
        raise RuntimeError(f"investment_adapter_not_configured:{action}")


class DemoInvestmentBackend(InvestmentBackend):
    """固定合成组合、产品和行情；不连接真实账户，也不执行真实下单。"""

    demo = True

    def __init__(self) -> None:
        super().__init__()

    def call(self, action: str, **parameters: Any) -> dict[str, Any]:
        if action == "query_portfolio":
            portfolio_id = parameters.get("portfolio_id") or "PORT-DEMO-001"
            return {
                "portfolio_id": portfolio_id,
                "as_of": "2026-10-23",
                "currency": "CNY",
                "total_value": "268000.00",
                "risk_profile": "稳健型",
                "holdings": [
                    {
                        "product_id": "FUND-DEMO-001",
                        "name": "稳健债券基金（演示）",
                        "asset_class": "债券",
                        "risk_level": "低",
                        "weight": "0.62",
                        "market_value": "166160.00",
                    },
                    {
                        "product_id": "FUND-DEMO-002",
                        "name": "宽基指数基金（演示）",
                        "asset_class": "权益",
                        "risk_level": "中",
                        "weight": "0.28",
                        "market_value": "75040.00",
                    },
                    {
                        "product_id": "CASH-DEMO-001",
                        "name": "现金管理（演示）",
                        "asset_class": "现金",
                        "risk_level": "低",
                        "weight": "0.10",
                        "market_value": "26800.00",
                    },
                ],
                "demo": True,
                "source": "演示合成组合，非真实持仓",
            }
        if action == "query_product":
            product_id = parameters.get("product_id") or "FUND-DEMO-001"
            products = {
                "FUND-DEMO-001": {
                    "product_id": "FUND-DEMO-001",
                    "name": "稳健债券基金（演示）",
                    "asset_class": "债券",
                    "risk_level": "低",
                    "historical_return": "3.20%",
                    "max_drawdown": "-1.80%",
                    "fee": "0.30%",
                },
                "FUND-DEMO-002": {
                    "product_id": "FUND-DEMO-002",
                    "name": "宽基指数基金（演示）",
                    "asset_class": "权益",
                    "risk_level": "中",
                    "historical_return": "8.60%",
                    "max_drawdown": "-18.40%",
                    "fee": "0.50%",
                },
            }
            return {
                **products.get(product_id, {
                    "product_id": product_id,
                    "name": "未登记演示产品",
                    "asset_class": "待核实",
                    "risk_level": "待核实",
                    "historical_return": None,
                    "max_drawdown": None,
                    "fee": None,
                }),
                "demo": True,
                "source": "演示合成产品数据，非真实净值或收益承诺",
            }
        if action == "query_market":
            return {
                "as_of": "2026-10-23",
                "indices": [
                    {"name": "沪深300（演示）", "change": "+0.42%"},
                    {"name": "中证全债（演示）", "change": "+0.08%"},
                ],
                "interest_rate": "待核实",
                "demo": True,
                "source": "演示合成行情，非实时市场数据",
            }
        if action == "submit_trade":
            return {
                "order_id": "ORD-DEMO-2026-001",
                "outbox_id": "OUT-DEMO-2026-001",
                "status": "pending_execution",
                "executed": False,
                "demo": True,
                "source": "演示环境只生成待执行事件，未连接券商或基金平台",
            }
        raise RuntimeError(f"演示投资后端不执行该操作：{action}")
