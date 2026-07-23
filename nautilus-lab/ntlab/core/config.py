"""Конфигурация Nautilus Trading Lab. Пути, секреты, режимы.

Секреты (LLM/Gate.io ключи) — ТОЛЬКО из окружения (systemd EnvironmentFile 600), не в коде.
Один код стратегии; режим (backtest/paper/live) и провайдеры данных/исполнения — из конфига.
"""
import os
from pathlib import Path

# --- корни ---
LAB_ROOT = Path("/opt/octobot/nautilus-lab")
LAKE = Path("/opt/octobot/strategy-lab/data/ohlcv")     # мигрируем ссылкой, не копируем 1.4ГБ
FUNDING = Path("/opt/octobot/strategy-lab/data/funding")
ENGINE_ROOT = Path("/opt/octobot/strategy-lab")          # переиспользуем честный numpy-движок
RESULTS = LAB_ROOT / "web" / "data"
REGISTRY_DB = LAB_ROOT / "var" / "registry.duckdb"       # реестр экспериментов (DuckDB-файл)

for p in (RESULTS, REGISTRY_DB.parent):
    p.mkdir(parents=True, exist_ok=True)


class Settings:
    """Единая точка настроек. Секреты — из env, остальное — дефолты."""
    # режимы
    MODES = ("backtest", "paper", "live")
    # биржа
    EXCHANGE = "gateio"
    VENUE = "GATEIO"
    QUOTE = "USDT"
    # косты Gate.io VIP2 спот (доля)
    SPOT_MAKER = 0.00075
    SPOT_TAKER = 0.0016
    # секреты (env; пусто = функция недоступна, честно показываем в UI)
    GATEIO_API_KEY = os.getenv("GATEIO_API_KEY", "")
    GATEIO_API_SECRET = os.getenv("GATEIO_API_SECRET", "")
    LLM_PROVIDER = os.getenv("NTLAB_LLM_PROVIDER", "")     # anthropic|openai|""
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    # API
    API_HOST = os.getenv("NTLAB_API_HOST", "127.0.0.1")
    API_PORT = int(os.getenv("NTLAB_API_PORT", "5020"))

    @property
    def gateio_ready(self) -> bool:
        return bool(self.GATEIO_API_KEY and self.GATEIO_API_SECRET)

    @property
    def llm_ready(self) -> bool:
        if self.LLM_PROVIDER == "anthropic":
            return bool(self.ANTHROPIC_API_KEY)
        if self.LLM_PROVIDER == "openai":
            return bool(self.OPENAI_API_KEY)
        return False


settings = Settings()
