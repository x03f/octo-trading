"""SmokeTestEvaluator — ДИАГНОСТИЧЕСКИЙ тентакл. Не стратегия, торговать им нельзя.

ЗАЧЕМ
-----
Проверить пайплайн инстанса «TA → стратегия-реле → торговый режим → ордер» за минуты,
не дожидаясь, пока рынок соизволит дать сигнал. Настоящая стратегия может молчать сутками
(например, при штиле нет пробоя канала), и тогда невозможно отличить «работает, но сигнала нет»
от «сломано и молчит». Именно на этом мы потеряли время 23.07.2026.

Выдаёт детерминированную ноту по циклу, не глядя на цену:
  цикл 1 → -1 (покупка), цикл 2 → 0 (выход), цикл 3 → +1 (продажа), цикл 4 → 0, дальше повтор.
Соглашение OctoBot: -1 = покупка, +1 = продажа.

ПРИМЕНЕНИЕ
----------
Ставится на инстанс ВРЕМЕННО вместо боевого TA-эвалюатора, подтверждает создание ордеров,
после чего откатывается. В боевом профиле этот тентакл активным оставаться НЕ ДОЛЖЕН.
"""
import octobot_evaluators.evaluators as evaluators
import octobot_evaluators.util as evaluators_util


class SmokeTestEvaluator(evaluators.TAEvaluator):
    """Пилообразный сигнал -1 → 0 → +1 → 0. Только для проверки проходимости пайплайна."""

    CYCLE = [-1, 0, 1, 0]

    def __init__(self, tentacles_setup_config):
        super().__init__(tentacles_setup_config)
        self.counter = {}

    async def ohlcv_callback(self, exchange: str, exchange_id: str,
                             cryptocurrency: str, symbol: str, time_frame, candle, inc_in_construction_data):
        key = f"{symbol}{time_frame}"
        n = self.counter.get(key, 0)
        self.eval_note = self.CYCLE[n % len(self.CYCLE)]
        self.counter[key] = n + 1
        self.logger.info(f"SMOKE-DBG {symbol} {time_frame} цикл={n} note={self.eval_note}")
        await self.evaluation_completed(
            cryptocurrency, symbol, time_frame,
            eval_time=evaluators_util.get_eval_time(full_candle=candle, time_frame=time_frame),
        )

    @classmethod
    def get_is_symbol_wildcard(cls) -> bool:
        return False
