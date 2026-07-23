"""RelayStrategyEvaluator — прозрачное реле TA-ноты на уровень СИМВОЛА.

ЗАЧЕМ ЭТОТ ТЕНТАКЛ ВООБЩЕ СУЩЕСТВУЕТ
-------------------------------------
Штатный `BlankStrategyEvaluator` публикует ноту по пути [крипта, символ, ТАЙМФРЕЙМ],
потому что передаёт `time_frame` в `strategy_completed()`. А `DailyTradingMode.set_final_eval()`
читает матрицу БЕЗ таймфрейма — по пути [крипта, символ]. Там лежит узел-контейнер
с `node_value = None`, проверка `check_valid_eval_note(None, ...)` возвращает False,
счётчик стратегий остаётся 0, `create_state()` не вызывается и ордера не создаются НИКОГДА.

Именно поэтому связка Blank + DailyTradingMode давала 0 сделок при живых эвалюаторах.
Штатные стратегии (SimpleStrategyEvaluator) этого не ловят, потому что агрегируют
несколько таймфреймов и публикуют результат сразу на уровне символа.

Наше реле делает ровно то же, что Blank, но публикует БЕЗ таймфрейма — туда,
где торговый режим ноту действительно ищет.

ПРО НЕСКОЛЬКО ТАЙМФРЕЙМОВ
-------------------------
Если у инстанса активен ровно один ТФ (наш случай — по одному ТФ на профиль),
реле полностью прозрачно. Если ТФ несколько, ноты разных ТФ перезаписывают друг друга
на уровне символа — «последний выигрывает». Это осознанное упрощение, а не недосмотр:
агрегация нескольких ТФ — задача полноценной стратегии, а не реле.
"""
import octobot_commons.constants as common_constants
import octobot_commons.enums as common_enums
import octobot_evaluators.evaluators as evaluators
import octobot_evaluators.enums as enums


class RelayStrategyEvaluator(evaluators.StrategyEvaluator):
    """Передаёт ноту TA-эвалюатора торговому режиму без изменений."""

    def init_user_inputs(self, inputs: dict) -> None:
        super().init_user_inputs(inputs)
        self.UI.user_input(
            common_constants.CONFIG_TENTACLES_REQUIRED_CANDLES_COUNT,
            common_enums.UserInputTypes.INT, 200, inputs, min_val=1,
            title="Сколько исторических свечей подгружать на старте.",
        )

    def get_full_cycle_evaluator_types(self) -> tuple:
        return enums.EvaluatorMatrixTypes.TA.value, enums.EvaluatorMatrixTypes.SCRIPTED.value

    async def matrix_callback(self,
                              matrix_id,
                              evaluator_name,
                              evaluator_type,
                              eval_note,
                              eval_note_type,
                              eval_note_description,
                              eval_note_metadata,
                              exchange_name,
                              cryptocurrency,
                              symbol,
                              time_frame):
        self.eval_note = eval_note
        # КЛЮЧЕВОЕ ОТЛИЧИЕ ОТ Blank: time_frame НЕ передаём.
        # Нота ложится по пути [крипта, символ] — именно там её ищет DailyTradingMode.
        await self.strategy_completed(cryptocurrency, symbol)
