"""Метрики из кривой эквити. Аннуализация через ppy (баров в году)."""
import numpy as np


def equity_returns(equity):
    equity = np.asarray(equity, float)
    return equity[1:] / equity[:-1] - 1.0


def max_drawdown(equity):
    equity = np.asarray(equity, float)
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def _nan():
    return float("nan")


def stats(equity, ppy=365):
    """Полный набор метрик. Возвращает dict."""
    equity = np.asarray(equity, float)
    r = equity_returns(equity)
    r = r[np.isfinite(r)]
    n = len(r)
    out = {"n_bars": n, "total_return": _nan(), "cagr": _nan(), "vol_ann": _nan(),
           "sharpe": _nan(), "sortino": _nan(), "max_dd": _nan(), "calmar": _nan()}
    if n < 2 or equity[0] <= 0 or equity[-1] <= 0:
        if n >= 1 and equity[0] > 0:
            out["total_return"] = float(equity[-1] / equity[0] - 1.0)
            out["max_dd"] = max_drawdown(equity)
        return out

    out["total_return"] = float(equity[-1] / equity[0] - 1.0)
    years = n / ppy
    out["cagr"] = float((equity[-1] / equity[0]) ** (1.0 / years) - 1.0) if years > 0 else _nan()
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    out["vol_ann"] = sd * np.sqrt(ppy)
    out["sharpe"] = (mu / sd) * np.sqrt(ppy) if sd > 0 else _nan()
    downside = r[r < 0]
    dsd = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    out["sortino"] = (mu / dsd) * np.sqrt(ppy) if dsd > 0 else _nan()
    mdd = max_drawdown(equity)
    out["max_dd"] = mdd
    out["calmar"] = float(out["cagr"] / abs(mdd)) if mdd < 0 and np.isfinite(out["cagr"]) else _nan()
    return out


def fmt(st):
    """Компактная строка для лога."""
    def p(x):
        return f"{x*100:+.1f}%" if np.isfinite(x) else "  n/a"
    def f(x):
        return f"{x:+.2f}" if np.isfinite(x) else " n/a"
    return (f"ret {p(st['total_return'])} | CAGR {p(st['cagr'])} | vol {p(st['vol_ann'])} | "
            f"Sharpe {f(st['sharpe'])} | Sortino {f(st['sortino'])} | maxDD {p(st['max_dd'])} | "
            f"Calmar {f(st['calmar'])}")
