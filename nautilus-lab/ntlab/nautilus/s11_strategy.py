"""S11 «Новичок» как ШТАТНАЯ Nautilus Strategy. ОДИН класс для BacktestNode и TradingNode(sandbox).

Сигнал — из общего ntlab.strategies.s11_signal (100% parity с движком). Ордера/позиции/PnL проходят
через Nautilus order API и portfolio. Никакой скрытой логики в runner/API — всё в этом классе.

Тезис S11: шорт распада внимания после листинга. На баровых данных: держим историю high/low/close,
считаем онлайн-сигнал S11 (0 или -1), на СМЕНЕ позиции выставляем market-ордер через Nautilus.
Выход/стоп/трейл/тайм-стоп — внутри s11_run. Sizing = risk_usdt / price.
"""
from collections import deque
import numpy as np

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, TimeInForce

import sys
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.strategies.s11_signal import s11_run, S11Params


class S11Config(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    risk_usdt: float = 200.0
    listing_hi_days: int = 3
    start_day: int = 3
    end_day: int = 20
    confirm_n: int = 3
    stop_hi_n: int = 5
    atr_n: int = 14
    atr_k: float = 2.5
    trail_n: int = 20
    target: float = -0.35
    time_stop: int = 30
    max_bars: int = 120


class S11Strategy(Strategy):
    """Штатная Nautilus-стратегия S11. Тот же класс в backtest и sandbox."""

    def __init__(self, config: S11Config):
        super().__init__(config)
        self.instrument = None
        self.highs = deque(maxlen=config.max_bars)
        self.lows = deque(maxlen=config.max_bars)
        self.closes = deque(maxlen=config.max_bars)
        self.params = S11Params(
            listing_hi_days=config.listing_hi_days, start_day=config.start_day,
            end_day=config.end_day, confirm_n=config.confirm_n, stop_hi_n=config.stop_hi_n,
            atr_n=config.atr_n, atr_k=config.atr_k, trail_n=config.trail_n,
            target=config.target, time_stop=config.time_stop)
        self.cur_pos = 0            # -1 шорт, 0 плоско (внутреннее целевое)
        self.held_qty = 0.0
        self.signals = 0
        self.orders_submitted = 0

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"нет инструмента {self.config.instrument_id}")
            self.stop(); return
        # подписка на бары (в backtest — из загруженных данных, в live — из data-клиента Gate.io).
        # Бэкфилл истории в live делает data-клиент (_request_bars), не стратегия.
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        self.highs.append(float(bar.high)); self.lows.append(float(bar.low))
        self.closes.append(float(bar.close))
        if len(self.closes) < max(self.params.atr_n + 2, self.params.start_day + 2):
            return
        H = np.array(self.highs); L = np.array(self.lows); C = np.array(self.closes)
        # first_idx=0: для sandbox/backtest на срезе истории листинг = начало окна
        target, info, _ = s11_run(H, L, C, first_idx=0, shortable_from_idx=0, params=self.params)
        self.signals += 1
        if target != self.cur_pos:
            self._transition(target, float(bar.close))

    def _transition(self, target, price):
        if target < self.cur_pos:                          # открыть шорт (sell)
            qty = self.instrument.make_qty(self.config.risk_usdt / price)
            self.held_qty = float(qty)
            self._market(OrderSide.SELL, qty)
        elif target > self.cur_pos:                        # закрыть шорт (buy back тот же объём)
            if self.held_qty > 0:
                qty = self.instrument.make_qty(self.held_qty)
                self._market(OrderSide.BUY, qty)
            self.held_qty = 0.0
        self.cur_pos = target

    def _market(self, side, qty):
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id, order_side=side, quantity=qty,
            time_in_force=TimeInForce.GTC)
        self.submit_order(order)
        self.orders_submitted += 1
        self.log.info(f"S11 {side} {qty} @ market")

    def on_stop(self):
        self.log.info(f"S11 стоп: сигналов={self.signals}, ордеров={self.orders_submitted}")
