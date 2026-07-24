"""Тесты мульти-портфелей: создание, восстановление, live-presets guard, research->paper."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0,"/opt/octobot/strategy-lab/nautilus-lab")
import ntlab.portfolios.manager as pm
from ntlab.portfolios.manager import PortfolioManager, Portfolio, LIVE_PRESETS

def _fresh(tmp):
    pm.STORE=Path(tmp)/"pf"; pm.STORE.mkdir(exist_ok=True); pm.STATUS=Path(tmp)/"status.json"

def test_create_multiple_portfolios():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m=PortfolioManager()
        m.create("A",10000,"S11",["BTC_USDT"]); m.create("B",5000,"S8",["ETH_USDT"])
        assert len(m.portfolios)==2

def test_restore_after_restart():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m=PortfolioManager(); p=m.create("A",7777,"S11",["BTC_USDT"])
        m2=PortfolioManager()
        assert p.pid in m2.portfolios
        assert m2.portfolios[p.pid].start_balance==7777

def test_paper_is_simulation():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m=PortfolioManager(); p=m.create("A",10000,"S11",["BTC_USDT"])
        assert p.status()["simulation"] is True
        assert p.mode=="paper"

def test_live_presets_not_ready_without_keys():
    assert "spot_basic_100usdt" in LIVE_PRESETS
    assert "adaptive_ai_10_100usdt" in LIVE_PRESETS
    for preset in LIVE_PRESETS.values():
        assert preset["ready"] is False        # не готов до ключей
        assert "guard" in preset
    assert LIVE_PRESETS["spot_basic_100usdt"]["start_balance"]==100

def test_delete_portfolio():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh(tmp)
        m=PortfolioManager(); p=m.create("A",10000,"S11",["BTC_USDT"])
        m.delete(p.pid)
        assert len(m.portfolios)==0

if __name__=="__main__":
    n=0
    for name,fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print(f"  ✓ {name}"); n+=1
    print(f"PORTFOLIOS: {n}/{n}")
