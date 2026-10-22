"""理赔与投资场景提示词及版本管理公共接口。"""
from prompts.investment_prompt import (
    INVESTMENT_ADVISOR_PROMPT,
    INVESTMENT_RISK_PROMPT,
    INVESTMENT_TRADE_PROMPT,
    InvestmentAdvisorPrompt,
)
from prompts.review_prompt import ClaimIntakePrompt, ClaimReviewPrompt, ClaimServicePrompt, PromptRegistry
from prompts.risk_prompt import FraudAnalysisPrompt

__all__ = [
    'ClaimIntakePrompt',
    'ClaimReviewPrompt',
    'ClaimServicePrompt',
    'FraudAnalysisPrompt',
    'InvestmentAdvisorPrompt',
    'INVESTMENT_ADVISOR_PROMPT',
    'INVESTMENT_RISK_PROMPT',
    'INVESTMENT_TRADE_PROMPT',
    'PromptRegistry',
]
