"""P10/E2E: полный адаптивный цикл диагностика→рекомендация→автовалидация→продвижение→откат
на детерминированных данных, без LLM-ключей (Mock/Deterministic советники)."""
import numpy as np
from ntlab.adaptive.advisor import DeterministicAdvisor, MockAdvisor
from ntlab.adaptive.schema import StrategyStats
from ntlab.adaptive.lifecycle import LifecycleManager, STAGES, classical_adaptation


def _stats(sharpe=-1.0, dd=-0.4):
    return StrategyStats(
        strategy_id="S11", hypothesis="listing-breakout momentum",
        current_params={"start_day": 20, "atr_n": 14},
        tunable_params={"start_day": ["int", 5, 60], "atr_n": ["int", 5, 30]},
        n_trades=42, equity_curve_tail=[1.0, 0.9, 0.85, 0.8],
        total_return=-0.2, max_drawdown=dd, sharpe=sharpe, volatility=0.5,
        regime_signals={"trend": -0.3})


def test_deterministic_advisor_pauses_on_degradation():
    rec = DeterministicAdvisor().advise(_stats(sharpe=-1.0, dd=-0.4))
    assert rec.decision == "pause"                        # деградация → наблюдение
    assert rec.market_regime in ("trend_down", "high_vol", "range", "unknown")


def test_deterministic_advisor_keeps_when_healthy():
    rec = DeterministicAdvisor().advise(_stats(sharpe=1.2, dd=-0.05))
    assert rec.decision == "keep"                          # норма → не дёргать


def test_mock_advisor_proposes_param():
    adv = MockAdvisor(propose_param="start_day", propose_value=30)
    rec = adv.advise(_stats())
    assert rec.decision == "test_new"
    assert rec.param_changes[0].name == "start_day"
    assert MockAdvisor.estimate_cost() > 0                 # учёт стоимости запроса


def test_lifecycle_full_cycle(tmp_path, monkeypatch):
    import ntlab.adaptive.lifecycle as lc
    # изолируем реестр и файл состояния во временную папку (не трогаем боевой дашборд)
    monkeypatch.setattr(lc, "REG", tmp_path / "versions.jsonl")
    monkeypatch.setattr(lc, "STATE", tmp_path / "state.json")
    m = lc.LifecycleManager()
    base = m.set_baseline({"start_day": 20}, source="test")
    assert base["stage"] == "champion"
    ch = m.propose_challenger({"start_day": 30}, source="mock",
                              validation={"valid_sharpe": 0.5, "test_sharpe": 0.4, "passed": True})
    assert ch["stage"] == "shadow"
    # продвижение по стадиям строго по одной (перепрыгивание запрещено)
    for stage in STAGES[1:]:
        m.promote(ch["version"], stage, result={"ok": True})
    assert m.champion["version"] == ch["version"]          # претендент стал чемпионом
    assert m.champion["params"]["start_day"] == 30


def test_lifecycle_no_stage_skip(tmp_path, monkeypatch):
    import ntlab.adaptive.lifecycle as lc
    monkeypatch.setattr(lc, "REG", tmp_path / "v.jsonl")
    monkeypatch.setattr(lc, "STATE", tmp_path / "s.json")
    m = lc.LifecycleManager()
    m.set_baseline({"start_day": 20})
    ch = m.propose_challenger({"start_day": 30}, "mock", {"passed": True})
    try:
        m.promote(ch["version"], "live_canary")            # прыжок shadow->live_canary запрещён
        assert False, "перепрыгивание стадии должно падать"
    except ValueError:
        pass


def test_lifecycle_rollback(tmp_path, monkeypatch):
    import ntlab.adaptive.lifecycle as lc
    monkeypatch.setattr(lc, "REG", tmp_path / "v.jsonl")
    monkeypatch.setattr(lc, "STATE", tmp_path / "s.json")
    m = lc.LifecycleManager()
    m.set_baseline({"start_day": 20})                      # champion v1
    ch = m.propose_challenger({"start_day": 30}, "mock", {"passed": True})
    for stage in STAGES[1:]:
        m.promote(ch["version"], stage, result={"ok": True})   # champion -> v2 (start_day 30)
    assert m.champion["params"]["start_day"] == 30
    restored = m.rollback()                                # откат к предыдущему РАЗЛИЧНОМУ champion
    assert restored is not None
    assert restored["params"]["start_day"] == 20          # вернулись к v1


def test_classical_adaptation_baseline():
    out = classical_adaptation(_stats(sharpe=-1.0, dd=-0.4), {"start_day": 20})
    assert isinstance(out, dict)                           # эвристический бейзлайн для сравнения с LLM
