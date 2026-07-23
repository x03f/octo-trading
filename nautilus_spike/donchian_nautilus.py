"""Порт S4 «Черепаха» (Donchian breakout) в Nautilus + сверка сделок с нашим движком.

Спайк вопрос (б): совпадают ли точки входа/выхода Nautilus с engine/strategies/turtle.py
на тех же барах BTC 1d. Логика идентична: вход при пробое N-максимума/минимума (без сегодня),
выход по обратному короткому каналу.
"""
import time
from collections import deque
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig, StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money, Currency, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy

ENTRY_N, EXIT_N = 20, 10


class DonchianConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: str = "0.10"
    entry_n: int = ENTRY_N
    exit_n: int = EXIT_N


class Donchian(Strategy):
    """Donchian breakout, long+short. Канал по ЗАКРЫТЫМ барам (без текущего) — как наш движок."""

    def __init__(self, config):
        super().__init__(config)
        self.instrument = None
        self.highs = deque(maxlen=config.entry_n)
        self.lows = deque(maxlen=config.entry_n)
        self.ex_highs = deque(maxlen=config.exit_n)
        self.ex_lows = deque(maxlen=config.exit_n)
        self.pos = 0
        self.fills = []   # (ts, side, price) — для сверки

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        c = float(bar.close)
        # каналы по ПРОШЛЫМ барам (текущий ещё не добавлен) — совпадает с shift(...,1) в движке
        chan_hi = max(self.highs) if len(self.highs) == self.config.entry_n else None
        chan_lo = min(self.lows) if len(self.lows) == self.config.entry_n else None
        ex_hi = max(self.ex_highs) if len(self.ex_highs) == self.config.exit_n else None
        ex_lo = min(self.ex_lows) if len(self.ex_lows) == self.config.exit_n else None

        # выходы по обратному короткому каналу
        if self.pos > 0 and ex_lo is not None and c < ex_lo:
            self._flat(bar)
        elif self.pos < 0 and ex_hi is not None and c > ex_hi:
            self._flat(bar)
        # входы по пробою длинного канала
        if self.pos == 0:
            if chan_hi is not None and c > chan_hi:
                self._enter(bar, OrderSide.BUY, +1)
            elif chan_lo is not None and c < chan_lo:
                self._enter(bar, OrderSide.SELL, -1)

        # обновляем окна ПОСЛЕ решения (чтобы текущий бар не влиял на свой сигнал)
        self.highs.append(float(bar.high)); self.lows.append(float(bar.low))
        self.ex_highs.append(float(bar.high)); self.ex_lows.append(float(bar.low))

    def _enter(self, bar, side, newpos):
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id, order_side=side,
            quantity=self.instrument.make_qty(float(self.config.trade_size)))
        self.submit_order(order)
        self.pos = newpos
        self.fills.append((bar.ts_event, "BUY" if side == OrderSide.BUY else "SELL", float(bar.close)))

    def _flat(self, bar):
        self.close_all_positions(self.config.instrument_id)
        self.fills.append((bar.ts_event, "FLAT", float(bar.close)))
        self.pos = 0


def our_engine_signals(closes, highs, lows):
    """Точки флипа нашей логики Donchian (без сайзинга/ADX) — для сверки направлений и таймингов."""
    T = len(closes)
    def rmax(a, w, t): return np.max(a[t - w:t]) if t >= w else None
    def rmin(a, w, t): return np.min(a[t - w:t]) if t >= w else None
    pos = 0; sig = []
    for t in range(T):
        c = closes[t]
        chan_hi = rmax(highs, ENTRY_N, t); chan_lo = rmin(lows, ENTRY_N, t)
        ex_hi = rmax(highs, EXIT_N, t); ex_lo = rmin(lows, EXIT_N, t)
        if pos > 0 and ex_lo is not None and c < ex_lo:
            sig.append((t, "FLAT")); pos = 0
        elif pos < 0 and ex_hi is not None and c > ex_hi:
            sig.append((t, "FLAT")); pos = 0
        if pos == 0:
            if chan_hi is not None and c > chan_hi:
                sig.append((t, "BUY")); pos = 1
            elif chan_lo is not None and c < chan_lo:
                sig.append((t, "SELL")); pos = -1
    return sig


def main():
    t0 = time.time()
    tbl = pq.read_table("/opt/octobot/strategy-lab/data/ohlcv/1d/BTCUSDT.parquet").to_pandas().sort_values("timestamp")
    o, h, l, c, v = (tbl[k].to_numpy(dtype="float64", copy=True) for k in ("open", "high", "low", "close", "volume"))
    ts = tbl["timestamp"].to_numpy()
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v},
                      index=pd.to_datetime(ts, unit="ms"))

    instrument = TestInstrumentProvider.btcusdt_binance()
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    pp, sp = instrument.price_precision, instrument.size_precision
    bars = [Bar(bar_type, Price(round(oo, pp), pp), Price(round(hh, pp), pp),
                Price(round(ll, pp), pp), Price(round(cc, pp), pp),
                Quantity(round(vv, sp), sp), int(tt), int(tt))
            for tt, oo, hh, ll, cc, vv in zip(df.index.view("int64"), o, h, l, c, v)]

    engine = BacktestEngine(BacktestEngineConfig(trader_id="DONCH-01", logging=LoggingConfig(log_level="ERROR")))
    venue = Venue("BINANCE")
    engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                     base_currency=None, starting_balances=[Money(1_000_000, Currency.from_str("USDT"))])
    engine.add_instrument(instrument)
    engine.add_data(bars)
    strat = Donchian(DonchianConfig(instrument_id=instrument.id, bar_type=bar_type))
    engine.add_strategy(strat)
    engine.run()

    naut = strat.fills
    ours = our_engine_signals(c, h, l)
    print(f"=== СВЕРКА Donchian: Nautilus vs наш движок (BTC 1d, {len(bars)} баров) ===")
    print(f"Nautilus сигналов: {len(naut)} | наш движок: {len(ours)} | за {time.time()-t0:.1f}s")
    # сверяем направления по индексу бара
    idx = {int(pd.Timestamp(pd.to_datetime(t, utc=True)).value): i for i, t in enumerate(df.index.view('int64'))}
    naut_by_bar = [(idx.get(int(pd.Timestamp(f[0]).value), -1), f[1]) for f in naut]
    print("\nпервые 12 сигналов:")
    print(f"{'бар':>5} {'Nautilus':>10} {'наш':>10}")
    ours_d = dict((t, s) for t, s in ours)
    naut_d = dict((b, s) for b, s in naut_by_bar if b >= 0)
    allbars = sorted(set(ours_d) | set(naut_d))
    match = sum(1 for b in allbars if ours_d.get(b) == naut_d.get(b))
    for b in allbars[:12]:
        print(f"{b:>5} {naut_d.get(b,'—'):>10} {ours_d.get(b,'—'):>10}")
    print(f"\nсовпадение сигналов по барам: {match}/{len(allbars)} "
          f"({100*match/max(len(allbars),1):.0f}%)")
    engine.dispose()


if __name__ == "__main__":
    main()
