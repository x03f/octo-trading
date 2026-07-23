"""Честная валидация: держится ли edge ВНЕ выборки (иначе in-sample числа = самообман).

Три проверки:
  • holdout(): метрики на in-sample (первые is_frac) vs out-of-sample (хвост). Параметры нот заданы
    a-priori (не оптимизированы) → это тест ВРЕМЕННО́Й стабильности edge через смену режимов.
  • sensitivity(): метрика по сетке параметров — ПЛАТО (робастно) или ПИК (переобучение/удача).
  • walk_forward(): расширяющийся train → оптимизируем параметр по Sharpe → тестируем на СЛЕДУЮЩЕМ
    невиданном окне → склеиваем OOS-куски. Кислотный тест: обобщается ли оптимизация.
Без look-ahead сохраняется: каждый под-прогон видит только свой срез, решение по закрытой свече.
"""
import numpy as np
from .data import Panel
from .backtester import run_portfolio
from .metrics import stats, equity_returns


def slice_panel(p, a, b):
    return Panel(p.coins, p.ts[a:b], p.open[a:b], p.high[a:b], p.low[a:b],
                 p.close[a:b], p.volume[a:b], p.tf)


def _stats_from_returns(rets, ppy):
    rets = np.asarray(rets, float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        return stats(np.array([1.0]), ppy)
    eq = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    return stats(eq, ppy)


def holdout(panel, strat, cost, is_frac=0.6):
    """Полный прогон, затем метрики отдельно на IS-срезе и OOS-хвосте кривой."""
    res = run_portfolio(panel, strat.generate(panel), cost=cost, ppy=panel.ppy)
    r = equity_returns(res["equity"])
    k = int(len(r) * is_frac)
    return {"IS": _stats_from_returns(r[:k], panel.ppy),
            "OOS": _stats_from_returns(r[k:], panel.ppy),
            "full": res["stats"]}


def sensitivity(panel, make_strat, grid, cost):
    """Сетка параметров → (params, sharpe, total_return, maxDD). Для проверки плато."""
    out = []
    for params in grid:
        res = run_portfolio(panel, make_strat(params).generate(panel), cost=cost, ppy=panel.ppy)
        st = res["stats"]
        out.append((params, st["sharpe"], st["total_return"], st["max_dd"]))
    return out


def walk_forward(panel, make_strat, param_grid, cost, n_folds=4, train_frac=0.5):
    """Расширяющийся train, ре-оптимизация по Sharpe на train, тест на след. окне. Склейка OOS."""
    T = panel.T
    start_test = int(T * train_frac)
    seg = max(1, (T - start_test) // n_folds)
    oos_rets, folds = [], []
    for i in range(n_folds):
        te0 = start_test + i * seg
        te1 = start_test + (i + 1) * seg if i < n_folds - 1 else T
        if te0 >= te1:
            break
        # оптимизация на train = [0, te0)
        train = slice_panel(panel, 0, te0)
        best, best_sh = None, -1e18
        for params in param_grid:
            st = run_portfolio(train, make_strat(params).generate(train),
                               cost=cost, ppy=panel.ppy)["stats"]
            if np.isfinite(st["sharpe"]) and st["sharpe"] > best_sh:
                best_sh, best = st["sharpe"], params
        # тест на [0, te1) с warmup, считаем только хвост [te0, te1)
        seg_panel = slice_panel(panel, 0, te1)
        r = equity_returns(run_portfolio(seg_panel, make_strat(best).generate(seg_panel),
                                         cost=cost, ppy=panel.ppy)["equity"])
        ntest = te1 - te0
        oos_rets.extend(list(r[-ntest:]))
        folds.append({"train_end": te0, "test": (te0, te1),
                      "best_params": best, "train_sharpe": round(best_sh, 2)})
    return {"oos": _stats_from_returns(oos_rets, panel.ppy), "folds": folds,
            "oos_equity": np.concatenate([[1.0], np.cumprod(1.0 + np.array(oos_rets))])
            if oos_rets else np.array([1.0])}
