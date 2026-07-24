"""Каталог стратегий Nautilus Trading Lab — реальные статусы из честного трёхчастного теста.

Единый источник правды для дашборда и лабы. Статусы: research/paper/live/buried.
Числа — из results/three_set_test.json и new_strategies_test.json (не выдуманы).
"""
CATALOG = [
    {
        "id": "S11", "name": "Новичок", "class": "event / short-after-listing",
        "hypothesis": "Структурный принудительный продавец после листинга (себестоимость ≈0, обязан "
                      "распределять неделями) против затухающего внимания розницы. Единственная шорт-идея.",
        "status": "candidate", "test_sharpe": 0.84, "test_ret_pct": 4.3,
        "splits": {"train": 0.58, "valid": 2.22, "test": 0.84},
        "status_line": "прошла трёхчастный BACKTEST на event-вселенной шорта листингов "
                       "(TRAIN +0.58 / VALID +2.22 / TEST +0.84 Sharpe, ret +4.3%, DD -5.7%); "
                       "край НЕ подтверждён форвардом (0 живых сигналов) — НЕ экономически доказана",
        "universe": "вся вселенная, шорт листингов, 316 монет (ОТДЕЛЬНАЯ от top-tercile лидерборда)",
        "market": "perp short",
        "note": "Единственная, пережившая честный трёхчастный BACKTEST (на своей event-вселенной, НЕ "
                "лидерборд top-tercile) + проверку исполнимости (перп доступен). Кандидат №1 на форвард. "
                "Форвард НЕ пройден (runtime waiting_for_signal, 0 сделок). Реальные деньги — только после форвард-подтверждения.",
        "engine_module": "engine.strategies.newlisting:NewListing",
    },
    {
        "id": "S8", "name": "Сквиз", "class": "volatility breakout",
        "hypothesis": "Сжатие волатильности предшествует расширению; выход из узкого коридора чаще продолжается.",
        "status": "buried", "test_sharpe": -0.29,
        "splits": {"train": 0.24, "valid": -0.29, "test": 0.70},
        "universe": "верхний терциль ликвидности", "market": "spot/perp",
        "note": "Ранги переворачиваются VALID↔TEST = режимная зависимость, не край. На неликвиде -1.17.",
        "engine_module": "engine.strategies.squeeze:Squeeze",
    },
    {
        "id": "S4", "name": "Черепаха", "class": "trend / Donchian breakout",
        "hypothesis": "Пробой N-канала продолжается (Turtle). Классика trend-following.",
        "status": "buried", "test_sharpe": -0.50,
        "splits": {"train": 0.39, "valid": -0.50, "test": 0.56},
        "universe": "верхний терциль", "market": "spot/perp",
        "note": "Портирована в Nautilus (100% совпадение сигнала). Края на честном тесте нет.",
        "engine_module": "engine.strategies.turtle:Turtle",
    },
    {
        "id": "S5", "name": "Маятник", "class": "mean reversion",
        "hypothesis": "Возврат к среднему в режиме флэта.",
        "status": "buried", "test_sharpe": -1.67,
        "splits": {"train": 0.54, "valid": 0.43, "test": -1.67},
        "universe": "верхний терциль", "market": "spot",
        "note": "Победитель по VALID → на TEST -1.67/-37%. Учебный пример переобучения отбором.",
        "engine_module": "engine.strategies.gridmr:GridMR",
    },
    {
        "id": "S1", "name": "Флюгер", "class": "time-series momentum",
        "hypothesis": "Собственный тренд актива автокоррелирован на среднем горизонте.",
        "status": "buried", "test_sharpe": -0.31,
        "splits": {"train": 0.40, "valid": -0.31, "test": 0.49},
        "universe": "верхний терциль", "market": "spot/perp",
        "note": "Ранги переворачиваются. Funding-tilt разблокирован данными, но сам сигнал края не дал.",
        "engine_module": "engine.strategies.fluger:Fluger",
    },
    {
        "id": "S12", "name": "Абсорбция", "class": "order-flow / accumulation",
        "hypothesis": "Информированный покупатель поглощает предложение лимитами: объём растёт, диапазон нет, Amihud коллапсирует.",
        "status": "buried", "test_sharpe": -2.31,
        "splits": {"valid": 1.31, "test": -2.31},
        "universe": "нижний терциль", "market": "spot",
        "note": "Накопление срабатывает 4 раза за 2 года — выборка тонкая. VALID +1.31 → TEST -2.31.",
        "engine_module": "engine.strategies.absorption:Absorption",
    },
    {
        "id": "ADAPTIVE", "name": "Adaptive AI", "class": "regime-adaptive + LLM advisor",
        "hypothesis": "Детерминированный алгоритм + периодическая консультация LLM по смене режима; "
                      "рекомендации применяются ТОЛЬКО после автовалидации бэктестом.",
        "status": "research", "test_sharpe": None, "splits": {},
        "universe": "конфигурируемо", "market": "spot",
        "note": "Экспериментальная. LLM — консультант, решение принимает платформа по воспроизводимым тестам. "
                "Польза AI проверяется отдельно (5 вариантов сравнения); не выдаём за доказанное улучшение.",
        "engine_module": "ntlab.adaptive.strategy:AdaptiveAIStrategy",
    },
]

# похороненные семейства из поиска (для честной карты; не торгуемы)
BURIED_FAMILIES = [
    "S10 Эхо (lead-lag): гэп не закрывается, размер антипредиктивен",
    "S3 Спред (коинтеграция): мажоры не коинтегрированы",
    "S9 Ротация (cross-sec momentum): слаб в крипте",
    "LTF-отскок 15m: край = премия за неликвидность, после костов минус",
    "vol-risk-premium: нет вол-инструмента на OHLCV, знак отрицателен",
    "funding-carry (S2): фандинг = моментум не разворот, разрыв costs ~13×",
    "корреляц-режим: конфаунден с календарной эпохой",
    "объём-climax: разворот только в неликвиде (микроструктура)",
    "TSMOM согласие-ТФ: сигнал инвертирован (краткосрочный разворот)",
]


def by_status(status):
    return [s for s in CATALOG if s["status"] == status]
