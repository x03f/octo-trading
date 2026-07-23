"""Сводный дашборд бумажных инстансов OctoBot.

Агрегирует /api/historical_portfolio_value и /api/trades со всех инстансов и отдаёт
одну страницу. Только чтение — ничем не управляет, торговлю не трогает.
Запуск: /opt/octobot/bot/venv/bin/python server.py   (порт 5010)
"""
import json, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder=None)
HERE = "/opt/octobot/dashboard"
START_CAPITAL = 10000.0

# слот = категориальный цвет (фиксированный порядок, НИКОГДА не циклится)
INSTANCES = [
    {"key": "squeeze-majors",  "port": 5003, "slot": 1, "strategy": "S8 «Сквиз»",
     "portfolio": "10 мажоров", "market": "спот",       "url": None},
    {"key": "turtle-majors",   "port": 5004, "slot": 2, "strategy": "S4 «Черепаха»-55",
     "portfolio": "10 мажоров", "market": "спот",       "url": None},
    {"key": "squeeze-wide",    "port": 5005, "slot": 3, "strategy": "S8 «Сквиз»",
     "portfolio": "20 пар",     "market": "спот",       "url": None},
    {"key": "turtle-wide",     "port": 5006, "slot": 4, "strategy": "S4 «Черепаха»-55",
     "portfolio": "20 пар",     "market": "спот",       "url": None},
    {"key": "squeeze-fut3",    "port": 5007, "slot": 5, "strategy": "S8 «Сквиз»",
     "portfolio": "10 мажоров", "market": "фьючерсы ×3", "url": None},
    {"key": "lev10",  "port": 5008, "slot": 6, "strategy": "S8 «Сквиз»-быстрый",
     "portfolio": "10 мажоров", "market": "фьючерсы ×10",  "url": None},
    {"key": "lev100", "port": 5009, "slot": 7, "strategy": "S8 «Сквиз»-скальп",
     "portfolio": "10 мажоров", "market": "фьючерсы ×100", "url": None},
    {"key": "squeeze-niche",  "port": 5012, "slot": 8, "strategy": "S8 «Сквиз»",
     "portfolio": "15 нишевых", "market": "спот",       "url": None},
    {"key": "turtle-niche",   "port": 5013, "slot": 9, "strategy": "S4 «Черепаха»-55",
     "portfolio": "15 нишевых", "market": "спот",       "url": None},
    {"key": "squeeze-aggr",   "port": 5014, "slot": 10, "strategy": "S8 «Сквиз»",
     "portfolio": "10 агрессивных", "market": "спот",   "url": None},
]


def load_endpoints():
    """Реальные адреса панелей держим ЛОКАЛЬНО (endpoints.local.json, вне git):
    поддомены намеренно неугадываемые — это часть защиты, им не место в репозитории."""
    try:
        return json.load(open(f"{HERE}/endpoints.local.json"))
    except Exception:
        return {}


ENDPOINTS = load_endpoints()


def read_profile(key):
    """Отслеживаемые пары, плечо и ТФ берём из профиля инстанса — это источник правды."""
    import os
    p = f"/opt/octobot/inst-{key}/user/profiles/strategy_profile"
    out = {"pairs": [], "leverage": None, "tf": None}
    try:
        d = json.load(open(f"{p}/profile.json"))
        c = d.get("config", d)
        cc = c.get("crypto-currencies", {})
        for grp in cc.values():
            out["pairs"] += [s.split(":")[0] for s in grp.get("pairs", [])]
        out["leverage"] = c.get("leverage")
    except Exception:
        pass
    try:
        b = json.load(open(f"{p}/specific_config/BlankStrategyEvaluator.json"))
        out["tf"] = (b.get("required_time_frames") or [None])[0]
    except Exception:
        pass
    return out


def _get(port, path, timeout=6):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def collect(inst):
    pv = _get(inst["port"], "/api/historical_portfolio_value")
    trades = _get(inst["port"], "/api/trades")
    alive = pv is not None or trades is not None
    series = []
    if isinstance(pv, list):
        for p in pv:
            try:
                series.append({"t": float(p["time"]), "v": float(p["value"])})
            except (KeyError, TypeError, ValueError):
                continue
        series.sort(key=lambda x: x["t"])
    cur = series[-1]["v"] if series else (START_CAPITAL if alive else None)
    n_tr = len(trades) if isinstance(trades, list) else 0
    pnl = (cur - START_CAPITAL) if cur is not None else None
    out = dict(inst)
    out["url"] = ENDPOINTS.get(inst["key"]) or f"http://127.0.0.1:{inst['port']}"
    out.update(read_profile(inst["key"]))
    out.update({
        "alive": alive,
        "series": series,
        "value": cur,
        "pnl": pnl,
        "pnl_pct": (pnl / START_CAPITAL * 100.0) if pnl is not None else None,
        "trades": n_tr,
        "last_trades": (trades or [])[-5:] if isinstance(trades, list) else [],
    })
    return out


@app.route("/api/data")
def data():
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(collect, INSTANCES))
    alive = [r for r in rows if r["alive"] and r["value"] is not None]
    total = sum(r["value"] for r in alive)
    base = START_CAPITAL * len(alive)
    return jsonify({
        "generated": time.time(),
        "start_capital": START_CAPITAL,
        "instances": rows,
        "totals": {
            "value": total,
            "base": base,
            "pnl": total - base if alive else 0.0,
            "pnl_pct": ((total - base) / base * 100.0) if base else 0.0,
            "alive": len(alive), "count": len(rows),
            "trades": sum(r["trades"] for r in rows),
        },
    })


@app.route("/api/nautilus")
def nautilus():
    """Результаты бэктестов Nautilus (та же стратегия S4, что тестит OctoBot, но по наборам монет
    в ОДНОМ процессе). Читаем JSON, которые пишет nautilus-venv/multi_backtest.py."""
    out = []
    for s in ("majors", "niche", "aggr"):
        try:
            out.append(json.load(open(f"{HERE}/nautilus_{s}.json")))
        except Exception:
            pass
    return jsonify({"generated": time.time(), "runs": out})


@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5010, threaded=True)
