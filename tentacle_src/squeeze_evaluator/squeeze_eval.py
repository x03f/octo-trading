"""S8 «Сквиз» для OctoBot — прорыв после сжатия волатильности.

Порт стратегии из strategy-lab (engine/strategies/squeeze.py), лучшей по OOS на полном озере.
Edge-тезис: волатильность кластеризуется и возвращается к среднему; период аномального СЖАТИЯ
предшествует РАСШИРЕНИЮ, и выход из узкого коридора чаще продолжается, чем гаснет.

eval_note (соглашение OctoBot): -1 = сигнал на покупку, +1 = на продажу, 0 = вне позиции.
Сигнал УСТОЙЧИВЫЙ: держим направление до обратного пробоя короткого канала.
"""
import numpy

import octobot_commons.constants as commons_constants
import octobot_commons.enums as enums
import octobot_evaluators.evaluators as evaluators
import octobot_evaluators.util as evaluators_util
import octobot_trading.api as trading_api


class SqueezeBreakoutEvaluator(evaluators.TAEvaluator):
    def __init__(self, tentacles_setup_config):
        super().__init__(tentacles_setup_config)
        self.vol_n = 20        # окно волатильности
        self.hist_n = 100      # окно сравнения (относительно чего vol «низкая»)
        self.pct = 0.25        # нижний квартиль = сжатие
        self.chan_n = 20       # коридор пробоя
        self.exit_n = 10       # обратный канал для выхода
        self.state = {}        # состояние по (symbol, time_frame)

    def init_user_inputs(self, inputs: dict) -> None:
        self.vol_n = self.UI.user_input("vol_n", enums.UserInputTypes.INT, self.vol_n, inputs,
                                        min_val=5, title="Volatility window")
        self.hist_n = self.UI.user_input("hist_n", enums.UserInputTypes.INT, self.hist_n, inputs,
                                         min_val=20, title="History window for squeeze percentile")
        self.pct = self.UI.user_input("pct", enums.UserInputTypes.FLOAT, self.pct, inputs,
                                      min_val=0.05, max_val=0.9, title="Squeeze percentile")
        self.chan_n = self.UI.user_input("chan_n", enums.UserInputTypes.INT, self.chan_n, inputs,
                                         min_val=5, title="Breakout channel length")
        self.exit_n = self.UI.user_input("exit_n", enums.UserInputTypes.INT, self.exit_n, inputs,
                                         min_val=2, title="Exit channel length")

    async def ohlcv_callback(self, exchange: str, exchange_id: str, cryptocurrency: str,
                             symbol: str, time_frame, candle, inc_in_construction_data):
        sd = self.get_exchange_symbol_data(exchange, exchange_id, symbol)
        high = trading_api.get_symbol_high_candles(sd, time_frame, include_in_construction=inc_in_construction_data)
        low = trading_api.get_symbol_low_candles(sd, time_frame, include_in_construction=inc_in_construction_data)
        close = trading_api.get_symbol_close_candles(sd, time_frame, include_in_construction=inc_in_construction_data)
        self.eval_note = commons_constants.START_PENDING_EVAL_NOTE
        need = max(self.hist_n + self.vol_n, self.chan_n) + 2
        if len(close) > need:
            await self.evaluate(cryptocurrency, symbol, time_frame, high, low, close)
        await self.evaluation_completed(
            cryptocurrency, symbol, time_frame,
            eval_time=evaluators_util.get_eval_time(full_candle=candle, time_frame=time_frame))

    async def evaluate(self, cryptocurrency, symbol, time_frame, high, low, close):
        c = numpy.asarray(close, dtype=float)
        h = numpy.asarray(high, dtype=float)
        l = numpy.asarray(low, dtype=float)
        rets = numpy.diff(c) / c[:-1]

        # волатильность сейчас и её распределение за hist_n (всё по ЗАКРЫТЫМ данным до текущей свечи)
        vol_now = float(numpy.std(rets[-self.vol_n - 1:-1], ddof=1))
        hist = numpy.array([numpy.std(rets[-(self.vol_n + 1 + k):-(1 + k)], ddof=1)
                            for k in range(self.hist_n)])
        thr = float(numpy.quantile(hist[numpy.isfinite(hist)], self.pct))
        squeezed = vol_now <= thr

        upper = float(numpy.max(h[-self.chan_n - 1:-1]))
        lower = float(numpy.min(l[-self.chan_n - 1:-1]))
        ex_hi = float(numpy.max(h[-self.exit_n - 1:-1]))
        ex_lo = float(numpy.min(l[-self.exit_n - 1:-1]))
        price = float(c[-1])

        key = f"{symbol}{time_frame}"
        st = self.state.get(key, 0)
        # выход по обратному короткому каналу
        if st < 0 and price < ex_lo:       # были в лонге (note<0) → выход
            st = 0
        elif st > 0 and price > ex_hi:     # были в шорте (note>0) → выход
            st = 0
        # вход только после сжатия
        if st == 0 and squeezed:
            if price > upper:
                st = -1                     # пробой вверх → покупка
            elif price < lower:
                st = 1                      # пробой вниз → продажа
        self.state[key] = st
        if symbol in ("BTC/USDT", "BTC/USDT:USDT"):
            self.logger.info(
                f"SQZ-DBG vol={vol_now:.5f} thr={thr:.5f} сжато={squeezed} "
                f"price={price:.1f} upper={upper:.1f} lower={lower:.1f} note={st}")
        self.eval_note = st

    @classmethod
    def get_is_symbol_wildcard(cls) -> bool:
        return False
