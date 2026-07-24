"""P2: валидация ордеров (min amount/notional/precision), идемпотентность, emergency stop.
Без сети/ключей — методы тестируются на подставном execution."""
import pytest
from ntlab.adapters.gateio.execution import GateioExecution, OrderValidationError, LiveDisabledError

SPEC = {"pair": "BTC_USDT", "base": "BTC", "quote": "USDT", "amount_precision": 4,
        "price_precision": 2, "min_base_amount": 0.0001, "min_quote_amount": 3.0,
        "trade_status": "tradable", "maker_fee": 0.002}


def test_validate_rejects_tiny_amount():
    with pytest.raises(OrderValidationError):
        GateioExecution.validate_order(SPEC, "buy", 0.00001, 50000.0)   # < min_base_amount


def test_validate_rejects_below_min_notional():
    with pytest.raises(OrderValidationError):
        GateioExecution.validate_order(SPEC, "buy", 0.0001, 100.0)      # notional 0.01 < 3.0


def test_validate_rejects_untradable():
    spec = dict(SPEC, trade_status="untradable")
    with pytest.raises(OrderValidationError):
        GateioExecution.validate_order(spec, "buy", 1.0, 50000.0)


def test_validate_rounds_precision():
    amt, px = GateioExecution.validate_order(SPEC, "buy", 0.123456789, 50000.123456)
    assert amt == 0.1235                # округлено до amount_precision=4
    assert px == 50000.12               # округлено до price_precision=2


def test_validate_ok_market_skips_notional():
    amt, px = GateioExecution.validate_order(SPEC, "buy", 0.5, None)    # market: price None
    assert amt == 0.5 and px is None    # notional не проверяется без цены


class _FakeExec(GateioExecution):
    """Подставной execution без сети: переопределяет сетевые методы."""
    def __init__(self, live=True):
        self.live_enabled = live
        self._open = [{"id": "1", "symbol": "BTC_USDT", "client_id": "t-x", "side": "buy", "left": 0.1},
                      {"id": "2", "symbol": "BTC_USDT", "client_id": "t-y", "side": "sell", "left": 0.2}]
        self.cancelled = []

    def open_orders(self, currency_pair=None):
        return list(self._open)

    def cancel_order(self, order_id, currency_pair):
        self.cancelled.append(order_id)
        self._open = [o for o in self._open if o["id"] != order_id]
        return {"id": order_id, "status": "cancelled"}


def test_find_by_client_id():
    ex = _FakeExec()
    assert ex.find_by_client_id("BTC_USDT", "t-y")["id"] == "2"
    assert ex.find_by_client_id("BTC_USDT", "nope") is None


def test_cancel_all():
    ex = _FakeExec()
    out = ex.cancel_all("BTC_USDT")
    assert len(out) == 2 and set(ex.cancelled) == {"1", "2"}


def test_emergency_stop_disables_live():
    ex = _FakeExec(live=True)
    r = ex.emergency_stop("BTC_USDT")
    assert r["live_disabled"] is True
    assert ex.live_enabled is False            # боевой режим жёстко выключен
    assert len(r["cancelled"]) == 2
    # после стопа мутирующий вызов заблокирован
    with pytest.raises(LiveDisabledError):
        ex.cancel_all("BTC_USDT")


def test_no_keys_constructor_raises():
    with pytest.raises(ValueError):
        GateioExecution("", "", live_enabled=False)
