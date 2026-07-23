"""Портфельный бэктестер БЕЗ look-ahead.

Соглашение (критично для честности):
  weights[t, i] — целевой вес актива i, СФОРМИРОВАННЫЙ на закрытии бара t из данных ≤ t.
  Держится на интервале (t, t+1). Доход реализуется на t+1: r = close[t+1]/close[t] − 1.
  Значит эквити растёт: equity[t+1] = equity[t] · (1 + Σ w[t,i]·r[t+1,i]) − косты ребаланса.
Косты берутся с ОБОРОТА относительно ДРЕЙФА прежних весов (реалистично).
funding[t, i] — ставка за период (t−1, t) на перпах: длинная позиция ПЛАТИТ при funding>0.
"""
import numpy as np
from .metrics import stats


def run_portfolio(panel, weights, cost=None, funding=None, ppy=None, cost_vec=None):
    """cost_vec — опциональный пер-монетный кост (доля, N-вектор): круговая стоимость на 1.0
    оборота по каждой монете. Если задан — ПЕРЕОПРЕДЕЛЯЕТ скалярный cost (честно на неликвиде)."""
    C = panel.close
    T, N = C.shape
    if ppy is None:
        ppy = panel.ppy
    W = np.asarray(weights, float)
    if W.shape != (T, N):
        raise ValueError(f"weights {W.shape} != panel {(T, N)}")
    rate = cost.rate if cost is not None else 0.0
    cvec = np.asarray(cost_vec, float) if cost_vec is not None else None
    if cvec is not None and cvec.shape != (N,):
        raise ValueError(f"cost_vec {cvec.shape} != N {(N,)}")

    equity = np.ones(T)
    w_prev = np.zeros(N)          # веса, сформированные на предыдущем баре (держим сейчас)
    turnover_s = np.zeros(T)
    exposure_s = np.zeros(T)
    net_s = np.zeros(T)

    for t in range(1, T):
        prev, cur = C[t - 1], C[t]
        valid = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
        r = np.zeros(N)
        r[valid] = cur[valid] / prev[valid] - 1.0

        wheld = np.where(np.isfinite(w_prev), w_prev, 0.0).copy()
        wheld[~valid] = 0.0        # нельзя держать нелистившийся актив

        port_ret = float(np.dot(wheld, r))
        if funding is not None:    # P&L funding: длинная нога платит f>0 → −w·f
            f = np.nan_to_num(funding[t], nan=0.0)
            f = np.where(valid, f, 0.0)
            port_ret += -float(np.dot(wheld, f))
        gross = 1.0 + port_ret

        wdrift = (wheld * (1.0 + r) / gross) if gross > 0 else wheld
        target = np.where(np.isfinite(W[t]), W[t], 0.0).copy()
        target[~valid] = 0.0

        dturn = np.abs(target - wdrift)          # пер-монетный оборот на этом баре
        turn = float(dturn.sum())
        c = float((dturn * cvec).sum()) if cvec is not None else turn * rate
        equity[t] = equity[t - 1] * gross * (1.0 - c)

        turnover_s[t] = turn
        exposure_s[t] = float(np.abs(target).sum())
        net_s[t] = float(target.sum())
        w_prev = target

    st = stats(equity, ppy)
    st["avg_turnover"] = float(turnover_s[1:].mean()) if T > 1 else 0.0
    st["avg_gross_exposure"] = float(exposure_s[1:].mean()) if T > 1 else 0.0
    st["avg_net_exposure"] = float(net_s[1:].mean()) if T > 1 else 0.0
    return {"equity": equity, "stats": st,
            "turnover": turnover_s, "gross_exposure": exposure_s, "net_exposure": net_s}
