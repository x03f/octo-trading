"""Долгоживущий Nautilus TradingNode(Environment.SANDBOX) для мульти-портфельного paper на ЖИВОМ
Gate.io WebSocket (1-минутные бары). Заменяет one-shot BacktestEngine для основного paper-контура.

Каждый активный портфель = отдельная LivePortfolioStrategy на своём инструменте: инкрементальный
сигнал на живых барах → market-ордер через Nautilus order lifecycle → SandboxExecutionClient
(симулированные филлы) → Nautilus Portfolio. Per-portfolio equity — из леджера стратегии (обновляется
on_order_filled). Реальные ордера НЕВОЗМОЖНЫ: Environment.SANDBOX + safety.py.

Запуск: python -m ntlab.nautilus.portfolios_node   (systemd ntlab-portfolios)
"""
import sys, asyncio, json, time, signal, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
from pathlib import Path
from collections import deque
import numpy as np
import pyarrow.parquet as pq

from nautilus_trader.live.node import TradingNode
from nautilus_trader.config import TradingNodeConfig, LoggingConfig, StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.common import Environment
from nautilus_trader.model.identifiers import TraderId, InstrumentId, Venue
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory

from ntlab.nautilus.gateio_factory import GateioDataClientConfig, GateioLiveDataClientFactory, PRESET_INSTRUMENT
from ntlab.nautilus.paper_engine import make_instrument
from ntlab.nautilus.safety import assert_no_live

VENUE = "BINANCE"
STORE = Path("/opt/octobot/nautilus-lab/var/portfolios")
STATUS = Path("/opt/octobot/nautilus-lab/web/data/portfolios_live.json")
LAKE = "/opt/octobot/strategy-lab/data/ohlcv_1d"
RUNTIME_MODE = "sandbox"
_STRATS = []   # ссылки на активные стратегии для записи статуса


def _last_close(coin):
    try:
        tbl = pq.read_table(f"{LAKE}/{coin}USDT.parquet").to_pandas()
        return float(tbl["close"].dropna().iloc[-1])
    except Exception:
        return 100.0


# карта: поле стратегии портфеля -> инкрементальный live-сигнал (long/flat, спот-paper)
def _kind_for(strategy_key):
    return {"S4": "donchian", "S8": "breakout", "S1": "sma", "S9": "sma",
            "S5": "meanrev", "S3": "sma", "ADAPTIVE": "sma"}.get(strategy_key, "donchian")


def live_signal(kind, highs, lows, closes, pos, entry_n=20, exit_n=10, fast=10, slow=30):
    """Чистая функция инкрементального сигнала (long/flat, спот-paper). Детерминирована — тестируется
    без Nautilus. highs/lows/closes — списки; pos — текущая позиция (0/1)."""
    c = closes[-1] if closes else 0.0
    if kind in ("donchian", "breakout"):
        if len(highs) < entry_n:
            return pos
        chi = max(highs[-entry_n:])
        clo = min(lows[-exit_n:]) if len(lows) >= exit_n else None
        if pos == 0 and c >= chi:
            return 1
        if pos == 1 and clo is not None and c <= clo:
            return 0
        return pos
    if kind == "sma":
        if len(closes) < slow:
            return pos
        import numpy as _np
        arr = _np.array(closes)
        return 1 if arr[-fast:].mean() > arr[-slow:].mean() else 0
    if kind == "meanrev":
        if len(closes) < slow:
            return pos
        import numpy as _np
        arr = _np.array(closes); ma = arr[-slow:].mean(); sd = arr[-slow:].std()
        if sd <= 0:
            return pos
        z = (c - ma) / sd
        if pos == 0 and z < -2:
            return 1
        if pos == 1 and z > 0:
            return 0
        return pos
    return pos


