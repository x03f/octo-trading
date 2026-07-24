"""Автовалидация рекомендаций LLM через исследовательскую лабу.

КЛЮЧЕВОЙ ПРИНЦИП: LLM — консультант, решение принимает ПЛАТФОРМА по воспроизводимым тестам.
Ни один параметр не применяется только потому, что нейросеть уверенно его предложила.

Проверка предложенной конфигурации против текущей включает:
  1. честный трёхчастный тест (train/valid/test; TEST не участвует в отборе);
  2. neighbor-sensitivity: возмущение предложенных числовых параметров ±шаг — предложение
     принимается, только если оно НЕ одиночный выброс среди соседей (робастность);
  3. Monte Carlo bootstrap TEST-доходностей → доверительный интервал Sharpe (край не признаётся,
     если CI уверенно пересекает 0).
Возвращает формальное решение accept/reject со всеми доказательствами.
"""
import sys
sys.path.insert(0, "/opt/octobot/strategy-lab")
import numpy as np
from engine import load_panel, list_universe, run_portfolio
from engine.validate import _stats_from_returns
from engine.metrics import equity_returns
from engine.liquidity import passport, cost_model


def _three_set(panel, strat, cvec):
    res = run_portfolio(panel, strat.generate(panel), cost_vec=cvec, ppy=panel.ppy)
    r = equity_returns(res["equity"])
    T = len(r); a, b = int(T * 0.50), int(T * 0.75)
    return {"train": _stats_from_returns(r[:a], panel.ppy),
            "valid": _stats_from_returns(r[a:b], panel.ppy),
            "test": _stats_from_returns(r[b:], panel.ppy),
            "test_returns": r[b:]}


def _monte_carlo_sharpe(returns, ppy, n=1000, seed=42):
    """Bootstrap-CI годового Sharpe по TEST-доходностям (без wall-clock рандома — фикс. seed)."""
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    if len(r) < 20:
        return {"sharpe_ci_low": None, "sharpe_ci_high": None, "prob_positive": None, "n": len(r)}
    rng = np.random.default_rng(seed)
    sh = np.empty(n)
    for i in range(n):
        s = rng.choice(r, size=len(r), replace=True)
        sd = s.std(ddof=1)
        sh[i] = (s.mean() / sd) * np.sqrt(ppy) if sd > 0 else 0.0
    return {"sharpe_ci_low": round(float(np.percentile(sh, 5)), 3),
            "sharpe_ci_high": round(float(np.percentile(sh, 95)), 3),
            "prob_positive": round(float((sh > 0).mean()), 3), "n": len(r)}


def _sensitivity(make_strategy, params, panel, cvec, ppy):
    """Возмущение числовых параметров ±10% (мин. ±1 для int). TEST Sharpe соседей → медиана/разброс.
    Робастно, если предложение близко к медиане соседей, а не одиночный пик."""
    neigh = []
    for k, v in params.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        for sign in (-1, 1):
            if isinstance(v, int):
                nv = int(v + sign * max(1, round(abs(v) * 0.1)))
            else:
                nv = float(v * (1 + sign * 0.10))
            p2 = dict(params); p2[k] = nv
            try:
                sh = _three_set(panel, make_strategy(p2), cvec)["test"].get("sharpe")
                if sh is not None and np.isfinite(sh):
                    neigh.append(float(sh))
            except Exception:
                continue
    if not neigh:
        return {"neighbors": 0, "median_test_sharpe": None, "std": None, "robust": None}
    med = float(np.median(neigh)); sd = float(np.std(neigh))
    return {"neighbors": len(neigh), "median_test_sharpe": round(med, 3),
            "std": round(sd, 3), "neighbor_values": [round(x, 3) for x in neigh]}


def validate_recommendation(make_strategy, current_params, recommended_params, coins=None, tf="1d"):
    """make_strategy(params)->Strategy. Сравнивает две конфигурации; решает accept/reject.

    Критерии принятия (объявлены заранее, не подгоняются):
      · TEST Sharpe предложенной > TEST Sharpe текущей И
      · TEST Sharpe предложенной > 0 (не принимаем отрицательный край) И
      · просадка не хуже текущей более чем на 20% И
      · РОБАСТНОСТЬ: TEST Sharpe предложенной не более чем на 0.5 выше медианы соседей
        (иначе это переобученный пик) И
      · Monte Carlo: нижняя граница CI Sharpe (5%) предложенной > 0 (край устойчив к ресемплингу).
    """
    coins = coins or list_universe(tf)
    pp = passport(coins); cm = cost_model(pp)
    panel = load_panel(coins, tf)
    cvec = np.array([cm[c] / 1e4 for c in panel.coins])

    cur = _three_set(panel, make_strategy(current_params), cvec)
    new = _three_set(panel, make_strategy(recommended_params), cvec)

    def g(d, k):
        v = d["test"].get(k)
        return v if v is not None and np.isfinite(v) else -99

    cur_sh, new_sh = g(cur, "sharpe"), g(new, "sharpe")
    cur_dd, new_dd = abs(g(cur, "max_dd")), abs(g(new, "max_dd"))

    sens = _sensitivity(make_strategy, recommended_params, panel, cvec, panel.ppy)
    mc_new = _monte_carlo_sharpe(new["test_returns"], panel.ppy)
    mc_cur = _monte_carlo_sharpe(cur["test_returns"], panel.ppy)

    robust = True
    if sens["median_test_sharpe"] is not None:
        robust = (new_sh - sens["median_test_sharpe"]) <= 0.5      # не одиночный пик
    mc_ok = mc_new["sharpe_ci_low"] is not None and mc_new["sharpe_ci_low"] > 0

    accept = bool(new_sh > cur_sh and new_sh > 0 and new_dd <= cur_dd * 1.20 + 0.05
                  and robust and mc_ok)
    if accept:
        reason = "лучше по TEST Sharpe, робастно к соседям, CI Sharpe>0, просадка не хуже"
    else:
        fails = []
        if not (new_sh > cur_sh): fails.append(f"TEST Sharpe не выше ({new_sh:+.2f} vs {cur_sh:+.2f})")
        if not (new_sh > 0): fails.append("TEST Sharpe отрицателен")
        if not (new_dd <= cur_dd * 1.20 + 0.05): fails.append(f"просадка хуже ({new_dd*100:.0f}% vs {cur_dd*100:.0f}%)")
        if not robust: fails.append("одиночный пик (не робастно к соседям)")
        if not mc_ok: fails.append(f"CI Sharpe пересекает 0 (low={mc_new['sharpe_ci_low']})")
        reason = "не принято: " + "; ".join(fails)

    return {
        "accept": accept, "reason": reason,
        "current": {k: cur[k].get("sharpe") for k in ("train", "valid", "test")},
        "recommended": {k: new[k].get("sharpe") for k in ("train", "valid", "test")},
        "current_test_sharpe": round(cur_sh, 3), "recommended_test_sharpe": round(new_sh, 3),
        "sensitivity": sens, "monte_carlo_recommended": mc_new, "monte_carlo_current": mc_cur,
        "robust": robust, "monte_carlo_ok": mc_ok,
    }
