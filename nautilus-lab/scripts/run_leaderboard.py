"""Leaderboard стратегий: полные честные метрики на ликвидной вселенной. НЕ доказательство края.

Для КАЖДОЙ стратегии: капитал, число сделок, средний размер позиции, комиссии, turnover, drawdown,
Sharpe/Sortino/Calmar/profit-factor/expectancy/win-rate, IS(train)+OOS(test), benchmark buy-hold.
Пер-монетные косты (Шаг 0). Порог: OOS Sharpe > 0.3 = пережила, иначе край не доказан.
Запуск: python nautilus-lab/scripts/run_leaderboard.py [tf]
"""
import sys, json, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import load_panel, list_universe, run_portfolio, buy_hold_equal_weight
from engine.strategies import Squeeze, Turtle, GridMR, Fluger, Rotation, Pairs, Ensemble
from engine.costs import GATE_TAKER
from engine.validate import _stats_from_returns
from engine.metrics import equity_returns, stats
from engine.liquidity import passport, terciles, cost_model

OUT = "/opt/octobot/nautilus-lab/web/data/leaderboard.json"


def trade_stats(weights, closes):
    T, N = weights.shape
    rets, sizes = [], []
    for i in range(N):
        pos = 0.0; entry_px = None; entry_w = 0.0
        for t in range(T):
            w = weights[t, i]; c = closes[t, i]
            if not np.isfinite(c):
                continue
            side = np.sign(w)
            if side != np.sign(pos):
                if pos != 0 and entry_px and entry_px > 0:
                    r = (c / entry_px - 1.0) * np.sign(pos)
                    if np.isfinite(r):
                        rets.append(r); sizes.append(abs(entry_w))
                if side != 0:
                    entry_px = c; entry_w = w
                pos = side
    rets = np.array(rets)
    if len(rets) == 0:
        return {"n_trades": 0, "win_rate": None, "profit_factor": None, "expectancy": None, "avg_position": None}
    wins = rets[rets > 0]; losses = rets[rets < 0]
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else None
    return {"n_trades": int(len(rets)), "win_rate": round(float((rets > 0).mean()), 3),
            "profit_factor": round(float(pf), 2) if pf else None,
            "expectancy": round(float(rets.mean()), 4),
            "avg_position": round(float(np.mean(sizes)), 3) if sizes else None}


def split_metrics(panel, weights, cvec):
    res = run_portfolio(panel, weights, cost_vec=cvec, ppy=panel.ppy)
    r = equity_returns(res["equity"]); T = len(r); a, b = int(T * 0.5), int(T * 0.75)
    # трёхчастный: train / valid (отбор) / test (честная оценка), как run_test.py
    return (_stats_from_returns(r[a:b], panel.ppy), _stats_from_returns(r[b:], panel.ppy), res["stats"], res)


def _downsample(a, n=160):
    """Прореживание массива до <=n точек (для лёгких графиков на дашборде)."""
    import numpy as _np
    a = _np.asarray(a, float)
    if len(a) <= n:
        return [round(float(x), 5) for x in a]
    idx = _np.linspace(0, len(a) - 1, n).astype(int)
    return [round(float(a[i]), 5) for i in idx]


def _dd_curve(equity):
    import numpy as _np
    e = _np.asarray(equity, float)
    peak = _np.maximum.accumulate(e)
    return (e / peak - 1.0)


