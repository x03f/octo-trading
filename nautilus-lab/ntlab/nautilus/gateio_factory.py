"""Config + Factory для Gate.io LiveDataClient (регистрация в TradingNode)."""
from nautilus_trader.live.config import LiveDataClientConfig
from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig

from .gateio_data_client import GateioLiveDataClient


class GateioDataClientConfig(LiveDataClientConfig, frozen=True):
    gate_symbol: str = "BTC_USDT"
    poll_interval: float = 5.0


class _StaticInstrumentProvider(InstrumentProvider):
    """Простой провайдер: заранее добавленный инструмент (обходим создание с precision)."""
    def __init__(self, instrument=None):
        super().__init__(config=InstrumentProviderConfig())
        self._preset = instrument
    async def load_all_async(self, filters=None):
        if self._preset is not None:
            self.add(self._preset)
    async def load_ids_async(self, instrument_ids, filters=None):
        if self._preset is not None:
            self.add(self._preset)


PRESET_INSTRUMENT = {"ref": None}   # выставляется в runner до build()


class GateioLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(loop, name, config, msgbus, cache, clock):
        provider = _StaticInstrumentProvider(PRESET_INSTRUMENT["ref"])
        return GateioLiveDataClient(
            loop=loop, client_id=ClientId(name), msgbus=msgbus, cache=cache, clock=clock,
            instrument_provider=provider, config=config,
            gate_symbol=getattr(config, "gate_symbol", "BTC_USDT"),
            poll_interval=getattr(config, "poll_interval", 5.0))
