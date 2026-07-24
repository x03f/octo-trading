"""Многофакторная защита от боевого исполнения. Live НЕВОЗМОЖЕН по умолчанию.

Для реального режима ОДНОВРЕМЕННО требуются ТРИ независимых фактора:
  1) runtime mode = "live" (аргумент запуска, не дефолт);
  2) env-флаг NTLAB_LIVE_ENABLED=true;
  3) файл-подтверждение /opt/octobot/nautilus-lab/config/LIVE_CONFIRMED с точной фразой.
Отсутствие любого → live заблокирован. Paper/sandbox не могут вызвать боевой путь в принципе.
"""
import os
from pathlib import Path

CONFIRM_FILE = Path("/opt/octobot/nautilus-lab/config/LIVE_CONFIRMED")
CONFIRM_PHRASE = "I_UNDERSTAND_REAL_MONEY_ORDERS"


def live_allowed(runtime_mode: str) -> bool:
    """True только если ВСЕ три фактора совпали. Иначе — заблокировано."""
    if runtime_mode != "live":
        return False
    if os.getenv("NTLAB_LIVE_ENABLED", "false").lower() != "true":
        return False
    try:
        if CONFIRM_FILE.read_text().strip() != CONFIRM_PHRASE:
            return False
    except Exception:
        return False
    return True


def assert_no_live(runtime_mode: str):
    """Гарантия, что из paper/sandbox боевой путь недоступен. Кидает при попытке."""
    if runtime_mode in ("paper", "sandbox", "backtest"):
        return  # эти режимы физически не создают боевой exec-client
    if not live_allowed(runtime_mode):
        raise PermissionError("LIVE заблокирован: нужны runtime=live + NTLAB_LIVE_ENABLED=true + файл-подтверждение")


def safety_status(runtime_mode: str = "sandbox"):
    """Снимок факторов защиты для дашборда (Live Trading). Ничего не разрешает — только читает."""
    env_ok = os.getenv("NTLAB_LIVE_ENABLED", "false").lower() == "true"
    try:
        confirm_ok = CONFIRM_FILE.exists() and CONFIRM_FILE.read_text().strip() == CONFIRM_PHRASE
    except Exception:
        confirm_ok = False
    factors = {"runtime_live": runtime_mode == "live", "env_enabled": env_ok, "confirm_file": confirm_ok}
    allowed = all(factors.values())
    return {
        "live_allowed": allowed,
        "reason": ("ВСЕ три фактора совпали — live разрешён" if allowed
                   else "live заблокирован: не совпал минимум один из трёх факторов"),
        "factors": factors,
        "required": ["runtime=live", "NTLAB_LIVE_ENABLED=true", f"файл {CONFIRM_FILE.name} с фразой"],
        "emergency_stop": "мгновенный: любой из факторов сброшен → боевой путь недоступен",
    }
