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
    """Простой провайдер: заранее добавленные инструменты (обходим создание с precision).
    Поддерживает МНОЖЕСТВО инструментов (мульти-портфельный узел) + одиночный (S11)."""
    def __init__(self, instruments=None):
        super().__init__(config=InstrumentProviderConfig())
        self._presets = [i for i in (instruments or []) if i is not None]
    async def load_all_async(self, filters=None):
        for i in self._presets:
            self.add(i)
    async def load_ids_async(self, instrument_ids, filters=None):
        for i in self._presets:
            self.add(i)


PRESET_INSTRUMENT = {"ref": None, "refs": []}   # ref=single (S11), refs=list (портфели)


class GateioLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(loop, name, config, msgbus, cache, clock):
        insts = PRESET_INSTRUMENT.get("refs") or ([PRESET_INSTRUMENT["ref"]] if PRESET_INSTRUMENT.get("ref") else [])
        provider = _StaticInstrumentProvider(insts)
        return GateioLiveDataClient(
            loop=loop, client_id=ClientId(name), msgbus=msgbus, cache=cache, clock=clock,
            instrument_provider=provider, config=config,
            gate_symbol=getattr(config, "gate_symbol", "BTC_USDT"),
            poll_interval=getattr(config, "poll_interval", 5.0))
