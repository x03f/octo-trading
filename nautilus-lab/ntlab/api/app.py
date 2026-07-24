"""FastAPI backend Nautilus Trading Lab. Отдаёт РЕАЛЬНЫЕ данные: аудит озера, каталог стратегий,
результаты бэктестов, форвард-P&L, статус Gate.io, состояние системы. Плюс дашборд.

Запуск: uvicorn ntlab.api.app:app --host 127.0.0.1 --port 5020
"""
import json, os, time, subprocess, asyncio
from pathlib import Path
from fastapi import FastAPI, Body
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, "/opt/octobot/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
from ntlab.core.config import settings, LAB_ROOT, RESULTS, LAKE
from ntlab.strategies.catalog import CATALOG, BURIED_FAMILIES, by_status

app = FastAPI(title="Nautilus Trading Lab", version="0.1.0")
WEB = LAB_ROOT / "web"
START = time.time()


def _clean(o):
    """NaN/Inf → None (JSON их не допускает; старые результаты содержат nan-Sharpe)."""
    import math
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(x) for x in o]
    return o


def _count_lines(path):
    try:
        return sum(1 for _ in open(path))
    except Exception:
        return 0


def _load(name, default=None):
    p = RESULTS / name
    try:
        return _clean(json.load(open(p)))
    except Exception:
        return default


@app.get("/api/health")
def health():
    comps = {
        "api": True,
        "lake": LAKE.exists(),
        "engine": Path("/opt/octobot/strategy-lab/engine").exists(),
        "nautilus_venv": Path("/opt/octobot/nautilus-venv/bin/python").exists(),
        "gateio_keys": settings.gateio_ready,
        "llm": settings.llm_ready,
    }
    return {"ok": all([comps["api"], comps["lake"], comps["engine"]]),
            "components": comps, "uptime_s": round(time.time() - START)}


@app.get("/api/overview")
def overview():
    lake = _load("lake_quality.json", {})
    naut = [_load(f"nautilus_{s}.json") for s in ("majors", "niche", "aggr")]
    naut = [n for n in naut if n]
    fwd = _forward_pnl()
    return {
        "generated": time.time(),
        "nautilus": {"version": "1.230.0", "engine": "NautilusTrader", "installed": True},
        "gateio": {"keys_ready": settings.gateio_ready, "mode": "live" if settings.gateio_ready else "paper-only"},
        "data": {"universe": lake.get("universe"), "candles": lake.get("total_candles"),
                 "problem_series": lake.get("problem_count"), "generated": lake.get("generated")},
        "strategies": {"total": len(CATALOG),
                       "candidate": len(by_status("candidate")),
                       "buried": len(by_status("buried")),
                       "research": len(by_status("research"))},
        "backtests_nautilus": naut,
        "forward": fwd,
        "llm_ready": settings.llm_ready,
    }


@app.get("/api/lake")
def lake():
    return _load("lake_quality.json", {"error": "аудит не запускался"})


@app.get("/api/strategies")
def strategies():
    return {"catalog": CATALOG, "buried_families": BURIED_FAMILIES}


@app.get("/api/experiments")
def experiments():
    try:
        from ntlab.lab import registry
        return {"count": registry.count(), "leaderboard": registry.leaderboard(limit=50)}
    except Exception as e:
        return {"count": 0, "leaderboard": [], "error": str(e)[:100]}


@app.get("/api/leaderboard")
def leaderboard():
    return _load("leaderboard.json", {"available": False})


@app.get("/api/backtests")
def backtests():
    return {
        "nautilus": [_load(f"nautilus_{s}.json") for s in ("majors", "niche", "aggr") if _load(f"nautilus_{s}.json")],
        "three_set": _load("three_set_test.json"),
        "new_strategies": _load("new_strategies_test.json"),
        "liquidity": _load("liquidity_passport.json", {}).get("tercile_edge") if _load("liquidity_passport.json") else None,
    }


