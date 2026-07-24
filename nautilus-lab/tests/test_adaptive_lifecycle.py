"""E2E тест жизненного цикла Adaptive AI без ключей (mock LLM + deterministic валидация)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
import ntlab.adaptive.lifecycle as lc
from ntlab.adaptive.lifecycle import LifecycleManager, classical_adaptation, STAGES
from ntlab.adaptive.advisor import MockAdvisor, DeterministicAdvisor
from ntlab.adaptive.schema import StrategyStats, Recommendation


def _fresh(tmp):
    lc.REG = Path(tmp) / "versions.jsonl"
    lc.STATE = Path(tmp) / "lifecycle.json"


def _stats(**kw):
    base = dict(strategy_id="TEST", hypothesis="x", current_params={"chan_n": 20},
                tunable_params={"chan_n": ["int", 5, 50]}, n_trades=40,
                equity_curve_tail=[1.0], total_return=0.03, max_drawdown=-0.08,
                sharpe=0.6, volatility=0.5, regime_signals={"trend": 0.2, "vol_ref": 0.4})
    base.update(kw); return StrategyStats(**base)


def test_mock_advisor_proposes_param():
    adv = MockAdvisor(propose_param="chan_n", propose_value=25)
    rec = adv.advise(_stats())
    assert rec.decision == "test_new"
    assert rec.param_changes[0].recommended == 25
    assert MockAdvisor.estimate_cost() > 0     # учёт стоимости API


def test_deterministic_keeps_when_healthy():
    rec = DeterministicAdvisor().advise(_stats())
    assert rec.decision == "keep"


def test_lifecycle_champion_challenger_promote():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m = LifecycleManager()
        champ = m.set_baseline({"chan_n": 20}, source="manual")
        assert m.champion["version"] == champ["version"]
        # challenger в shadow с валидацией
        ch = m.propose_challenger({"chan_n": 25}, source="mock-llm",
                                  validation={"accept": True, "recommended_test_sharpe": 0.5})
        assert ch["stage"] == "shadow"
        # продвижение по стадиям
        m.promote(ch["version"], "paper_canary", result={"pnl": 1.2})
        m.promote(ch["version"], "live_canary", result={"pnl": 0.8})
        m.promote(ch["version"], "champion", result={"pnl": 2.0})
        assert m.champion["version"] == ch["version"]
        assert m.champion["params"]["chan_n"] == 25


def test_lifecycle_cannot_skip_stage():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m = LifecycleManager()
        m.set_baseline({"chan_n": 20})
        ch = m.propose_challenger({"chan_n": 30}, "mock-llm", {"accept": True})
        try:
            m.promote(ch["version"], "live_canary")   # перепрыгнули paper_canary
            assert False, "должно запретить перепрыгивание"
        except ValueError:
            pass


def test_lifecycle_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m = LifecycleManager()
        m.set_baseline({"chan_n": 20})
        ch = m.propose_challenger({"chan_n": 30}, "mock-llm", {"accept": True})
        m.promote(ch["version"], "paper_canary")
        m.promote(ch["version"], "live_canary")
        m.promote(ch["version"], "champion")
        assert m.champion["params"]["chan_n"] == 30
        # деградация -> откат к предыдущему стабильному (chan_n=20)
        restored = m.rollback()
        assert restored is not None
        assert m.champion["params"]["chan_n"] == 20
        assert restored["source"] == "rollback"


def test_classical_adaptation_baseline():
    # сравнение с классической алго-адаптацией (без LLM)
    high_vol = _stats(volatility=0.8, regime_signals={"vol_ref": 0.4})
    new = classical_adaptation(high_vol, {"chan_n": 20})
    assert new["chan_n"] > 20     # выросла волатильность -> окно шире (консервативнее)
    low_vol = _stats(volatility=0.2, regime_signals={"vol_ref": 0.4})
    new2 = classical_adaptation(low_vol, {"chan_n": 20})
    assert new2["chan_n"] < 20


def test_e2e_full_cycle():
    """Полный цикл: наблюдение -> mock LLM предлагает -> валидация -> challenger -> canary -> champion."""
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m = LifecycleManager()
        m.set_baseline({"chan_n": 20}, source="manual")
        adv = MockAdvisor(propose_param="chan_n", propose_value=25)
        rec = adv.advise(_stats())
        assert rec.decision == "test_new"
        # валидация рекомендации (симулируем accept)
        validation = {"accept": True, "current_test_sharpe": 0.3, "recommended_test_sharpe": 0.6}
        if validation["accept"]:
            ch = m.propose_challenger({"chan_n": rec.param_changes[0].recommended}, adv.provider, validation)
            m.promote(ch["version"], "paper_canary", result={"ok": True})
            m.promote(ch["version"], "live_canary", result={"ok": True})
            m.promote(ch["version"], "champion", result={"ok": True})
        assert m.champion["params"]["chan_n"] == 25
        assert lc.STATE.exists()


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}"); n += 1
    print(f"ADAPTIVE LIFECYCLE E2E: {n}/{n}")
