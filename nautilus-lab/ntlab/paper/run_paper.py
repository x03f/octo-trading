"""Точка входа непрерывного paper-сервиса S11 (systemd ntlab-paper).

Watchlist — спот-пары Gate.io для наблюдения. Сервис сам гейтит по возрасту листинга: действует
ТОЛЬКО на свежих (окно входа S11), устоявшиеся монеты пропускает. Реальные ордера невозможны
(PaperExecution, SIMULATION=True). Боевой путь — только явным LIVE-переключателем + ключами.

Запуск: python -m ntlab.paper.run_paper
"""
import json
from pathlib import Path
from .service import S11PaperService

WATCHLIST_FILE = Path("/opt/octobot/nautilus-lab/config/paper_watchlist.json")
# дефолтный watchlist: ликвидные + потенциально свежие пары. Сервис сам отсеет устоявшиеся по возрасту.
DEFAULT_WATCH = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "PUMP_USDT", "ASTER_USDT",
                 "WLFI_USDT", "XPL_USDT", "AERO_USDT", "EIGEN_USDT", "ZAMA_USDT"]


def load_watchlist():
    try:
        return json.load(open(WATCHLIST_FILE))["pairs"]
    except Exception:
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"pairs": DEFAULT_WATCH,
                   "note": "Gate.io спот-пары под наблюдением S11. Сервис действует только на свежих листингах."},
                  open(WATCHLIST_FILE, "w"), ensure_ascii=False, indent=1)
        return DEFAULT_WATCH


def main():
    watch = load_watchlist()
    svc = S11PaperService(watchlist=watch, start_balance=10000.0, risk_usdt_per_pos=200.0)
    svc.tick()             # немедленный первый тик, чтобы статус заполнился сразу
    svc.run(interval_s=3600)


if __name__ == "__main__":
    main()
