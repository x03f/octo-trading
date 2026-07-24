"""Nautilus-backed исполнение portfolio: сигналы стратегии → НАСТОЯЩИЙ Nautilus order lifecycle
через BacktestEngine (SimulatedExchange + Nautilus Portfolio). Заменяет custom PaperExecution как
ОСНОВНОЙ paper-контур портфелей. Custom PaperExecution остаётся только тестовым oracle.

Каждый портфель проходит: Nautilus Strategy (NautilusWeightStrategy) → submit_order/order_factory →
SimulatedExchange (матчинг по барам) → Nautilus Portfolio (account/positions/fills). Реальные ордера
невозможны: BacktestEngine — симуляция.
"""
import sys, time
from collections import deque
from decimal import Decimal
sys.path.insert(0, "/opt/octobot/strategy-lab")
import numpy as np
import pyarrow.parquet as pq

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OmsType, AccountType, OrderSide, CurrencyType
from nautilus_trader.model.identifiers import Symbol, InstrumentId, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity, Currency
from nautilus_trader.trading.strategy import Strategy

LAKE = "/opt/octobot/strategy-lab/data/ohlcv_1d"
SIGNALS = {}      # signal_key -> np.array целевой позиции (знак) по барам


def _price_precision(sample):
    x = float(np.nanmedian(sample))
    if x >= 100: return 2
    if x >= 1: return 4
    if x >= 0.01: return 6
    return 8


_CCY = {}
def _mk_ccy(code):
    if code not in _CCY:
        _CCY[code] = Currency(code=code, precision=8, iso4217=0, name=code, currency_type=CurrencyType.CRYPTO)
    return _CCY[code]


def make_instrument(coin, closes):
    pp = _price_precision(closes)
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
        maker_fee=Decimal("0.00075"), taker_fee=Decimal("0.0016"),   # Gate spot taker/maker
        ts_event=0, ts_init=0)


class NWConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    signal_key: str
    alloc_usdt: float = 100.0        # капитал на этот инструмент (нотионал позиции ≤ alloc)


class NautilusWeightStrategy(Strategy):
    """Прогоняет предвычисленные сигналы стратегии через НАСТОЯЩИЙ Nautilus order lifecycle."""
    def __init__(self, config):
        super().__init__(config)
        self.instrument = None
        self.sig = None
        self.i = 0
        self.pos = 0

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.sig = SIGNALS.get(self.config.signal_key, np.array([]))
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar):
        if self.i >= len(self.sig):
            self.i += 1
            return
        target = int(np.sign(self.sig[self.i]))
        self.i += 1
        if target != self.pos:
            if self.pos != 0:
                self.close_all_positions(self.config.instrument_id)
            px = float(bar.close)
            if target != 0 and px > 0:
                qty = self.config.alloc_usdt / px          # нотионал = alloc (gross ≤ 1x)
                self._mkt(OrderSide.BUY if target > 0 else OrderSide.SELL, qty)
            self.pos = target

    def _mkt(self, side, qty):
        q = self.instrument.make_qty(max(float(qty), 1e-4))
        if float(q) <= 0:
            return
        self.submit_order(self.order_factory.market(
            instrument_id=self.config.instrument_id, order_side=side, quantity=q))


