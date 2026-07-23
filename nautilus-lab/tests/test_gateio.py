"""Тесты Gate.io adapter: подпись, модели, execution (моки), idempotency, комиссии/precision."""
import sys, json
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.adapters.gateio.signing import sign_request, client_order_id
from ntlab.adapters.gateio.execution import GateioExecution, LiveDisabledError, RateLimiter
from ntlab.adapters.gateio.paper import PaperExecution


# ---------- подпись ----------
def test_signature_deterministic():
    h1 = sign_request("GET", "/api/v4/spot/accounts", "", "", "k", "s", timestamp="1700000000")
    h2 = sign_request("GET", "/api/v4/spot/accounts", "", "", "k", "s", timestamp="1700000000")
    assert h1["SIGN"] == h2["SIGN"]                      # детерминизм при фикс ts
    assert len(h1["SIGN"]) == 128                        # HMAC-SHA512 hex = 128 символов
    # разный секрет → разная подпись
    h3 = sign_request("GET", "/api/v4/spot/accounts", "", "", "k", "other", timestamp="1700000000")
    assert h3["SIGN"] != h1["SIGN"]


def test_signature_body_affects_sign():
    a = sign_request("POST", "/api/v4/spot/orders", "", '{"a":1}', "k", "s", timestamp="1")
    b = sign_request("POST", "/api/v4/spot/orders", "", '{"a":2}', "k", "s", timestamp="1")
    assert a["SIGN"] != b["SIGN"]                        # тело влияет на подпись


def test_client_order_id_prefix():
    cid = client_order_id("s11")
    assert cid.startswith("t-") and len(cid) <= 28       # требования Gate.io к полю text


# ---------- защита от боевых ордеров ----------
def test_live_disabled_blocks_orders():
    ex = GateioExecution("key", "secret", live_enabled=False)
    try:
        ex.place_order("BTC_USDT", "buy", 0.001, 65000)
        assert False, "должно кинуть LiveDisabledError"
    except LiveDisabledError:
        pass
    finally:
        ex.close()


def test_no_keys_raises():
    try:
        GateioExecution("", "")
        assert False
    except ValueError:
        pass


# ---------- разбор моделей биржи ----------
def test_parse_order_partial():
    o = GateioExecution._parse_order({"id": "1", "text": "t-x", "currency_pair": "BTC_USDT",
                                      "side": "buy", "type": "limit", "price": "65000",
                                      "amount": "1.0", "filled_total": "0.4", "left": "0.6",
                                      "status": "open", "fee": "0.1", "fee_currency": "BTC"})
    assert o["partial"] is True and o["filled"] == 0.4 and o["left"] == 0.6


def test_parse_order_rejected_and_filled():
    filled = GateioExecution._parse_order({"id": "2", "amount": "1.0", "filled_total": "1.0",
                                           "status": "closed", "finish_as": "filled"})
    assert filled["partial"] is False and filled["status"] == "closed"
    cancelled = GateioExecution._parse_order({"id": "3", "amount": "1.0", "filled_total": "0",
                                              "status": "cancelled", "finish_as": "cancelled"})
    assert cancelled["status"] == "cancelled" and cancelled["partial"] is False


def test_parse_fill_maker_taker():
    f = GateioExecution._parse_fill({"id": "9", "order_id": "2", "currency_pair": "BTC_USDT",
                                     "side": "sell", "price": "65000", "amount": "0.5",
                                     "fee": "0.05", "fee_currency": "USDT", "role": "maker"})
    assert f["role"] == "maker" and f["amount"] == 0.5


# ---------- rate limiter / backoff ----------
def test_rate_limiter_backoff():
    rl = RateLimiter(max_per_sec=100)
    rl.on_429(); assert rl._backoff > 0
    b = rl._backoff; rl.on_429(); assert rl._backoff > b   # экспоненциальный рост
    rl.on_ok(); rl.on_ok(); assert rl._backoff < b         # спад при успехе


# ---------- paper execution: комиссии, min, precision, partial ----------
class _FakeData:
    """Мок данных Gate.io для детерминированных тестов (без сети)."""
    def instrument(self, s):
        return {"price_precision": 1, "amount_precision": 6, "min_quote_amount": "3", "min_base_amount": "0.0001"}
    def order_book(self, s, limit=20):
        return {"asks": [[100.0, 0.3], [100.5, 1.0]], "bids": [[99.9, 0.3], [99.5, 1.0]]}
    def candles(self, s, tf, limit=1): return [{"close": 100.0}]


def test_paper_market_fill_and_fee():
    pe = PaperExecution(starting_balances={"USDT": 10000}, data=_FakeData(), taker_fee=0.0016)
    r = pe.submit_market("X_USDT", "buy", 0.5)
    assert r["status"] == "closed"
    assert len(r["fills"]) == 2                          # прошли 2 уровня стакана = проскальзывание
    # комиссия = notional * taker
    total_fee = sum(f["fee"] for f in r["fills"])
    assert abs(total_fee - (0.3*100.0 + 0.2*100.5) * 0.0016) < 1e-6


def test_paper_min_notional_rejected():
    pe = PaperExecution(starting_balances={"USDT": 10000}, data=_FakeData())
    ok, reason = pe.check_min("X_USDT", 0.001, 100.0)   # notional 0.1 < min 3
    assert not ok and "notional" in reason


def test_paper_partial_when_thin_book():
    pe = PaperExecution(starting_balances={"USDT": 10000}, data=_FakeData())
    r = pe.submit_market("X_USDT", "buy", 5.0)           # больше глубины стакана (0.3+1.0=1.3)
    assert r["status"] == "partial" and r["filled"] < 5.0


def test_paper_precision_rounding():
    pe = PaperExecution(data=_FakeData())
    assert pe._round_amount("X_USDT", 0.123456789) == 0.123457   # amount_precision=6
    assert pe._round_price("X_USDT", 100.14) == 100.1            # price_precision=1


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}"); n += 1
    print(f"GATE.IO ADAPTER: {n}/{n} тестов прошли")
