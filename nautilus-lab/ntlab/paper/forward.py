"""Nautilus-native форвард-контур (P9): собственный источник форвард-P&L вместо csv OctoBot.
Агрегирует РАБОТАЮЩИЕ Nautilus/paper-контуры (TradingNode S11 + custom harness + paper-портфели)
в единый снимок nautilus_forward_status.json и историю var/forward_history.jsonl.

Честно: этот контур стартует ЗАНОВО (нулевая история). Историческая кривая OctoBot архивируется
отдельно (scripts/archive_octobot.sh) и НЕ переносится — форвард-эвиденс копится заново.
"""
import json, time
from pathlib import Path

RESULTS = Path("/opt/octobot/nautilus-lab/web/data")
HIST = Path("/opt/octobot/nautilus-lab/var/forward_history.jsonl")


def _load(name):
    try:
        return json.load(open(RESULTS / name))
    except Exception:
        return {}


def snapshot():
    rt = _load("nautilus_runtime_status.json")     # Nautilus TradingNode S11 (SANDBOX)
    paper = _load("paper_s11_status.json")          # custom paper harness S11
    try:
        from ntlab.portfolios.manager import PortfolioManager
        ports = PortfolioManager().all_status()
    except Exception:
        ports = []

    contours = []
    if rt.get("equity_usdt") is not None:
        contours.append({"name": "nautilus_runtime_s11", "equity": float(rt["equity_usdt"]),
                         "start": 100000.0, "engine": "NautilusTrader TradingNode SANDBOX",
                         "state": rt.get("strategy_state")})
    if paper.get("equity") is not None:
        contours.append({"name": "custom_paper_s11", "equity": float(paper["equity"]),
                         "start": float(paper.get("start_balance", 10000.0)),
                         "engine": "custom harness", "fills": paper.get("fills", 0)})
    for p in ports:
        if p.get("equity") is not None:
            contours.append({"name": p.get("name"), "equity": float(p["equity"]),
                             "start": float(p.get("start_balance", 0) or 0),
                             "engine": "paper portfolio", "strategy": p.get("strategy")})

    tot_eq = sum(c["equity"] for c in contours)
    tot_start = sum(c["start"] for c in contours) or 1.0
    pnl_pct = round((tot_eq / tot_start - 1) * 100, 3)
    snap = {
        "source": "nautilus-native",
        "contours": contours, "n_contours": len(contours),
        "total_equity": round(tot_eq, 2), "total_start": round(tot_start, 2),
        "pnl_pct": pnl_pct,
        "started_fresh": True,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("Форвард-контур на Nautilus/paper (независим от OctoBot). Стартовал заново — "
                 "историческая кривая OctoBot заархивирована и НЕ переносится (форвард-эвиденс копится с нуля)."),
    }
    json.dump(snap, open(RESULTS / "nautilus_forward_status.json", "w"), ensure_ascii=False, indent=1)
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with open(HIST, "a") as f:
        f.write(json.dumps({"ts": snap["updated"], "pnl_pct": pnl_pct,
                            "total_equity": snap["total_equity"], "n": len(contours)}) + "\n")
    return snap


if __name__ == "__main__":
    s = snapshot()
    print(f"forward snapshot: {s['n_contours']} контуров, equity ${s['total_equity']}, P&L {s['pnl_pct']}%")
