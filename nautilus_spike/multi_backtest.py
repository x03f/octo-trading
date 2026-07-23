"""Многоинструментный бэктест в Nautilus: та же логика, что тестит OctoBot (Donchian S4),
но по НАБОРУ монет в ОДНОМ процессе — демонстрация главного преимущества Nautilus над OctoBot
(много инструментов/стратегий в одном процессе вместо N поддоменов).

Каждой монете — свой инструмент (точность выводится из цены) + свой экземпляр стратегии.
Результат → JSON для дашборда.

Запуск: python multi_backtest.py <набор>   (majors|niche|aggr)
"""
import sys, json, time
from decimal import Decimal
from collections import deque
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Currency, Price, Quantity
from nautilus_trader.trading.strategy import Strategy

LAKE = "/opt/octobot/strategy-lab/data/ohlcv/1d"
SETS = {
    "majors": ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT"],
    "niche": ["LINK", "AVAX", "NEAR", "LTC", "UNI", "AAVE", "BCH", "HBAR", "XLM", "FIL"],
    "aggr": ["SHIB", "BONK", "ORDI", "FLOKI", "ETC", "GALA", "ETHFI", "AXS"],
}
ENTRY_N, EXIT_N = 20, 10


def price_precision(sample):
    """Точность цены по величине (трение (в) спайка: реальные монеты требуют ручного вывода)."""
    x = float(np.nanmedian(sample))
    if x >= 100: return 2
    if x >= 1: return 4
    if x >= 0.01: return 6
    return 8


def make_instrument(coin, closes):
    pp = price_precision(closes)
    sym = Symbol(f"{coin}USDT")
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=sym, venue=Venue("BINANCE")), raw_symbol=sym,
        base_currency=Currency.from_str(coin) if coin in ("BTC", "ETH") else _mk_ccy(coin),
        quote_currency=USDT, price_precision=pp, size_precision=4,
        price_increment=Price(10 ** -pp, precision=pp), size_increment=Quantity(1e-04, precision=4),
        lot_size=None, max_quantity=Quantity(1e9, precision=4), min_quantity=Quantity(1e-04, precision=4),
        max_notional=None, min_notional=Money(1, USDT),
        max_price=Price(10 ** 9, precision=pp), min_price=Price(10 ** -pp, precision=pp),
        margin_init=Decimal("0.10"), margin_maint=Decimal("0.05"),
        maker_fee=Decimal("0.0002"), taker_fee=Decimal("0.00046"),   # Gate VIP2 перп
        ts_event=0, ts_init=0)


_CCY = {}
def _mk_ccy(code):
    if code not in _CCY:
        from nautilus_trader.model.objects import Currency as C
        from nautilus_trader.model.enums import CurrencyType
        _CCY[code] = C(code=code, precision=8, iso4217=0, name=code, currency_type=CurrencyType.CRYPTO)
    return _CCY[code]


class DonchianConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: str = "1.0"


class Donchian(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.instrument = None
        self.highs = deque(maxlen=ENTRY_N); self.lows = deque(maxlen=ENTRY_N)
        self.ehi = deque(maxlen=EXIT_N); self.elo = deque(maxlen=EXIT_N)
        self.pos = 0

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar):
        c = float(bar.close)
        chi = max(self.highs) if len(self.highs) == ENTRY_N else None
        clo = min(self.lows) if len(self.lows) == ENTRY_N else None
        ehi = max(self.ehi) if len(self.ehi) == EXIT_N else None
        elo = min(self.elo) if len(self.elo) == EXIT_N else None
        if self.pos > 0 and elo is not None and c < elo:
            self.close_all_positions(self.config.instrument_id); self.pos = 0
        elif self.pos < 0 and ehi is not None and c > ehi:
            self.close_all_positions(self.config.instrument_id); self.pos = 0
        if self.pos == 0:
            if chi is not None and c > chi:
                self._mkt(OrderSide.BUY); self.pos = 1
            elif clo is not None and c < clo:
                self._mkt(OrderSide.SELL); self.pos = -1
        self.highs.append(float(bar.high)); self.lows.append(float(bar.low))
        self.ehi.append(float(bar.high)); self.elo.append(float(bar.low))

    def _mkt(self, side):
        self.submit_order(self.order_factory.market(
            instrument_id=self.config.instrument_id, order_side=side,
            quantity=self.instrument.make_qty(float(self.config.trade_size))))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "majors"
    coins = SETS[which]
    t0 = time.time()
    engine = BacktestEngine(BacktestEngineConfig(trader_id="MULTI-01", logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(venue=Venue("BINANCE"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                     base_currency=USDT, starting_balances=[Money(100_000, USDT)])
    used = []
    for coin in coins:
        try:
            tbl = pq.read_table(f"{LAKE}/{coin}USDT.parquet").to_pandas().sort_values("timestamp")
        except Exception:
            continue
        o, h, l, c, v = (tbl[k].to_numpy(dtype="float64", copy=True) for k in ("open", "high", "low", "close", "volume"))
        ts = tbl["timestamp"].to_numpy()
        instr = make_instrument(coin, c)
        pp, sp = instr.price_precision, instr.size_precision
        bt = BarType.from_str(f"{instr.id}-1-DAY-LAST-EXTERNAL")
        VMAX = 1e12   # потолок объёма: мем-монеты (SHIB/BONK) дают триллионы > QUANTITY_MAX Nautilus.
        bars = [Bar(bt, Price(round(oo, pp), pp), Price(round(hh, pp), pp), Price(round(ll, pp), pp),
                    Price(round(cc, pp), pp), Quantity(round(min(max(vv, 1e-4), VMAX), sp), sp), int(tt), int(tt))
                for tt, oo, hh, ll, cc, vv in zip(ts * 1_000_000, o, h, l, c, v)]
        engine.add_instrument(instr)
        engine.add_data(bars)
        engine.add_strategy(Donchian(DonchianConfig(instrument_id=instr.id, bar_type=bt)))
        used.append(coin)

    engine.run()
    acct = engine.portfolio.account(Venue("BINANCE"))
    bal = float(acct.balance_total(USDT).as_double())
    fills = len(engine.trader.generate_order_fills_report())
    out = {"set": which, "coins": used, "n_instruments": len(used),
           "start_balance": 100_000, "end_balance": round(bal, 2),
           "pnl_pct": round((bal / 100_000 - 1) * 100, 2), "fills": fills,
           "elapsed_s": round(time.time() - t0, 1), "engine": "nautilus", "strategy": "S4 Donchian"}
    print(json.dumps(out, ensure_ascii=False))
    path = f"/opt/octobot/strategy-lab/dashboard/nautilus_{which}.json"
    json.dump(out, open(path, "w"), ensure_ascii=False)
    engine.dispose()


if __name__ == "__main__":
    main()
