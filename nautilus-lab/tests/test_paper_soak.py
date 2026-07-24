"""P10/paper soak: длительная стабильность симулятора — много ордеров/тиков подряд,
инвариант: equity/балансы конечны, нет NaN, состояние не разъезжается, нет исключений."""
import numpy as np
from conftest import FakeMarket
from ntlab.adapters.gateio.paper import PaperExecution


def test_soak_many_roundtrips_stable():
    mkt = FakeMarket(mid=100.0, depth=[(50.0,)])
    ex = PaperExecution(starting_balances={"USDT": 100000.0}, data=mkt)
    rng = np.random.default_rng(0)
    for i in range(500):                                  # soak: 500 итераций
        mkt.set_mid(100.0 * (1 + 0.2 * np.sin(i / 20)))   # блуждающая цена
        if i % 2 == 0:
            ex.submit_market("BTC_USDT", "buy", 0.1)
        else:
            held = ex.balances.get("BTC", 0)
            if held > 0.05:
                ex.submit_market("BTC_USDT", "sell", min(held, 0.1))
        eq = ex.equity_usdt()
        assert np.isfinite(eq), f"equity NaN/inf на итерации {i}"
        assert np.isfinite(ex.balances["USDT"])
    assert len(ex.fills) > 100                             # реально торговали
    assert ex.equity_usdt() > 0                            # не обнулились


def test_soak_no_negative_usdt_on_min_check():
    mkt = FakeMarket(mid=100.0, depth=[(1000.0,)], mins=(5.0, 0.0))
    ex = PaperExecution(starting_balances={"USDT": 200.0}, data=mkt)
    rejects = 0
    for _ in range(200):
        r = ex.submit_market("BTC_USDT", "buy", 0.001)     # notional 0.1 < min 5 → reject
        if r["status"] == "rejected":
            rejects += 1
    assert rejects == 200                                  # все мелкие отклонены
    assert ex.balances["USDT"] == 200.0                    # баланс не тронут отклонёнными