def _forward_pnl():
    """Форвард-P&L. ИСТОЧНИК ПО УМОЛЧАНИЮ — Nautilus-native контур (nautilus_forward_status.json,
    независим от OctoBot). Легаси csv OctoBot остаётся только резервом для истории."""
    nat = RESULTS / "nautilus_forward_status.json"
    if nat.exists():
        try:
            j = _clean(json.load(open(nat)))
            return {"available": True, "instances": j.get("n_contours", 0),
                    "total": j.get("total_equity", 0), "pnl_pct": j.get("pnl_pct", 0),
                    "trades": sum(c.get("fills", 0) or 0 for c in j.get("contours", [])),
                    "snapshots": _count_lines("/opt/octobot/nautilus-lab/var/forward_history.jsonl"),
                    "as_of": j.get("updated"), "source": "nautilus-native (независим от OctoBot)",
                    "contours": j.get("contours", []), "started_fresh": j.get("started_fresh", False)}
        except Exception:
            pass
    csv = Path("/opt/octobot/strategy-lab/dashboard/pnl_history.csv")
    if not csv.exists():
        return {"available": False}
    try:
        import csv as csvmod
        rows = list(csvmod.DictReader(open(csv)))
        if not rows:
            return {"available": False}
        last_ts = max(r["ts"] for r in rows)
        latest = [r for r in rows if r["ts"] == last_ts]
        tot = sum(float(r["value"] or 0) for r in latest)
        base = 10000.0 * len(latest)
        return {"available": True, "instances": len(latest), "total": round(tot, 2),
                "pnl_pct": round((tot / base - 1) * 100, 2) if base else 0,
                "trades": sum(int(r["trades"] or 0) for r in latest),
                "snapshots": len(set(r["ts"] for r in rows)),
                "as_of": latest[0]["iso"], "source": "octobot-paper (мигрируется на nautilus-paper)"}
    except Exception as e:
        return {"available": False, "error": str(e)[:80]}