class LivePortCfg(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    pid: str
    name: str
    kind: str = "donchian"
    alloc_usdt: float = 100.0
    entry_n: int = 20
    exit_n: int = 10
    fast: int = 10
    slow: int = 30


class LivePortfolioStrategy(Strategy):
    """Один портфель на живых 1m барах Gate.io → Nautilus order lifecycle → SANDBOX fill → Portfolio."""
    def __init__(self, config: LivePortCfg):
        super().__init__(config)
        self.instrument = None
        self.highs = deque(maxlen=max(config.entry_n, config.slow) + 5)
        self.lows = deque(maxlen=max(config.exit_n, config.slow) + 5)
        self.closes = deque(maxlen=max(config.entry_n, config.slow) + 5)
        self.pos = 0                       # 0 плоско, 1 в позиции (спот long/flat)
        # per-portfolio леджер (обновляется on_order_filled — из НАСТОЯЩИХ Nautilus-филлов)
        self.cash = float(config.alloc_usdt)
        self.qty = 0.0
        self.last_price = 0.0
        self.fills = 0
        self.bars_seen = 0
        _STRATS.append(self)

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"нет инструмента {self.config.instrument_id}"); self.stop(); return
        self._backfill()                    # тёплый старт: история 1m с Gate.io public REST
        self.subscribe_bars(self.config.bar_type)

    def _backfill(self, n=80):
        """REST-бэкфилл последних n закрытых 1m свечей → прайминг сигнала (как реальный live-старт)."""
        try:
            import httpx
            sym = str(self.config.instrument_id).split(".")[0]
            gsym = sym[:-4] + "_USDT" if sym.endswith("USDT") else sym
            r = httpx.get("https://api.gateio.ws/api/v4/spot/candlesticks",
                          params={"currency_pair": gsym, "interval": "1m", "limit": n}, timeout=15)
            rows = sorted(r.json(), key=lambda k: int(float(k[0])))[:-1]   # без незакрытой
            for k in rows:
                self.highs.append(float(k[3])); self.lows.append(float(k[4])); self.closes.append(float(k[2]))
            self.last_price = float(rows[-1][2]) if rows else 0.0
            self.log.info(f"backfill {len(rows)} 1m баров для {gsym}")
        except Exception as e:
            self.log.warning(f"backfill не удался: {str(e)[:60]}")

    def on_bar(self, bar: Bar):
        c = float(bar.close); self.last_price = c
        self.bars_seen += 1
        self.highs.append(float(bar.high)); self.lows.append(float(bar.low)); self.closes.append(c)
        sig = self._signal(c)
        if sig != self.pos:
            self._transition(sig, c)

    def _signal(self, c):
        return live_signal(self.config.kind, list(self.highs), list(self.lows), list(self.closes),
                           self.pos, self.config.entry_n, self.config.exit_n, self.config.fast, self.config.slow)

    def _transition(self, target, price):
        if target == 1 and self.pos == 0:
            qty = self.instrument.make_qty(max(self.config.alloc_usdt / price, 1e-4))
            self._market(OrderSide.BUY, qty)
        elif target == 0 and self.pos == 1 and self.qty > 0:
            qty = self.instrument.make_qty(self.qty)
            self._market(OrderSide.SELL, qty)
        self.pos = target

    def _market(self, side, qty):
        self.submit_order(self.order_factory.market(
            instrument_id=self.config.instrument_id, order_side=side, quantity=qty,
            time_in_force=TimeInForce.GTC))

    def on_order_filled(self, event):
        # per-portfolio леджер из НАСТОЯЩИХ Nautilus-филлов
        try:
            px = float(event.last_px); q = float(event.last_qty)
            fee = float(event.commission.as_double()) if event.commission else 0.0
        except Exception:
            return
        if event.order_side == OrderSide.BUY:
            self.cash -= px * q + fee; self.qty += q
        else:
            self.cash += px * q - fee; self.qty -= q
        self.fills += 1

    def equity(self):
        return self.cash + self.qty * self.last_price

    def snapshot(self):
        eq = self.equity()
        return {"pid": self.config.pid, "name": self.config.name,
                "strategy": self.config.kind, "instrument": str(self.config.instrument_id).split(".")[0],
                "alloc_usdt": self.config.alloc_usdt, "equity": round(eq, 2),
                "pnl_pct": round((eq / self.config.alloc_usdt - 1) * 100, 3) if self.config.alloc_usdt else 0,
                "position_qty": round(self.qty, 6), "in_position": self.pos == 1,
                "fills": self.fills, "bars_seen": self.bars_seen, "last_price": round(self.last_price, 4)}


def _active_portfolios():
    out = []
    for f in sorted(STORE.glob("*.json")):
        try:
            d = json.load(open(f))
            if not d.get("paused"):
                out.append(d)
        except Exception:
            pass
    return out


