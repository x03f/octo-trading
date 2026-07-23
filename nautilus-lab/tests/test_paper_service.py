"""Тесты непрерывного paper-сервиса S11: идемпотентность, восстановление без дублей, reconciliation."""
import sys, json, tempfile, os
from pathlib import Path
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
import ntlab.paper.service as svcmod
from ntlab.paper.service import S11PaperService


class _FakeData:
    """Мок Gate.io: одна свежая монета в окне входа S11, падающая (шорт сработает)."""
    def __init__(self):
        # 25 дневных баров: пик в первые 3 дня, затем слом вниз
        highs = [10, 12, 11] + [9, 8.5, 8, 7.5, 7, 6.8, 6.5] + [6.3]*14
        self.h = highs
        self.l = [x*0.95 for x in highs]
        self.c = [x*0.97 for x in highs]
    def instrument(self, s):
        return {"price_precision": 4, "amount_precision": 6, "min_quote_amount": "1", "min_base_amount": "0.0001"}
    def order_book(self, s, limit=20):
        px = self.c[-1]
        return {"asks": [[px*1.001, 1000]], "bids": [[px*0.999, 1000]]}
    def candles(self, s, tf, limit=1000, frm=None, to=None):
        import time
        base = int(time.time()*1000) - len(self.c)*86_400_000
        return [{"ts": base+i*86_400_000, "open": self.c[i], "high": self.h[i],
                 "low": self.l[i], "close": self.c[i], "volume": 1000} for i in range(len(self.c))]


def _fresh_paths(tmp):
    svcmod.STATE = Path(tmp)/"state.json"
    svcmod.STATUS = Path(tmp)/"status.json"
    svcmod.LOG = Path(tmp)/"paper.log"


def test_tick_opens_short_on_fresh_listing():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh_paths(tmp)
        svc = S11PaperService(watchlist=["NEW_USDT"], start_balance=10000, data=_FakeData())
        r = svc.tick(ts=1_800_000_000_000)
        # свежий листинг в падении → S11 должна открыть шорт
        assert any(a["side"] == "sell" for a in r["acted"]), f"ожидали шорт, получили {r['acted']}"
        assert svc.state["positions"]["NEW_USDT"] == -1.0


def test_idempotent_no_duplicate_after_restart():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh_paths(tmp)
        svc1 = S11PaperService(watchlist=["NEW_USDT"], start_balance=10000, data=_FakeData())
        svc1.tick(ts=1_800_000_000_000)
        fills1 = len(svc1.exec.fills)
        pos1 = dict(svc1.state["positions"])
        # РЕСТАРТ: новый сервис читает то же состояние
        svc2 = S11PaperService(watchlist=["NEW_USDT"], start_balance=10000, data=_FakeData())
        assert svc2.state["positions"] == pos1                 # позиция восстановлена
        r2 = svc2.tick(ts=1_800_000_000_000)                   # тот же день/переход
        assert r2["acted"] == [] or all(a is None for a in r2["acted"])  # НЕТ повторного ордера
        # состояние не задублировало позицию
        assert svc2.state["positions"]["NEW_USDT"] == -1.0


def test_state_persists_and_reconciles():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh_paths(tmp)
        svc = S11PaperService(watchlist=["NEW_USDT"], start_balance=10000, data=_FakeData())
        svc.tick(ts=1_800_000_000_000)
        # состояние на диске
        assert svcmod.STATE.exists()
        saved = json.load(open(svcmod.STATE))
        assert "positions" in saved and "balances" in saved
        # reconciliation: балансы симулятора == сохранённые
        svc2 = S11PaperService(watchlist=["NEW_USDT"], data=_FakeData())
        assert svc2.exec.balances == saved["balances"]


def test_status_written_for_api():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh_paths(tmp)
        svc = S11PaperService(watchlist=["NEW_USDT"], start_balance=10000, data=_FakeData())
        svc.tick(ts=1_800_000_000_000)
        assert svcmod.STATUS.exists()
        st = json.load(open(svcmod.STATUS))
        assert st["simulation"] is True and st["strategy"] == "S11"
        assert "equity" in st and "pnl_pct" in st and "max_drawdown_pct" in st


def test_smoke_multiple_ticks():
    with tempfile.TemporaryDirectory() as tmp:
        _fresh_paths(tmp)
        svc = S11PaperService(watchlist=["NEW_USDT"], start_balance=10000, data=_FakeData())
        for i in range(3):
            r = svc.tick(ts=1_800_000_000_000 + i*86_400_000)
            assert "equity" in r
        assert svc.state["ticks"] == 3


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}"); n += 1
    print(f"PAPER-СЕРВИС S11: {n}/{n} тестов прошли")
