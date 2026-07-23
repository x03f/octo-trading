"""Тест адаптивного цикла без ключей: диагностика → рекомендация → решение платформы → память."""
import sys
sys.path.insert(0, "/opt/octobot/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
from ntlab.core.config import settings
from ntlab.adaptive.schema import StrategyStats, Recommendation
from ntlab.adaptive.loop import AdaptiveLoop, should_consult


def _stats(**kw):
    base = dict(strategy_id="TEST", hypothesis="x", current_params={"chan_n": 20},
                tunable_params={"chan_n": ["int", 5, 50]}, n_trades=40,
                equity_curve_tail=[1.0, 1.02, 1.01], total_return=0.03,
                max_drawdown=-0.08, sharpe=0.6, volatility=0.5, regime_signals={"trend": 0.2})
    base.update(kw)
    return StrategyStats(**base)


def test_schema_validation():
    r = Recommendation(market_regime="range", confidence=0.5, regime_change_explanation="x",
                       expected_effect="y", ttl_hours=24, decision="keep")
    assert r.confidence == 0.5
    try:
        Recommendation(market_regime="range", confidence=1.5, regime_change_explanation="x",
                       expected_effect="y", ttl_hours=24, decision="keep")
        assert False, "confidence>1 должен упасть"
    except Exception:
        pass


def test_healthy_keeps():
    loop = AdaptiveLoop(settings)
    rec = loop.consult(_stats(), trigger="schedule", ts="2026-07-24T00:00:00Z")
    assert rec.valid
    assert rec.platform_decision in ("kept", "applied", "rejected")
    assert rec.recommendation["decision"] == "keep"


def test_degraded_pauses():
    loop = AdaptiveLoop(settings)
    bad = _stats(sharpe=-0.9, max_drawdown=-0.32)
    trig = should_consult(bad)
    assert trig and "drawdown" in trig
    rec = loop.consult(bad, trigger=trig, ts="2026-07-24T01:00:00Z")
    assert rec.recommendation["decision"] == "pause"
    assert rec.platform_decision == "paused"


def test_no_key_uses_deterministic():
    loop = AdaptiveLoop(settings)
    assert loop.advisor.provider == "deterministic"   # без ключа — безопасный дефолт


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}"); n += 1
    print(f"АДАПТИВНЫЙ ЦИКЛ: {n}/{n} тестов прошли")
