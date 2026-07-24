"""Сборка ФАКТИЧЕСКОГО Nautilus TradingNode(SANDBOX): Gate.io live data + sandbox simulated execution.

Данные, стратегия, ордера, позиции и portfolio проходят через Nautilus. Реальные ордера НЕВОЗМОЖНЫ:
среда SANDBOX, исполнение — SandboxExecutionClient (симуляция), приватные Gate.io endpoints не вызываются.

build_node(strategy_cfgs, gate_symbol, bar_spec, diag=False) → сконфигурированный TradingNode.
"""
from nautilus_trader.live.node import TradingNode
from nautilus_trader.config import TradingNodeConfig, LoggingConfig
from nautilus_trader.common import Environment
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.data import BarType
from nautilus_trader.model.objects import Money, Currency
from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from .gateio_factory import GateioDataClientConfig, GateioLiveDataClientFactory, PRESET_INSTRUMENT

VENUE = "BINANCE"     # sandbox venue (используем известный инструмент BTCUSDT для обхода precision)


def build_node(strategies, gate_symbol="BTC_USDT", bar_spec="1-MINUTE-LAST-EXTERNAL",
               start_usdt=100_000, poll_interval=5.0, log_level="INFO"):
    instrument = TestInstrumentProvider.btcusdt_binance()
    PRESET_INSTRUMENT["ref"] = instrument          # провайдер data-клиента отдаст этот инструмент
    bar_type = BarType.from_str(f"{instrument.id}-{bar_spec}")

    cfg = TradingNodeConfig(
        environment=Environment.SANDBOX,
        trader_id=TraderId("NTLAB-NAUT-001"),
        logging=LoggingConfig(log_level=log_level),
        data_clients={"GATEIO": GateioDataClientConfig(gate_symbol=gate_symbol, poll_interval=poll_interval)},
        exec_clients={VENUE: SandboxExecutionClientConfig(
            venue=VENUE, account_type="MARGIN", base_currency="USDT",
            starting_balances=[f"{start_usdt} USDT"], oms_type="NETTING",
            bar_execution=True)},          # sandbox исполняет по барам
        strategies=strategies,
    )
    node = TradingNode(config=cfg)
    node.add_data_client_factory("GATEIO", GateioLiveDataClientFactory)
    node.add_exec_client_factory(VENUE, SandboxLiveExecClientFactory)
    node.build()
    # инструмент должен быть в кэше до старта sandbox exec
    node.kernel.cache.add_instrument(instrument)
    return node, instrument, bar_type