def build_portfolios_node(portfolios, bar_spec="1-MINUTE-LAST-EXTERNAL", poll_interval=5.0, log_level="ERROR"):
    # один инструмент на портфель (первый); дедуп инструментов
    instruments, bar_types, cfgs = {}, {}, []
    total_alloc = 0.0
    for p in portfolios:
        instr_sym = (p.get("instruments") or ["BTC_USDT"])[0]
        coin = instr_sym.replace("_USDT", "").replace("USDT", "")
        if coin not in instruments:
            instr = make_instrument(coin, np.array([_last_close(coin)]))
            instruments[coin] = instr
            bar_types[coin] = BarType.from_str(f"{instr.id}-{bar_spec}")
        instr = instruments[coin]; bt = bar_types[coin]
        alloc = float(p.get("start_balance", 100))
        total_alloc += alloc
        cfgs.append(LivePortCfg(instrument_id=instr.id, bar_type=bt, pid=p["pid"],
                                name=p.get("name", p["pid"]), kind=_kind_for(p.get("strategy", "S4")),
                                alloc_usdt=alloc, fast=int(p.get("fast", 10)), slow=int(p.get("slow", 30))))
    PRESET_INSTRUMENT["refs"] = list(instruments.values())
    PRESET_INSTRUMENT["ref"] = None

    cfg = TradingNodeConfig(
        environment=Environment.SANDBOX,
        trader_id=TraderId("NTLAB-PORTF-01"),
        logging=LoggingConfig(log_level=log_level),
        data_clients={"GATEIO": GateioDataClientConfig(gate_symbol="BTC_USDT", poll_interval=poll_interval)},
        exec_clients={VENUE: SandboxExecutionClientConfig(
            venue=VENUE, account_type="MARGIN", base_currency="USDT",
            starting_balances=[f"{max(total_alloc, 1):.0f} USDT"], oms_type="NETTING", bar_execution=True)},
        strategies=[])
    node = TradingNode(config=cfg)
    node.add_data_client_factory("GATEIO", GateioLiveDataClientFactory)
    node.add_exec_client_factory(VENUE, SandboxLiveExecClientFactory)
    node.build()
    for instr in instruments.values():
        node.kernel.cache.add_instrument(instr)
    for c in cfgs:
        node.trader.add_strategy(LivePortfolioStrategy(c))
    return node, list(instruments.values()), cfgs


def write_status(node, extra=None):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    ports = [s.snapshot() for s in _STRATS]
    total_eq = sum(p["equity"] for p in ports)
    total_alloc = sum(p["alloc_usdt"] for p in ports) or 1
    dc = None
    for c in node.kernel.data_engine.registered_clients:
        dc = c
    st = {
        "contour": "nautilus_portfolios_live", "is_nautilus": True, "simulation": True,
        "runtime_engine": "NautilusTrader TradingNode", "environment": "SANDBOX",
        "transport": "gate.io websocket (1m)", "n_portfolios": len(ports),
        "total_equity": round(total_eq, 2), "total_alloc": round(total_alloc, 2),
        "pnl_pct": round((total_eq / total_alloc - 1) * 100, 3),
        "portfolios": ports,
        "reconnect_count": getattr(dc, "reconnect_count", 0) if dc else 0,
        "gaps_detected": getattr(dc, "gaps_detected", 0) if dc else 0,
        "last_event_ts": getattr(dc, "last_event_ts", 0) if dc else 0,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        st.update(extra)
    json.dump(st, open(STATUS, "w"), ensure_ascii=False, indent=1)


async def main():
    assert_no_live(RUNTIME_MODE)
    ports = _active_portfolios()
    if not ports:
        # плейсхолдер-статус: нет активных портфелей
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"contour": "nautilus_portfolios_live", "is_nautilus": True, "n_portfolios": 0,
                   "note": "нет активных портфелей — создай через дашборд/API",
                   "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                  open(STATUS, "w"), ensure_ascii=False, indent=1)
        while True:
            await asyncio.sleep(30)
            ports = _active_portfolios()
            if ports:
                break
    node, instruments, cfgs = build_portfolios_node(ports)
    stop = asyncio.Event()
    for s in (signal.SIGTERM, signal.SIGINT):
        try: asyncio.get_running_loop().add_signal_handler(s, stop.set)
        except Exception: pass
    task = asyncio.create_task(node.run_async())
    write_status(node)
    while not stop.is_set():
        await asyncio.sleep(30)
        try: write_status(node)
        except Exception: pass
    await node.stop_async(); task.cancel(); node.dispose()


if __name__ == "__main__":
    asyncio.run(main())
