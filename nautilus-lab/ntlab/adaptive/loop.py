"""Адаптивный цикл: наблюдение → диагностика → рекомендация → автовалидация → решение → память.

Оркестрирует советника (advisor), валидатор и реестр версий. Работает в backtest/shadow БЕЗ
ключей (детерминированный советник). С ключом подключается реальный LLM. Решение о применении
принимает ПЛАТФОРМА после автопроверки, не LLM.
"""
import json, time
from pathlib import Path
from .schema import StrategyStats, ConsultationRecord
from .advisor import make_advisor, _input_hash

MEMORY = Path("/opt/octobot/nautilus-lab/var/adaptive_memory.jsonl")
STATE = Path("/opt/octobot/nautilus-lab/web/data/adaptive_state.json")


class AdaptiveLoop:
    def __init__(self, settings, make_strategy=None):
        self.settings = settings
        self.advisor = make_advisor(settings)
        self.make_strategy = make_strategy       # для автовалидации
        MEMORY.parent.mkdir(parents=True, exist_ok=True)

    def _remember(self, rec: ConsultationRecord):
        with open(MEMORY, "a") as f:
            f.write(json.dumps(rec.model_dump(), ensure_ascii=False, default=str) + "\n")

    def _history(self, n=10):
        if not MEMORY.exists():
            return []
        lines = MEMORY.read_text().strip().splitlines()[-n:]
        return [json.loads(x) for x in lines]

    def consult(self, stats: StrategyStats, trigger="manual", ts=None):
        """Одна итерация цикла. ts — метка (backtest не имеет wall-clock)."""
        ts = ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        stats.prior_recommendations = self._history(5)
        ih = _input_hash(stats)

        t0 = time.time()
        rec = self.advisor.advise(stats)               # Recommendation (валидна по Pydantic)
        latency = int((time.time() - t0) * 1000)

        record = ConsultationRecord(
            ts=ts, trigger=trigger, provider=self.advisor.provider, model=self.advisor.model,
            input_hash=ih, recommendation=rec.model_dump(), valid=True, latency_ms=latency)

        # автовалидация: только если LLM реально предложил менять параметры И есть make_strategy
        if rec.decision in ("test_new", "apply_new") and rec.param_changes and self.make_strategy:
            cur = {c.name: c.current for c in rec.param_changes}
            new = {c.name: c.recommended for c in rec.param_changes}
            from .validator import validate_recommendation
            try:
                vr = validate_recommendation(self.make_strategy, cur, new)
                record.validation_result = vr
                record.platform_decision = "applied" if vr["accept"] else "rejected"
            except Exception as e:
                record.validation_result = {"error": str(e)[:120]}
                record.platform_decision = "rejected"
        elif rec.decision == "pause":
            record.platform_decision = "paused"
        else:
            record.platform_decision = "kept"

        self._remember(record)
        self._write_state(record, stats)
        return record

    def _write_state(self, record: ConsultationRecord, stats: StrategyStats):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        json.dump({
            "strategy": stats.strategy_id,
            "last_consult": record.ts, "trigger": record.trigger,
            "provider": record.provider, "model": record.model,
            "regime": record.recommendation.get("market_regime") if record.recommendation else None,
            "confidence": record.recommendation.get("confidence") if record.recommendation else None,
            "decision": record.recommendation.get("decision") if record.recommendation else None,
            "platform_decision": record.platform_decision,
            "validation": record.validation_result,
            "consultations_total": len(self._history(10_000)),
        }, open(STATE, "w"), ensure_ascii=False, indent=1)


def should_consult(stats: StrategyStats, last_ts=None, cfg=None) -> str | None:
    """Событийный триггер: возвращает причину консультации или None. Не дёргать зря."""
    cfg = cfg or {}
    dd = abs(stats.max_drawdown)
    if dd > cfg.get("dd_trigger", 0.20):
        return f"drawdown {dd*100:.0f}%"
    if stats.sharpe is not None and stats.sharpe < cfg.get("sharpe_trigger", -0.5):
        return f"sharpe {stats.sharpe:+.2f}"
    if stats.n_trades and stats.n_trades % cfg.get("trades_trigger", 50) == 0:
        return f"{stats.n_trades} сделок"
    return None
