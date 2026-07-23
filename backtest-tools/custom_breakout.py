"""Кастомные «топ-бот» эвалюаторы, которых нет во встроенных OctoBot.

DonchianBreakoutEvaluator — классический канальный пробой (система Turtle Traders):
покупка при пробое максимума за N свечей, продажа при пробое минимума за N свечей.
eval_note: -1 = пробой вверх (buy), +1 = пробой вниз (sell), 0 = внутри канала.
"""
import numpy

import octobot_commons.constants as commons_constants
import octobot_commons.enums as enums
import octobot_evaluators.evaluators as evaluators
import octobot_evaluators.util as evaluators_util
import octobot_trading.api as trading_api


class DonchianBreakoutEvaluator(evaluators.TAEvaluator):
    def __init__(self, tentacles_setup_config):
        super().__init__(tentacles_setup_config)
        self.period = 20
        self.trend = {}          # состояние тренда по (symbol, time_frame)

    def init_user_inputs(self, inputs: dict) -> None:
        self.period = self.UI.user_input(
            "period", enums.UserInputTypes.INT, self.period, inputs, min_val=2,
            title="Donchian channel length (candles) for the breakout")

    async def ohlcv_callback(self, exchange: str, exchange_id: str, cryptocurrency: str,
                             symbol: str, time_frame, candle, inc_in_construction_data):
        symbol_data = self.get_exchange_symbol_data(exchange, exchange_id, symbol)
        high = trading_api.get_symbol_high_candles(symbol_data, time_frame,
                                                   include_in_construction=inc_in_construction_data)
        low = trading_api.get_symbol_low_candles(symbol_data, time_frame,
                                                 include_in_construction=inc_in_construction_data)
        close = trading_api.get_symbol_close_candles(symbol_data, time_frame,
                                                     include_in_construction=inc_in_construction_data)
        self.eval_note = commons_constants.START_PENDING_EVAL_NOTE
        if len(close) > self.period + 1:
            await self.evaluate(cryptocurrency, symbol, time_frame, high, low, close)
        await self.evaluation_completed(
            cryptocurrency, symbol, time_frame,
            eval_time=evaluators_util.get_eval_time(full_candle=candle, time_frame=time_frame))

    async def evaluate(self, cryptocurrency, symbol, time_frame, high, low, close):
        # канал по ПРЕДЫДУЩИМ period свечам (текущую исключаем)
        upper = float(numpy.max(high[-self.period - 1:-1]))
        lower = float(numpy.min(low[-self.period - 1:-1]))
        price = float(close[-1])
        key = f"{symbol}{time_frame}"
        prev = self.trend.get(key, 0)
        if price >= upper:
            trend = -1                 # пробой вверх -> входим/держим лонг
        elif price <= lower:
            trend = 1                  # пробой вниз -> выходим/шорт-сигнал
        else:
            trend = prev               # внутри канала -> держим прежнее состояние
        self.trend[key] = trend
        self.eval_note = trend         # УСТОЙЧИВЫЙ сигнал (Turtle: держим до обратного пробоя)

    @classmethod
    def get_is_symbol_wildcard(cls) -> bool:
        return False
