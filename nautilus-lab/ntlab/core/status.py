"""Статусы доказанности контуров и стратегий (честная карта «что доказано, что нет»).

Каждый контур/стратегия имеет НАБОР независимых флагов — нельзя выдавать один за другой.
До реального forward-сигнала и сделки S11 = "runtime operational, execution validated,
forward validation pending".
"""

# уровни доказанности (по возрастанию)
PROOF_LEVELS = [
    "BACKTEST_VALIDATED",          # прошла честный трёхчастный тест на исторических данных
    "LOCAL_SANDBOX_OPERATIONAL",   # работает в локальном Nautilus sandbox на живых данных (без ордеров биржи)
    "FUTURES_TESTNET_OPERATIONAL", # прошла lifecycle на Gate.io Futures TestNet
    "FORWARD_SIGNAL_OBSERVED",     # выдала хотя бы один реальный сигнал на НОВЫХ данных после запуска
    "FORWARD_TRADE_COMPLETED",     # завершила хотя бы одну реальную forward-сделку
    "LIVE_READY",                  # готова к боевому (только ручным решением, не автоматически)
]
# отдельные флаги-предупреждения
FLAGS = ["ECONOMIC_EDGE_UNPROVEN", "LIVE_BLOCKED"]

# ТЕКУЩИЕ статусы контуров (обновляются кодом/сервисами; здесь — источник правды по типам контуров)
CONTOURS = {
    "octobot_legacy": {
        "kind": "legacy",
        "engine": "OctoBot (ВЫВЕДЕН)",
        "role": "Выведен из эксплуатации 2026-07-24 после regression GO. Наработки (эвалуаторы "
                "SqueezeBreakout/Donchian, профили) заархивированы; откат через архивы + git-тег "
                "octobot-last-working. В активном продукте не работает.",
        "strategies": [],
        "status": "decommissioned",
        "validates_s11": False,
    },
    "nautilus_portfolios": {
        "kind": "nautilus",
        "engine": "NautilusTrader BacktestEngine (SimulatedExchange + Portfolio)",
        "role": "ОСНОВНОЙ paper-контур портфелей: NautilusWeightStrategy → order lifecycle → "
                "SimulatedExchange → Nautilus Portfolio (изолир. subprocess). Заменил custom PaperExecution.",
        "strategies": ["S1", "S3", "S4", "S5", "S8", "S9"],
        "status": "operational",
        "is_nautilus": True,
    },
    "custom_paper_harness": {
        "kind": "custom-harness",       # ЯВНО: это НЕ Nautilus paper
        "engine": "ntlab custom harness (прямой Gate.io data + PaperExecution + функция сигнала)",
        "role": "ТОЛЬКО тестовый oracle для S11 на живых данных Gate.io (сверка сигнала). Использует "
                "переиспользуемую функцию сигнала, НЕ Nautilus TradingNode/Strategy lifecycle.",
        "strategies": ["S11"],
        "status": "operational",
        "is_nautilus": False,
    },
    "nautilus_runtime": {
        "kind": "nautilus",
        "engine": "NautilusTrader TradingNode (sandbox/simulated execution)",
        "role": "Штатный Nautilus runtime: Strategy → ExecutionEngine → simulated fills → "
                "Nautilus orders/positions/portfolio. Один Strategy class с BacktestNode.",
        "strategies": ["S11"],
        "status": "pending",            # обновится при запуске сервиса
        "is_nautilus": True,
    },
}


def s11_proof_status():
    """Честный текущий статус доказанности S11."""
    return {
        "summary": "runtime operational, execution validated, forward validation pending",
        "BACKTEST_VALIDATED": True,     # прошла чистый трёхчастный тест на event-вселенной листингов (TEST Sharpe +0.84)
        "LOCAL_SANDBOX_OPERATIONAL": None,   # проставит nautilus runtime при запуске
        "FUTURES_TESTNET_OPERATIONAL": False,  # требует TestNet-ключей владельца
        "FORWARD_SIGNAL_OBSERVED": False,   # ещё не было реального сигнала после запуска
        "FORWARD_TRADE_COMPLETED": False,
        "ECONOMIC_EDGE_UNPROVEN": True,     # backtest ≠ доказанный экономический край
        "LIVE_READY": False,
        "LIVE_BLOCKED": True,
        "note": "replay 0G — ТЕСТ механизма, НЕ forward validation. Реальный forward начнётся с "
                "первого сигнала на новых листингах после запуска.",
    }