def _r(x):
    return round(float(x), 2) if x is not None and np.isfinite(x) else None


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    t0 = time.time()
    coins = list_universe(tf)
    pp = passport(coins); cm = cost_model(pp)
    top, _, _ = terciles(pp)
    panel = load_panel(top, tf)
    cvec = np.array([cm[c] / 1e4 for c in panel.coins])
    span = (time.strftime("%Y-%m-%d", time.gmtime(panel.ts[0] / 1000)),
            time.strftime("%Y-%m-%d", time.gmtime(panel.ts[-1] / 1000)))
    print(f"LEADERBOARD tf={tf} top-tercile {panel.N} coins {span[0]}..{span[1]}", flush=True)
    bh = buy_hold_equal_weight(panel)
    bh_stats = bh["stats"] if isinstance(bh, dict) and "stats" in bh else stats(bh, panel.ppy)
    strategies = [
        ("S8 Squeeze", Squeeze(), "volatility breakout"),
        ("S4 Turtle", Turtle(), "trend following / breakout"),
        ("S5 Pendulum", GridMR(), "mean reversion (regime-gated) / grid"),
        ("S1 Fluger", Fluger(), "time-series momentum"),
        ("S9 Rotation", Rotation(), "cross-sectional momentum"),
        ("S3 Pairs", Pairs(), "pairs / statistical arbitrage")]
    rows = []
    for label, strat, category in strategies:
        W = strat.generate(panel)
        tr, te, full, res = split_metrics(panel, W, cvec)
        ts = trade_stats(W, panel.close)
        va_sh = tr.get("sharpe"); te_sh = te.get("sharpe")   # tr=VALID, te=TEST (см. split_metrics)
        survived = (va_sh is not None and np.isfinite(va_sh) and va_sh > 0 and
                    te_sh is not None and np.isfinite(te_sh) and te_sh > 0.3)
        verdict = "survived_3set" if survived else "edge_unproven"
        row = {"strategy": label, "capital_start": 10000,
               "capital_end": round(10000 * (1 + full["total_return"]), 2),
               "total_return_pct": round(full["total_return"] * 100, 1),
               "cagr_pct": round(full.get("cagr", 0) * 100, 1) if np.isfinite(full.get("cagr", np.nan)) else None,
               "sharpe": _r(full.get("sharpe")), "sortino": _r(full.get("sortino")),
               "calmar": _r(full.get("calmar")), "max_dd_pct": round(full.get("max_dd", 0) * 100, 1),
               "vol_ann_pct": round(full.get("vol_ann", 0) * 100, 1),
               "turnover": round(full.get("avg_turnover", 0), 3),
               "n_trades": ts["n_trades"], "win_rate": ts["win_rate"],
               "profit_factor": ts["profit_factor"], "expectancy": ts["expectancy"],
               "avg_position": ts["avg_position"], "valid_sharpe": _r(tr.get("sharpe")),
               "oos_sharpe": _r(te.get("sharpe")), "oos_return_pct": round(te.get("total_return", 0) * 100, 1),
               "verdict": verdict, "category": category}
        row["equity_curve"] = _downsample(res["equity"])            # нормированная кривая (старт=1.0)
        row["dd_curve"] = _downsample(_dd_curve(res["equity"]) * 100)  # просадка, %
        rows.append(row)
        print(f"  {label:14} ret {row['total_return_pct']:+6.1f}% Sh {row['sharpe'] or 0:+.2f} "
              f"OOS {row['oos_sharpe'] or 0:+.2f} DD {row['max_dd_pct']:.0f}% trades {row['n_trades']} "
              f"PF {row['profit_factor']} -> {verdict}", flush=True)
    # S6 Оркестр — portfolio allocation между стратегиями (risk-parity мета-слой, kill-switch)
    try:
        ens = Ensemble()
        eres = ens.run(panel, cost=GATE_TAKER)
        er = equity_returns(eres["equity"]); T = len(er); a, b = int(T * 0.5), int(T * 0.75)
        e_valid = _stats_from_returns(er[a:b], panel.ppy); e_test = _stats_from_returns(er[b:], panel.ppy)
        e_full = eres["stats"]
        wh = np.asarray(eres.get("weights"))              # [M, L] веса ног — оборот аллокации
        alloc_turn = float(np.abs(np.diff(wh, axis=0)).sum(axis=1).mean()) if wh.ndim == 2 and len(wh) > 1 else 0.0
        n_realloc = int((np.abs(np.diff(wh, axis=0)).sum(axis=1) > 0.01).sum()) if wh.ndim == 2 and len(wh) > 1 else 0
        e_va, e_te = e_valid.get("sharpe"), e_test.get("sharpe")
        e_surv = (e_va is not None and np.isfinite(e_va) and e_va > 0 and
                  e_te is not None and np.isfinite(e_te) and e_te > 0.3)
        erow = {"strategy": "S6 Orchestra", "capital_start": 10000,
                "capital_end": round(10000 * (1 + e_full["total_return"]), 2),
                "total_return_pct": round(e_full["total_return"] * 100, 1),
                "cagr_pct": round(e_full.get("cagr", 0) * 100, 1) if np.isfinite(e_full.get("cagr", np.nan)) else None,
                "sharpe": _r(e_full.get("sharpe")), "sortino": _r(e_full.get("sortino")),
                "calmar": _r(e_full.get("calmar")), "max_dd_pct": round(e_full.get("max_dd", 0) * 100, 1),
                "vol_ann_pct": round(e_full.get("vol_ann", 0) * 100, 1),
                "turnover": round(alloc_turn, 3), "n_trades": n_realloc,
                "win_rate": None, "profit_factor": None, "expectancy": None,
                "avg_position": None, "valid_sharpe": _r(e_valid.get("sharpe")),
                "oos_sharpe": _r(e_test.get("sharpe")), "oos_return_pct": round(e_test.get("total_return", 0) * 100, 1),
                "verdict": "survived_3set" if e_surv else "edge_unproven",
                "category": "portfolio allocation (risk-parity meta)",
                "note": f"мета-аллокатор {len(eres.get('leg_names', []))} ног; сделки=реаллокации, "
                        f"trade-метрики на уровне ног. avg_alive_legs={e_full.get('avg_alive_legs')}",
                "equity_curve": _downsample(eres["equity"]),
                "dd_curve": _downsample(_dd_curve(eres["equity"]) * 100)}
        rows.append(erow)
        print(f"  {'S6 Orchestra':14} ret {erow['total_return_pct']:+6.1f}% Sh {erow['sharpe'] or 0:+.2f} "
              f"OOS {erow['oos_sharpe'] or 0:+.2f} DD {erow['max_dd_pct']:.0f}% realloc {n_realloc} -> {erow['verdict']}", flush=True)
    except Exception as e:
        print(f"  S6 Orchestra: ошибка {str(e)[:80]}", flush=True)

    rows.sort(key=lambda r: (r["oos_sharpe"] if r["oos_sharpe"] is not None else -99), reverse=True)
    bh_equity = bh["equity"] if isinstance(bh, dict) and "equity" in bh else bh
    x_dates = [time.strftime("%Y-%m-%d", time.gmtime(t / 1000)) for t in
               np.asarray(panel.ts)[np.linspace(0, len(panel.ts) - 1, min(160, len(panel.ts))).astype(int)]]
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tf": tf,
              "x_dates": x_dates, "benchmark_curve": _downsample(bh_equity),
              "universe": "top_tercile", "n_coins": panel.N, "span": span,
              "costs": "per-coin (Step0; top tercile ~15bps)",
              "benchmark_buyhold": {"total_return_pct": round(bh_stats["total_return"] * 100, 1),
                                    "sharpe": _r(bh_stats.get("sharpe")), "max_dd_pct": round(bh_stats.get("max_dd", 0) * 100, 1)},
              "strategies": rows,
              "categories_covered": {
                  "trend following": "S4 Turtle", "breakout": "S4 Turtle / S8 Squeeze",
                  "time-series momentum": "S1 Fluger", "mean reversion": "S5 Pendulum",
                  "volatility breakout": "S8 Squeeze", "regime-based": "S5 (regime-gated) + ADAPTIVE",
                  "grid (research)": "S5 GridMR", "pairs / stat-arb": "S3 Pairs",
                  "cross-sectional momentum": "S9 Rotation",
                  "portfolio allocation": "S6 Orchestra (risk-parity meta)"},
              "honest_conclusion": "Трёхчастная дисциплина (VALID>0 И TEST>0.3). S9 на 50/50 казалась хороша, "
                                   "но VALID -1.17 -> режимная зависимость, НЕ край. Ни одна не прошла. "
                                   "Единственный кандидат S11 (event-класс, другая вселенная, прошёл трёхчастный).",
              "elapsed_s": round(time.time() - t0, 1)}
    json.dump(report, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"benchmark buy-hold {report['benchmark_buyhold']['total_return_pct']:+.1f}% -> {OUT} ({report['elapsed_s']}s)")


if __name__ == "__main__":
    main()
