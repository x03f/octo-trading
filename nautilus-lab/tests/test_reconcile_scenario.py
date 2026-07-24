"""P10/reconciliation-сценарий: расхождение обнаружено И сформировано действие на выравнивание.
Отличается от unit-проверок — моделирует состояние «после рестарта» с реальным конфликтом."""
from ntlab.adapters.gateio.reconcile import reconcile


class _Exch:
    """Подставная биржа: отдаёт балансы, открытые ордера, исполнения."""
    def __init__(self, balances, open_by_pair):
        self._bal = balances
        self._open = open_by_pair
    def balances(self): return self._bal
    def open_orders(self, pair=None): return self._open.get(pair, [])
    def my_trades(self, pair, limit=100): return []


def test_unknown_exchange_order_produces_action():
    # на бирже есть открытый ордер, о котором платформа не знает → adopt_or_cancel
    exch = _Exch({"USDT": {"available": 1000, "locked": 50}},
                 {"BTC_USDT": [{"id": "999", "side": "buy", "left": 0.1}]})
    rep = reconcile(exch, {"positions": {}, "known_order_ids": []}, ["BTC_USDT"])
    assert rep["exchange_reachable"] is True
    assert rep["in_sync"] is False
    acts = [a for a in rep["actions"] if a["type"] == "adopt_or_cancel"]
    assert acts and acts[0]["order_id"] == "999"           # действие на выравнивание сформировано


def test_position_divergence_flagged():
    # локально считаем, что держим позицию, а на бирже базового актива нет → resync_position
    exch = _Exch({"USDT": {"available": 1000, "locked": 0}, "BTC": {"available": 0, "locked": 0}}, {})
    rep = reconcile(exch, {"positions": {"BTC_USDT": 0.5}, "known_order_ids": []}, ["BTC_USDT"])
    assert rep["in_sync"] is False
    assert any(a["type"] == "resync_position" for a in rep["actions"])


def test_in_sync_when_consistent():
    exch = _Exch({"USDT": {"available": 1000, "locked": 0}}, {"BTC_USDT": []})
    rep = reconcile(exch, {"positions": {}, "known_order_ids": []}, ["BTC_USDT"])
    assert rep["in_sync"] is True and not rep["actions"]    # согласовано → действий нет


def test_exchange_unreachable_safe():
    class _Dead:
        def balances(self): raise RuntimeError("timeout")
    rep = reconcile(_Dead(), {"positions": {}, "known_order_ids": []}, ["BTC_USDT"])
    assert rep["exchange_reachable"] is False               # безопасно: помечено, без действий