def run_nautilus_portfolio(strategy_key, instruments, start_usdt=1000.0, tf="1d", log_level="ERROR"):
    """Прогон портфеля через Nautilus BacktestEngine. instruments — ['BTC_USDT', ...] или ['BTC', ...].
    Возвращает Nautilus-вычисленные equity/positions/fills/pnl (не custom-симуляция)."""
    from engine import load_panel
    from engine.strategies import REGISTRY
    coins = [c.replace("_USDT", "").replace("USDT", "") for c in instruments]
    panel = load_panel(coins, tf)
    W = REGISTRY[strategy_key]().generate(panel)      # [T, N] веса стратегии

    engine = BacktestEngine(BacktestEngineConfig(trader_id="NTLAB-PF-01", logging=LoggingConfig(log_level=log_level)))
    engine.add_venue(venue=Venue("BINANCE"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                     base_currency=USDT, starting_balances=[Money(start_usdt, USDT)])
    used = []
    for j, coin in enumerate(panel.coins):
        o, h, l, c, v = (panel.open[:, j], panel.high[:, j], panel.low[:, j], panel.close[:, j], panel.volume[:, j])
        if not np.isfinite(c).any():
            continue
        instr = make_instrument(coin, c[np.isfinite(c)])
        pp, sp = instr.price_precision, instr.size_precision
        bt = BarType.from_str(f"{instr.id}-1-DAY-LAST-EXTERNAL")
        VMAX = 1e12
        bars = []
        for t in range(len(c)):
            if not (np.isfinite(o[t]) and np.isfinite(h[t]) and np.isfinite(l[t]) and np.isfinite(c[t])):
                continue
            tt = int(panel.ts[t]) * 1_000_000
            vv = v[t] if np.isfinite(v[t]) else 1e-4
            bars.append(Bar(bt, Price(round(o[t], pp), pp), Price(round(h[t], pp), pp),
                            Price(round(l[t], pp), pp), Price(round(c[t], pp), pp),
                            Quantity(round(min(max(vv, 1e-4), VMAX), sp), sp), tt, tt))
        if not bars:
            continue
        SIGNALS[coin] = np.sign(np.nan_to_num(W[:, j]))
        engine.add_instrument(instr)
        engine.add_data(bars)
        used.append((instr, bt, coin))
    alloc = start_usdt / max(1, len(used))     # равновесная доля капитала на инструмент (gross ≤ 1x)
    for instr, bt, coin in used:
        engine.add_strategy(NautilusWeightStrategy(NWConfig(
            instrument_id=instr.id, bar_type=bt, signal_key=coin, alloc_usdt=alloc)))

    engine.run()
    used = [c for _, _, c in used]
    acct = engine.portfolio.account(Venue("BINANCE"))
    equity = float(acct.balance_total(USDT).as_double()) if acct else start_usdt
    fills = len(engine.trader.generate_order_fills_report())
    positions_report = engine.trader.generate_positions_report()
    n_positions = len(positions_report)
    engine.dispose()
    return {
        "engine": "nautilus-backtest", "is_nautilus": True, "venue": "BINANCE(sandbox-sim)",
        "instruments": used, "n_instruments": len(used),
        "start_balance": round(start_usdt, 2), "equity": round(equity, 2),
        "pnl_pct": round((equity / start_usdt - 1) * 100, 3),
        "fills": fills, "positions": int(n_positions),
        "lifecycle": "Strategy → order_factory.market → SimulatedExchange → Nautilus Portfolio",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def run_isolated(strategy_key, instruments, start_usdt=1000.0, timeout=120):
    """Изолированный прогон в ОТДЕЛЬНОМ процессе (Nautilus Rust-логгер инициализируется раз на процесс,
    поэтому долгоживущий API обязан запускать каждый портфель в subprocess). Возвращает dict результата."""
    import subprocess, json, os
    env = dict(os.environ, PYTHONPATH="/opt/octobot/strategy-lab/nautilus-lab:/opt/octobot/strategy-lab")
    args = ["/opt/octobot/nautilus-venv/bin/python", "-m", "ntlab.nautilus.paper_engine",
            strategy_key, ",".join(instruments), str(start_usdt)]
    try:
        out = subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout,
                             cwd="/opt/octobot/strategy-lab/nautilus-lab")
        line = [l for l in out.stdout.splitlines() if l.strip().startswith("{")]
        return json.loads(line[-1]) if line else {"error": "нет результата", "stderr": out.stderr[-200:]}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)[:150]}


if __name__ == "__main__":
    import json
    strat = sys.argv[1] if len(sys.argv) > 1 else "S4"
    instr = sys.argv[2].split(",") if len(sys.argv) > 2 else ["BTC_USDT", "ETH_USDT"]
    start = float(sys.argv[3]) if len(sys.argv) > 3 else 1000.0
    r = run_nautilus_portfolio(strat, instr, start_usdt=start)
    print(json.dumps(r, ensure_ascii=False))