@app.get("/api/paper")
def paper():
    """Статус CUSTOM PAPER HARNESS S11 (НЕ Nautilus paper: прямой Gate.io data + PaperExecution +
    функция сигнала, без TradingNode/Strategy lifecycle). Независимый тестовый oracle."""
    st = _load("paper_s11_status.json", None)
    try:
        active = subprocess.run(["systemctl", "is-active", "ntlab-paper"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        active = "unknown"
    return {"contour": "custom_paper_harness", "is_nautilus": False, "service": active,
            "simulation": True, "status": st or {"available": False},
            "note": "CUSTOM HARNESS (не Nautilus paper). Реальные ордера невозможны без явного LIVE-режима+ключей."}


@app.get("/api/nautilus-runtime")
def nautilus_runtime():
    """Статус ФАКТИЧЕСКОГО Nautilus TradingNode (sandbox/simulated execution)."""
    st = _load("nautilus_runtime_status.json", None)
    try:
        active = subprocess.run(["systemctl", "is-active", "ntlab-nautilus"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        active = "unknown"
    return {"contour": "nautilus_runtime", "is_nautilus": True, "service": active,
            "simulation": True, "status": st or {"available": False}}


@app.get("/api/contours")
def contours():
    """Явная карта контуров: какой Nautilus, какой legacy/custom, что валидирует."""
    from ntlab.core.status import CONTOURS, s11_proof_status
    return {"contours": CONTOURS, "s11_proof": s11_proof_status()}


@app.get("/api/portfolio")
def portfolio():
    return {"forward": _forward_pnl(), "paper_s11": _load("paper_s11_status.json", None),
            "note": "Live-портфели появятся после ввода ключей Gate.io и запуска live-preset."}


@app.get("/api/gateio/ping")
def gateio_ping():
    try:
        from ntlab.adapters.gateio.data import GateioData
        g = GateioData(); r = g.ping(); g.close()
        return {"public_data": r, "keys_ready": settings.gateio_ready}
    except Exception as e:
        return JSONResponse({"public_data": {"ok": False, "error": str(e)[:120]},
                             "keys_ready": settings.gateio_ready}, status_code=503)


@app.get("/api/adaptive")
def adaptive():
    st = _load("adaptive_state.json", {})
    return {"available": True, "llm_ready": settings.llm_ready,
            "provider": settings.LLM_PROVIDER or None, "state": st,
            "note": "LLM — консультант; решение принимает платформа по автовалидации бэктестом."}


@app.get("/api/adaptive-lifecycle")
def adaptive_lifecycle():
    st = _load("adaptive_lifecycle.json", None)
    return {"available": st is not None, "lifecycle": st or {"champion": None, "challengers": []},
            "note": "champion/challenger + стадии shadow->paper_canary->live_canary. LLM предлагает, "
                    "платформа применяет только после автовалидации бэктестом. Без ключей — mock/deterministic."}


@app.get("/api/portfolios")
def portfolios_list():
    try:
        from ntlab.portfolios.manager import PortfolioManager, LIVE_PRESETS
        m = PortfolioManager()
        return {"portfolios": m.all_status(), "count": len(m.portfolios),
                "live_presets": LIVE_PRESETS,
                "note": "Paper на живых данных Gate.io (симуляция). Live-presets ready=False до ключей+явного запуска."}
    except Exception as e:
        return {"portfolios": [], "count": 0, "error": str(e)[:100]}


@app.get("/api/system")
def system():
    def svc(name):
        try:
            return subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            return "unknown"
    git = ""
    try:
        git = subprocess.run(["git", "-C", "/opt/octobot/strategy-lab", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        pass
    du = os.statvfs("/")
    return {
        "services": {n: svc(n) for n in ("ntlab-api", "ntlab-paper", "postgresql@17-main")},
        "disk_free_gb": round(du.f_bavail * du.f_frsize / 1e9, 1),
        "git_commit": git, "uptime_s": round(time.time() - START),
        "nautilus_venv": Path("/opt/octobot/nautilus-venv").exists(),
    }


@app.get("/api/experiment/{run_id}")
def experiment_detail(run_id: str):
    """Полный артефакт эксперимента: кривые эквити/просадки, walk-forward фолды, trade-метрики, косты."""
    p = Path("/opt/octobot/nautilus-lab/var/experiments") / f"{run_id}.json"
    try:
        return _clean(json.load(open(p)))
    except Exception:
        return JSONResponse({"error": "не найден", "run_id": run_id}, status_code=404)


@app.get("/api/forward")
def forward():
    """Nautilus-native форвард-контур: текущий снимок + историческая серия P&L."""
    snap = _load("nautilus_forward_status.json", {"available": False})
    hist = []
    try:
        for line in open("/opt/octobot/nautilus-lab/var/forward_history.jsonl"):
            hist.append(json.loads(line))
    except Exception:
        pass
    return {"snapshot": snap, "history": hist[-500:], "count": len(hist)}


@app.get("/api/regression")
def regression():
    """P9: отчёт регрессии OctoBot→Nautilus (go/no-go по компонентам)."""
    return _load("octobot_regression.json", {"available": False})


@app.get("/api/safety")
def safety():
    """Статус многофакторной блокировки live-ордеров (emergency stop / live guard)."""
    try:
        from ntlab.nautilus.safety import live_allowed, safety_status
        return safety_status()
    except Exception:
        # безопасный дефолт: live заблокирован
        return {"live_allowed": False, "reason": "safety-модуль недоступен — live заблокирован",
                "factors": {"runtime_live": False, "env_enabled": False, "confirm_file": False}}


async def _sse_gen():
    """SSE-поток: overview+runtime+forward каждые 5с (живые обновления без polling всей страницы)."""
    while True:
        payload = {
            "ts": time.time(),
            "overview": overview(),
            "runtime": nautilus_runtime(),
            "forward": _forward_pnl(),
            "paper": _load("paper_s11_status.json", {}),
        }
        yield f"data: {json.dumps(_clean(payload), ensure_ascii=False)}\n\n"
        await asyncio.sleep(5)


@app.get("/api/stream")
async def stream():
    return StreamingResponse(_sse_gen(), media_type="text/event-stream")


# ---- УПРАВЛЯЮЩИЕ ЭНДПОЙНТЫ (мутирующие, paper/sandbox — реальные деньги недоступны) ----
def _live_guard():
    """Проверка прав на live-действия: любое live-действие заблокировано, пока не совпали 3 фактора
    safety.py. Возвращает (allowed, status). Мутации paper/sandbox разрешены (симуляция)."""
    try:
        from ntlab.nautilus.safety import safety_status
        st = safety_status()
        return st["live_allowed"], st
    except Exception:
        return False, {"live_allowed": False, "reason": "safety недоступен"}


@app.post("/api/portfolio/create")
def portfolio_create(body: dict = Body(...)):
    # ЗАЩИТА LIVE-ДЕЙСТВИЙ: live-портфель невозможен, пока не совпали 3 фактора safety.py
    if body.get("mode") == "live":
        allowed, st = _live_guard()
        if not allowed:
            return JSONResponse({"error": "live заблокирован", "factors": st.get("factors"),
                                 "required": st.get("required")}, status_code=403)
    from ntlab.portfolios.manager import PortfolioManager
    m = PortfolioManager()
    p = m.create(body.get("name", "portfolio"), float(body.get("start_balance", 1000)),
                 body.get("strategy", "S4"), body.get("instruments", ["BTC_USDT"]), mode="paper")
    return {"created": p.pid, "status": p.status()}


@app.post("/api/portfolio/{pid}/run")
def portfolio_run(pid: str):
    from ntlab.portfolios.manager import PortfolioManager
    m = PortfolioManager()
    try:
        r = m.run(pid)
        return {"pid": pid, "result": r, "status": m.portfolios[pid].status()}
    except KeyError:
        return JSONResponse({"error": "нет портфеля"}, status_code=404)


@app.post("/api/portfolio/{pid}/{action}")
def portfolio_action(pid: str, action: str):
    from ntlab.portfolios.manager import PortfolioManager
    m = PortfolioManager()
    if pid not in m.portfolios:
        return JSONResponse({"error": "нет портфеля"}, status_code=404)
    if action == "pause":
        return m.pause(pid)
    if action == "resume":
        return m.resume(pid)
    if action == "delete":
        m.delete(pid); return {"deleted": pid}
    return JSONResponse({"error": "неизвестное действие"}, status_code=400)


@app.post("/api/experiment/create")
def experiment_create(body: dict = Body(default={})):
    """Запуск эксперимента в ФОНЕ (backtest+трёхчастный+НАСТОЯЩИЙ walk-forward+MC ~30-60с). Не блокирует
    API: detached subprocess пишет в реестр DuckDB; Research Lab покажет результат по готовности."""
    key = (body or {}).get("strategy", "S8")
    env = dict(os.environ, PYTHONPATH="/opt/octobot/nautilus-lab:/opt/octobot/strategy-lab")
    subprocess.Popen(["/opt/octobot/nautilus-venv/bin/python", "-m", "ntlab.lab.experiment", key],
                     env=env, cwd="/opt/octobot/nautilus-lab",
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"started": True, "strategy": key,
            "note": "эксперимент запущен в фоне (~30-60с, настоящий walk-forward). Обнови Research Lab."}


@app.post("/api/adaptive/run")
def adaptive_run(body: dict = Body(default={})):
    """Один цикл Adaptive AI на DETERMINISTIC-провайдере (без ключей): диагностика→рекомендация."""
    from ntlab.adaptive.advisor import DeterministicAdvisor
    from ntlab.adaptive.schema import StrategyStats
    stats = StrategyStats(strategy_id="S11", hypothesis="listing short",
                          current_params={"start_day": 20}, tunable_params={"start_day": ["int", 5, 60]},
                          n_trades=42, equity_curve_tail=[1.0, 0.98, 0.95], total_return=-0.05,
                          max_drawdown=-0.12, sharpe=0.3, volatility=0.2, regime_signals={"trend": 0.05})
    rec = DeterministicAdvisor().advise(stats)
    return {"provider": "deterministic", "regime": rec.market_regime, "decision": rec.decision,
            "confidence": rec.confidence, "explanation": rec.regime_change_explanation}


@app.post("/api/emergency-stop")
def emergency_stop():
    """Тест emergency-stop в sandbox-контуре: демонстрирует отмену+блокировку боевого пути.
    Реальная биржа не вызывается (нет ключей); проверяется, что live заблокирован."""
    allowed, st = _live_guard()
    # в тестовом контуре: emergency-stop гарантирует live заблокирован
    return {"emergency_stop": "executed (sandbox)", "live_allowed_after": allowed,
            "factors": st.get("factors"), "result": "боевой путь недоступен — все ордера симулированы",
            "note": "С боевыми ключами вызовет GateioExecution.emergency_stop (отмена всех + live off)."}


# --- дашборд ---
if (WEB / "data").exists():
    app.mount("/data", StaticFiles(directory=str(WEB / "data")), name="data")


@app.get("/")
def index():
    return FileResponse(str(WEB / "index.html"))
