"""Строгие схемы Adaptive AI Strategy: аналитический пакет для LLM и его структурированный ответ.

Ответ LLM ВСЕГДА валидируется по этой схеме. Если не проходит — рекомендация отклоняется,
стратегия остаётся на текущей конфигурации. LLM — консультант, не пилот.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class StrategyStats(BaseModel):
    """Что уходит нейросети: срез состояния стратегии (только факты, без look-ahead)."""
    strategy_id: str
    hypothesis: str
    current_params: dict
    tunable_params: dict                      # {имя: [тип, min, max]}
    n_trades: int
    equity_curve_tail: list[float]            # хвост кривой (нормированный)
    total_return: float
    max_drawdown: float
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy: Optional[float] = None
    win_rate: Optional[float] = None
    turnover: Optional[float] = None
    fees_paid: Optional[float] = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    exposure: float = 0.0
    volatility: Optional[float] = None
    regime_signals: dict = Field(default_factory=dict)   # прокси-признаки режима
    metrics_by_window: dict = Field(default_factory=dict)  # метрики на нескольких окнах
    expected_vs_actual: dict = Field(default_factory=dict)
    prior_recommendations: list = Field(default_factory=list)  # что советовали раньше и с каким итогом


class ParamChange(BaseModel):
    name: str
    current: float | int | str
    recommended: float | int | str
    reason: str


class Recommendation(BaseModel):
    """СТРОГИЙ ответ нейросети. Валидируется Pydantic; невалидный = отклонён."""
    market_regime: Literal["trend_up", "trend_down", "range", "high_vol", "crisis", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    regime_change_explanation: str
    param_changes: list[ParamChange] = Field(default_factory=list)
    expected_effect: str
    invalidation_signals: list[str] = Field(default_factory=list)   # когда отменить рекомендацию
    ttl_hours: int = Field(ge=1, le=720)                            # срок действия
    extra_experiments: list[str] = Field(default_factory=list)
    decision: Literal["keep", "test_new", "apply_new", "pause"]     # финальное намерение LLM


class ConsultationRecord(BaseModel):
    """Полный лог консультации: запрос, ответ, провайдер, стоимость, итоговое решение платформы."""
    ts: str
    trigger: str                       # что запустило консультацию
    provider: str                      # anthropic|openai|deterministic
    model: str
    input_hash: str                    # для дедупликации одинаковых пакетов
    recommendation: Optional[dict] = None
    valid: bool = False
    validation_result: Optional[dict] = None   # итог автопроверки бэктестом
    platform_decision: Literal["kept", "applied", "rejected", "paused", "pending"] = "pending"
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
