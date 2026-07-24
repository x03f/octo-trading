"""P10/integration: сквозной контур data → сигнал/ордер → PaperExecution → баланс/equity.
Проверяет РЕАЛЬНОЕ взаимодействие компонентов (стакан→проскальзывание→комиссии→баланс)."""
import numpy as np
from conftest import FakeMarket, synth_panel
from ntlab.adapters.gateio.paper import PaperExecution
from ntlab.strategies.s11_signal import s11_run, S11Params


def test_buy_updates_balances_with_fee():
    ex = PaperExecution(starting_balances={"USDT": 1000.0}, data=FakeMarket(mid=100.0))
    r = ex.submit_market("BTC_USDT", "buy", 1.0)
    assert r["status"] in ("closed", "partial")
    assert ex.balances["USDT"] < 1000.0                 # потрачено notional + комиссия
    assert ex.balances.get("BTC", 0) > 0                # база получена
    assert sum(f["fee"] for f in r["fills"]) > 0        # комиссия списана


def test_slippage_from_depth():
    # маленькая глубина верхнего уровня → часть исполняется глубже, avg хуже лучшей цены
    ex = PaperExecution(starting_balances={"USDT": 1e6}, data=FakeMarket(mid=100.0, depth=[(0.3,), (0.3,), (5.0,)]))
    r = ex.submit_market("BTC_USDT", "buy", 1.0)
    best_ask = 100.0 * 1.001
    assert r["avg_price"] > best_ask                    # проскальзывание по глубине стакана


def test_round_trip_loses_only_fees():
    ex = PaperExecution(starting_balances={"USDT": 10000.0}, data=FakeMarket(mid=100.0, depth=[(100.0,)]))
    ex.submit_market("BTC_USDT", "buy", 1.0)
    ex.submit_market("BTC_USDT", "sell", ex.balances["BTC"])
    # после круга USDT меньше старта (комиссии+спред), но в разумных пределах
    assert 9900.0 < ex.balances["USDT"] < 10000.0
    assert abs(ex.balances.get("BTC", 0)) < 1e-9


def test_min_notional_rejects():
    ex = PaperExecution(data=FakeMarket(mid=100.0, mins=(10.0, 0.0)))   # min_quote 10 USDT
    r = ex.submit_market("BTC_USDT", "buy", 0.01)                        # notional ~1 USDT
    assert r["status"] == "rejected"


def test_signal_drives_execution():
    # сигнал S11 на синтетике → если позиция>0, исполняем buy и видим экспозицию
    p = synth_panel(N=1, seed=3)
    pos, state, positions = s11_run(p.high[:, 0], p.low[:, 0], p.close[:, 0], params=S11Params())
    ex = PaperExecution(starting_balances={"USDT": 1000.0}, data=FakeMarket(mid=float(p.close[-1, 0])))
    if pos > 0:
        r = ex.submit_market("BTC_USDT", "buy", 0.5)
        assert r["status"] in ("closed", "partial")
        assert ex.balances.get("BTC", 0) > 0
    assert np.isfinite(ex.equity_usdt())                # equity считается в любом случае
