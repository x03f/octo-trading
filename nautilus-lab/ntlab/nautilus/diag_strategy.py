"""Диагностическая TestStrategy — проверка order lifecycle через Nautilus (п.13).

НЕ торговая идея. После warmup_bars баров делает один market BUY, затем через hold_bars — SELL,
чтобы прогнать submitted→accepted→filled→position→portfolio на живых данных в sandbox. S11 при этом
остаётся в режиме ожидания реального сигнала (её lifecycle проверять не через принудительные сделки).
"""
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, TimeInForce


class DiagConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: str = "0.001"
    warmup_bars: int = 1
    hold_bars: int = 2


class DiagStrategy(Strategy):
    def __init__(self, config: DiagConfig):
        super().__init__(config)
        self.instrument = None
        self.n = 0
        self.opened = False
        self.closed = False
        self.events = []          # лог lifecycle для доказательства

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        self.n += 1
        if self.n == self.config.warmup_bars and not self.opened:
            self._mkt(OrderSide.BUY); self.opened = True
        elif self.opened and not self.closed and self.n >= self.config.warmup_bars + self.config.hold_bars:
            self._mkt(OrderSide.SELL); self.closed = True

    def _mkt(self, side):
        o = self.order_factory.market(instrument_id=self.config.instrument_id, order_side=side,
                                      quantity=self.instrument.make_qty(float(self.config.trade_size)),
                                      time_in_force=TimeInForce.GTC)
        self.submit_order(o)
        self.events.append(("submit", side.name, str(self.clock.utc_now())))

    def on_order_accepted(self, event):
        self.events.append(("accepted", str(event.client_order_id)))
    def on_order_filled(self, event):
        self.events.append(("filled", str(event.client_order_id), str(event.last_px), str(event.last_qty)))
    def on_order_rejected(self, event):
        self.events.append(("rejected", str(event.reason)))
