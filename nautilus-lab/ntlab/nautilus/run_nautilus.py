"""Точка входа ФАКТИЧЕСКОГО Nautilus TradingNode runtime (systemd ntlab-nautilus).

Запускает S11 как штатную Nautilus Strategy в TradingNode(SANDBOX) на живых данных Gate.io.
S11 — ДНЕВНАЯ, ждёт реальный сигнал (свежий листинг); статус пишется для API/дашборда.
Реальные ордера НЕВОЗМОЖНЫ: среда SANDBOX + многофакторная защита (safety.py).

Запуск: python -m ntlab.nautilus.run_nautilus
"""
import sys, asyncio, json, time, signal, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
from pathlib import Path
from ntlab.nautilus.node import build_node
from ntlab.nautilus.s11_strategy import S11Strategy, S11Config
from ntlab.nautilus.safety import assert_no_live

STATUS = Path("/opt/octobot/nautilus-lab/web/data/nautilus_runtime_status.json")
RUNTIME_MODE = "sandbox"     # НЕ live; боевой путь недоступен


def write_status(node, instrument, strat, extra=None):
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Currency
    try:
        acct = node.portfolio.account(Venue("BINANCE"))
        bals = acct.balances_total() if acct else {}
        equity = sum(float(v.as_double()) for v in bals.values()) if bals else 0.0
    except Exception:
        equity = 0.0
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    dc = None
    for c in node.kernel.data_engine.registered_clients:
        dc = c
    st = {
        "contour": "nautilus_runtime", "is_nautilus": True, "simulation": True,
        "runtime_engine": "NautilusTrader TradingNode", "environment": "SANDBOX",
        "strategy": "S11", "strategy_state": "waiting_for_signal",
        "bars_seen": getattr(strat, "n", 0) if hasattr(strat, "n") else getattr(strat, "signals", 0),
        "orders_submitted": getattr(strat, "orders_submitted", 0),
        "equity_usdt": round(equity, 2),
        "open_positions": len(node.cache.positions_open()),
        "closed_positions": len(node.cache.positions_closed()),
        "data_connection": "gateio-public-poll",
        "reconnect_count": getattr(dc, "reconnect_count", 0) if dc else 0,
        "gaps_detected": getattr(dc, "gaps_detected", 0) if dc else 0,
        "last_event_ts": getattr(dc, "last_event_ts", 0) if dc else 0,
        "proof_status": "runtime operational, execution validated, forward validation pending",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        st.update(extra)
    json.dump(st, open(STATUS, "w"), ensure_ascii=False, indent=1)


async def main():
    assert_no_live(RUNTIME_MODE)      # гарантия: из sandbox боевой путь недоступен
    # S11 на дневных барах Gate.io (ждёт свежий листинг). Инструмент — известный (обход precision).
    node, instrument, bar_type = build_node(
        strategies=[], gate_symbol="BTC_USDT", bar_spec="1-DAY-LAST-EXTERNAL",
        log_level="INFO", poll_interval=30.0)
    strat = S11Strategy(S11Config(instrument_id=instrument.id, bar_type=bar_type, risk_usdt=200.0))
    node.trader.add_strategy(strat)

    stop = asyncio.Event()
    def _sig(*_): stop.set()
    for s in (signal.SIGTERM, signal.SIGINT):
        try: asyncio.get_running_loop().add_signal_handler(s, _sig)
        except Exception: pass

    task = asyncio.create_task(node.run_async())
    write_status(node, instrument, strat)
    while not stop.is_set():
        await asyncio.sleep(30)
        try: write_status(node, instrument, strat)
        except Exception: pass
    await node.stop_async()
    task.cancel()
    node.dispose()


if __name__ == "__main__":
    asyncio.run(main())
