"""Тесты reconciliation и синхронизации времени (mock-биржа, без сети/ключей)."""
import sys
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.adapters.gateio.reconcile import reconcile


class _MockExec:
    def __init__(self, balances=None, open_orders=None, reachable=True):
        self._bal = balances or {}
        self._oo = open_orders or []
        self._reachable = reachable
    def balances(self):
        if not self._reachable:
            raise RuntimeError("network down")
        return self._bal
    def open_orders(self, pair=None):
        return [o for o in self._oo if o["symbol"] == pair]


def test_reconcile_in_sync():
    ex = _MockExec(balances={"USDT": {"available": 10000, "locked": 0}}, open_orders=[])
    r = reconcile(ex, {"positions": {}, "known_order_ids": []}, ["BTC_USDT"])
    assert r["in_sync"] is True and r["exchange_reachable"] is True


def test_reconcile_unknown_order():
    ex = _MockExec(balances={"USDT": {"available": 9000, "locked": 100}},
                   open_orders=[{"id": "999", "symbol": "BTC_USDT", "side": "buy", "left": 0.5}])
    r = reconcile(ex, {"positions": {}, "known_order_ids": []}, ["BTC_USDT"])
    assert r["in_sync"] is False
    assert any(a["type"] == "adopt_or_cancel" and a["order_id"] == "999" for a in r["actions"])


def test_reconcile_known_order_ok():
    ex = _MockExec(balances={"USDT": {"available": 9000, "locked": 100}},
                   open_orders=[{"id": "999", "symbol": "BTC_USDT", "side": "buy", "left": 0.5}])
    r = reconcile(ex, {"positions": {}, "known_order_ids": ["999"]}, ["BTC_USDT"])
    assert r["in_sync"] is True                          # ордер известен → нет расхождения


def test_reconcile_exchange_unreachable():
    ex = _MockExec(reachable=False)
    r = reconcile(ex, {"positions": {}}, ["BTC_USDT"])
    assert r["exchange_reachable"] is False and len(r["discrepancies"]) > 0


def test_time_sync_offset():
    # проверка вычисления смещения времени (без сети — через фиктивный ответ)
    import ntlab.adapters.gateio.execution as ex
    e = ex.GateioExecution("k", "s")
    class _C:
        def get(self, url):
            class R:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"server_time": 1_700_000_005_000}
            return R()
        def close(self): pass
    e._c = _C()
    import time
    off = e.sync_time()
    # server_time - local ≈ 5000ms ± небольшой дрейф
    assert abs(off - (1_700_000_005_000 - int(time.time()*1000))) < 2000
    e.close()


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}"); n += 1
    print(f"RECONCILE + TIME-SYNC: {n}/{n} тестов прошли")
