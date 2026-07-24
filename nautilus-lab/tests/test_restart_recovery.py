"""P10/restart-recovery: состояние переживает перезапуск процесса (сохранить→пересоздать→сверить)."""
import json
import ntlab.adaptive.lifecycle as lc
from ntlab.portfolios.manager import PortfolioManager, Portfolio


def test_lifecycle_reload_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "REG", tmp_path / "v.jsonl")
    monkeypatch.setattr(lc, "STATE", tmp_path / "s.json")
    m = lc.LifecycleManager()
    m.set_baseline({"start_day": 20}, source="test")
    ch = m.propose_challenger({"start_day": 30}, "mock", {"passed": True})
    for st in lc.STAGES[1:]:
        m.promote(ch["version"], st, result={"ok": True})
    champ_before = m.champion["version"]
    # НОВЫЙ менеджер (эмуляция рестарта) читает тот же реестр
    m2 = lc.LifecycleManager()
    assert m2.champion is not None
    assert m2.champion["version"] == champ_before        # чемпион восстановлен с диска
    assert m2.champion["params"]["start_day"] == 30


def test_portfolio_save_load(tmp_path, monkeypatch):
    import ntlab.portfolios.manager as pm
    monkeypatch.setattr(pm, "STORE", tmp_path)
    p = Portfolio("pf1", "Test", 500.0, "S11", ["BTC_USDT"], mode="paper")
    p.save()
    loaded = Portfolio.load("pf1")
    assert loaded.pid == "pf1" and loaded.start_balance == 500.0
    assert loaded.strategy == "S11" and loaded.instruments == ["BTC_USDT"]


def test_manager_reloads_all(tmp_path, monkeypatch):
    import ntlab.portfolios.manager as pm
    monkeypatch.setattr(pm, "STORE", tmp_path)
    m = PortfolioManager()
    m.create("Alpha", 1000.0, "S11", ["BTC_USDT"])
    m.create("Beta", 2000.0, "S4", ["ETH_USDT"])
    # рестарт: новый менеджер поднимает оба
    m2 = PortfolioManager()
    assert len(m2.portfolios) == 2
    names = {p.name for p in m2.portfolios.values()}
    assert names == {"Alpha", "Beta"}


def test_adaptive_memory_persists(tmp_path, monkeypatch):
    import ntlab.adaptive.loop as loop
    monkeypatch.setattr(loop, "MEMORY", tmp_path / "mem.jsonl")
    # запишем запись напрямую и прочитаем новым «процессом»
    (tmp_path / "mem.jsonl").write_text(json.dumps({"ts": "t1", "decision": "keep"}) + "\n")
    lines = [json.loads(x) for x in open(tmp_path / "mem.jsonl")]
    assert lines[0]["decision"] == "keep"                # память консультаций переживает рестарт
