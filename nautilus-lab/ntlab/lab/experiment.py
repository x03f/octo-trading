"""Полный экспериментальный прогон: backtest + трёхчастный + НАСТОЯЩИЙ walk-forward (ре-оптимизация)
+ Monte Carlo + trade-статистика. Запись в реестр с ID, git_sha, data_sha, seed. Честные метрики.

run_experiment(strategy_key, params, tf) -> запись + артефакт (полная эквити/DD/косты/сделки).
"""
import sys, json, time
sys.path.insert(0, "/opt/octobot/strategy-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
import numpy as np
from engine import load_panel, list_universe, run_portfolio, buy_hold_equal_weight
from engine.strategies import REGISTRY
from engine.validate import _stats_from_returns, walk_forward
from engine.metrics import equity_returns, stats, max_drawdown
from engine.costs import CostModel
from engine.liquidity import passport, terciles, cost_model
from ntlab.lab import registry


def _three_set(r, ppy):
    T = len(r); a, b = int(T * 0.5), int(T * 0.75)
    return (_stats_from_returns(r[:a], ppy), _stats_from_returns(r[a:b], ppy), _stats_from_returns(r[b:], ppy))


def _monte_carlo(returns, ppy, n=500, seed=42):
    rng = np.random.RandomState(seed)
    r = returns[np.isfinite(returns)]
    if len(r) < 30:
        return None, None
    sharpes = []
    for _ in range(n):
        s = rng.choice(r, size=len(r), replace=True)
        sd = s.std()
        sharpes.append((s.mean() / sd) * np.sqrt(ppy) if sd > 0 else 0.0)
    return float(np.percentile(sharpes, 5)), float(np.percentile(sharpes, 95))


def _trade_stats(weights, closes):
    """Round-trip статистика: n_trades, win_rate, profit_factor, expectancy, avg_position."""
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
                    rr = (c / entry_px - 1.0) * np.sign(pos)
                    if np.isfinite(rr):
                        rets.append(rr); sizes.append(abs(entry_w))
                if side != 0:
                    entry_px = c; entry_w = w
                pos = side
    rets = np.array(rets)
    if len(rets) == 0:
        return {"n_trades": 0, "win_rate": None, "profit_factor": None, "expectancy": None, "avg_position": None}
    losses = rets[rets < 0]
    pf = (rets[rets > 0].sum() / abs(losses.sum())) if losses.sum() != 0 else None
    return {"n_trades": int(len(rets)), "win_rate": round(float((rets > 0).mean()), 3),
            "profit_factor": round(float(pf), 2) if pf else None,
            "expectancy": round(float(rets.mean()), 4),
            "avg_position": round(float(np.mean(sizes)), 3) if sizes else None}


def _param_grid(strat, base):
    """Небольшая сетка вокруг числовых параметров стратегии (для ре-оптимизации в walk-forward).
    Берём до 2 числовых атрибутов, каждый ±20%. Ограничена (≤5 конфигов) ради скорости."""
    base = dict(base) if base else {}
    numeric = [(k, v) for k, v in vars(strat).items()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and not k.startswith("_")]
    numeric = numeric[:2]
    grid = [base or {k: v for k, v in numeric}]
    for k, v in numeric:
        for f in (0.8, 1.2):
            p = dict(grid[0])
            p[k] = int(round(v * f)) if isinstance(v, int) else float(v * f)
            grid.append(p)
    # уникализируем
    seen, uniq = set(), []
    for p in grid:
        key = json.dumps(p, sort_keys=True)
        if key not in seen:
            seen.add(key); uniq.append(p)
    return uniq[:5]


def run_experiment(strategy_key, params=None, tf="1d", universe="top_tercile", seed=42):
    t0 = time.time()
    params = params or {}
    coins = list_universe(tf)
    pp = passport(coins); cm = cost_model(pp)
    use = terciles(pp)[0] if universe == "top_tercile" else coins
    panel = load_panel(use, tf)
    cvec = np.array([cm[c] / 1e4 for c in panel.coins])
    StratCls = REGISTRY[strategy_key]
    strat = StratCls(**params) if params else StratCls()
    W = strat.generate(panel)

    res = run_portfolio(panel, W, cost_vec=cvec, ppy=panel.ppy)
    eq = res["equity"]; r = equity_returns(eq)
    full = res["stats"]
    tr, va, te = _three_set(r, panel.ppy)
    mc05, mc95 = _monte_carlo(r, panel.ppy, seed=seed)
    ts = _trade_stats(W, panel.close)

    # НАСТОЯЩИЙ walk-forward: расширяющийся train, ре-оптимизация по сетке, склейка OOS.
    scalar_cost = CostModel(0, 0); scalar_cost.rate = float(np.mean(cvec))   # репрезентативный кост
    wf = None
    try:
        grid = _param_grid(strat, params)
        wfres = walk_forward(panel, lambda p: StratCls(**p), grid, scalar_cost, n_folds=3)
        wf = {"oos_sharpe": wfres["oos"].get("sharpe"), "oos_return": wfres["oos"].get("total_return"),
              "folds": [{"train_end": f["train_end"], "best_params": f["best_params"],
                         "train_sharpe": f["train_sharpe"]} for f in wfres["folds"]],
              "grid_size": len(grid)}
    except Exception as e:
        wf = {"error": str(e)[:100]}

    # честная под-метрика (НЕ walk-forward): средний Sharpe поздних фолдов ОДНОЙ кривой без ре-опт.
    oos_folds = None
    try:
        Tn = len(r); seg = Tn // 5
        f4 = [_stats_from_returns(r[seg*(k+1):seg*(k+2)], panel.ppy).get("sharpe") for k in range(4)]
        f4 = [x for x in f4 if x is not None and np.isfinite(x)]
        oos_folds = float(np.mean(f4)) if f4 else None
    except Exception:
        pass

    bh = buy_hold_equal_weight(panel)
    bh_stats = bh["stats"] if isinstance(bh, dict) and "stats" in bh else stats(bh, panel.ppy)

    # оценка костов: суммарный оборот × репрезентативная ставка (косты уже в equity, тут — раскрытие)
    turnover_series = res.get("turnover")
    total_turnover = float(np.nansum(turnover_series)) if turnover_series is not None else None
    est_fees_frac = round(total_turnover * float(np.mean(cvec)), 4) if total_turnover is not None else None

    survived = (va.get("sharpe") is not None and np.isfinite(va["sharpe"]) and va["sharpe"] > 0
                and te.get("sharpe") is not None and np.isfinite(te["sharpe"]) and te["sharpe"] > 0.3)
    span = f"{time.strftime('%Y-%m-%d', time.gmtime(panel.ts[0]/1000))}..{time.strftime('%Y-%m-%d', time.gmtime(panel.ts[-1]/1000))}"

    def _r(x): return float(x) if x is not None and np.isfinite(x) else None
    def _ds(a, n=120):
        a = np.asarray(a, float)
        idx = np.linspace(0, len(a)-1, min(n, len(a))).astype(int)
        return [round(float(a[i]), 5) for i in idx]

    run = {
        "run_id": registry.new_run_id(strategy_key),
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "strategy": strategy_key, "params": params, "universe": universe, "tf": tf,
        "period": span, "seed": seed,
        "n_trades": ts["n_trades"], "win_rate": ts["win_rate"],
        "profit_factor": ts["profit_factor"], "expectancy": ts["expectancy"], "avg_position": ts["avg_position"],
        "total_return": _r(full["total_return"]), "sharpe": _r(full.get("sharpe")),
        "sortino": _r(full.get("sortino")), "calmar": _r(full.get("calmar")),
        "max_dd": _r(full.get("max_dd")), "turnover": _r(full.get("avg_turnover")),
        "valid_sharpe": _r(va.get("sharpe")), "test_sharpe": _r(te.get("sharpe")),
        "wf_sharpe": _r(wf.get("oos_sharpe") if isinstance(wf, dict) else None),   # НАСТОЯЩИЙ walk-forward OOS
        "oos_folds_sharpe": _r(oos_folds),                                          # честно: не walk-forward
        "walk_forward": wf,
        "mc_sharpe_p05": _r(mc05), "mc_sharpe_p95": _r(mc95),
        "benchmark_return": _r(bh_stats["total_return"]),
        # полные артефакт-ряды (в JSON, не в SQL-схему)
        "equity_curve": _ds(eq), "dd_curve": _ds((np.asarray(eq)/np.maximum.accumulate(eq)-1.0)*100),
        "est_fees_frac": est_fees_frac, "total_turnover": round(total_turnover, 2) if total_turnover else None,
        "cost_model": "per-coin cvec (Step0); walk-forward — скалярный mean(cvec)",
        "verdict": "survived_3set" if survived else "edge_unproven",
        "elapsed_s": round(time.time() - t0, 1),
    }
    registry.record(run)
    return run


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "S8"
    run = run_experiment(key)
    wf = run.get("walk_forward", {})
    print(f"эксперимент {run['run_id']}: ret {run['total_return']*100:+.1f}% Sh {run['sharpe']} "
          f"VALID {run['valid_sharpe']} TEST {run['test_sharpe']} trades {run['n_trades']} PF {run['profit_factor']}")
    print(f"  walk-forward (ре-оптимизация, {wf.get('grid_size')} конфигов, {len(wf.get('folds',[]))} фолдов): "
          f"OOS Sharpe {run['wf_sharpe']} | oos_folds (не WF) {run['oos_folds_sharpe']}")
    print(f"  est_fees {run['est_fees_frac']} turnover {run['total_turnover']} -> {run['verdict']}")
    print(f"всего в реестре: {registry.count()}")
