"""Спайк NautilusTrader: сквозной бэктест из НАШЕГО озера, замер трения.

Отвечает на 2 из 3 вопросов спайка:
  (а) сколько времени/кода загнать кусок озера в формат Nautilus;
  (в) насколько больно с их инвариантами точности (используем TestInstrumentProvider — готовый инструмент).
Вопрос (б) — совпадение сделок с нашим движком — требует порта стратегии, это остаток недели.
"""
import time, sys
import pandas as pd
import pyarrow.parquet as pq

t0 = time.time()

# ── (а) загрузка нашего parquet → DataFrame в формате Nautilus ──────────────────
LAKE = "/opt/octobot/strategy-lab/data/ohlcv/1d/BTCUSDT.parquet"
tbl = pq.read_table(LAKE).to_pandas().sort_values("timestamp")
# writable-копия массивов (pyarrow отдаёт read-only буфер, Nautilus-wrangler требует writable)
df = pd.DataFrame(
    {c: tbl[c].to_numpy(dtype="float64", copy=True) for c in ("open", "high", "low", "close", "volume")},
    index=pd.to_datetime(tbl["timestamp"].to_numpy(), unit="ms"),
)
print(f"[а] озеро→DataFrame: {len(df)} баров BTC/USDT 1d, NaN={int(df.isna().sum().sum())}, "
      f"за {time.time()-t0:.2f}s")

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Currency
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.examples.strategies.ema_cross import EMACross, EMACrossConfig

# ── (в) инструмент с готовой точностью (обошли ручные инварианты) ───────────────
from nautilus_trader.model.data import Bar
from nautilus_trader.model.objects import Price, Quantity
instrument = TestInstrumentProvider.btcusdt_binance()
bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
# ⚠️ ТРЕНИЕ СПАЙКА: штатный BarDataWrangler падает на pandas 3.0 (read-only буфер под CoW),
# а Nautilus 1.230 сам тянет pandas 3.0 → его же загрузчик несовместим со своей зависимостью.
# Обходим ручной сборкой баров (документированный паттерн, но это лишний код и ловушки точности).
t1 = time.time()
pp, sp = instrument.price_precision, instrument.size_precision
bars = []
for ts, o, h, l, c, v in zip(df.index.view("int64"), df["open"], df["high"],
                             df["low"], df["close"], df["volume"]):
    tns = int(ts)  # datetime64[ns] → наносекунды (Nautilus работает в нс)
    bars.append(Bar(bar_type,
                    Price(round(o, pp), pp), Price(round(h, pp), pp),
                    Price(round(l, pp), pp), Price(round(c, pp), pp),
                    Quantity(round(v, sp), sp), tns, tns))
print(f"[а] DataFrame→Nautilus Bars (ручная сборка): {len(bars)} баров за {time.time()-t1:.2f}s "
      f"| точность price={pp} size={sp}")

# ── движок бэктеста ─────────────────────────────────────────────────────────────
engine = BacktestEngine(BacktestEngineConfig(
    trader_id="SPIKE-001", logging=LoggingConfig(log_level="ERROR")))
venue = Venue("BINANCE")
engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
                 base_currency=None, starting_balances=[Money(100_000, Currency.from_str("USDT"))])
engine.add_instrument(instrument)
engine.add_data(bars)

engine.add_strategy(EMACross(EMACrossConfig(
    instrument_id=instrument.id, bar_type=bar_type,
    fast_ema_period=10, slow_ema_period=20, trade_size="0.10")))

t2 = time.time()
engine.run()
print(f"[прогон] бэктест выполнен за {time.time()-t2:.2f}s")

acct = engine.portfolio.account(venue)
report = engine.trader.generate_account_report(venue)
fills = engine.trader.generate_order_fills_report()
print(f"[итог] сделок(заполнений): {len(fills)} | баланс USDT: "
      f"{acct.balance_total(Currency.from_str('USDT'))}")
print(f"[итог] полное время спайка: {time.time()-t0:.2f}s")
engine.dispose()
