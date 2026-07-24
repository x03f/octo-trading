"""Короткий прогон sandbox-узла с диагностической стратегией — доказательство lifecycle."""
import sys, asyncio, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0,"/opt/octobot/strategy-lab/nautilus-lab"); sys.path.insert(0,"/opt/octobot/strategy-lab")
from ntlab.nautilus.node import build_node
from ntlab.nautilus.diag_strategy import DiagStrategy, DiagConfig

RUN_SEC = int(sys.argv[1]) if len(sys.argv)>1 else 40

async def main():
    node, instrument, bar_type = build_node(strategies=[], gate_symbol="BTC_USDT",
                                            bar_spec="1-MINUTE-LAST-EXTERNAL", log_level="ERROR", poll_interval=4.0)
    diag = DiagStrategy(DiagConfig(instrument_id=instrument.id, bar_type=bar_type,
                                   trade_size="0.001", warmup_bars=1, hold_bars=1))
    node.trader.add_strategy(diag)
    task = asyncio.create_task(node.run_async())
    await asyncio.sleep(RUN_SEC)
    from nautilus_trader.model.identifiers import Venue
    print("=== ФАКТИЧЕСКИЙ Nautilus TradingNode (SANDBOX) — прогон", RUN_SEC, "с ===")
    print("environment:", node.kernel.environment)
    print("баров получено стратегией:", diag.n)
    print("lifecycle события:")
    for e in diag.events: print("   ", e)
    fills = node.trader.generate_order_fills_report()
    print("заполнений через Nautilus:", len(fills))
    acct = node.portfolio.account(Venue("BINANCE"))
    if acct: print("баланс USDT:", acct.balance_total(Currency.from_str("USDT")) if False else acct.balances_total())
    # data client метрики
    dc = node.kernel.data_engine
    print("closed positions:", len(node.cache.positions_closed()), "| open:", len(node.cache.positions_open()))
    await node.stop_async()
    task.cancel()
    node.dispose()

from nautilus_trader.model.objects import Currency
asyncio.run(main())
