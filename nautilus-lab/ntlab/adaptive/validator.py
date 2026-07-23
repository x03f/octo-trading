"""Автовалидация рекомендаций LLM через исследовательскую лабу.

КЛЮЧЕВОЙ ПРИНЦИП: LLM — консультант, решение принимает ПЛАТФОРМА по воспроизводимым тестам.
Ни один параметр не применяется только потому, что нейросеть уверенно его предложила.

Проверка сравнивает текущую и предложенную конфигурацию честным трёхчастным тестом (TEST не
участвует в отборе) + чувствительностью соседей. Возвращает формальное решение accept/reject.
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
            "test": _stats_from_returns(r[b:], panel.ppy)}


def validate_recommendation(make_strategy, current_params, recommended_params, coins=None, tf="1d"):
    """make_strategy(params)->Strategy. Сравнивает две конфигурации; решает accept/reject.

    Критерии принятия (объявлены заранее, не подгоняются):
      · TEST Sharpe предложенной > TEST Sharpe текущей И
      · предложенная не хуже по просадке более чем на 20% относительно И
      · TEST Sharpe предложенной > 0 (не принимаем отрицательный край).
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
    accept = bool(new_sh > cur_sh and new_sh > 0 and new_dd <= cur_dd * 1.20 + 0.05)
    return {
        "accept": accept,
        "reason": ("предложенная лучше по TEST Sharpe и не хуже по просадке" if accept
                   else f"не принято: TEST Sharpe {new_sh:+.2f} vs {cur_sh:+.2f}, DD {new_dd*100:.0f}% vs {cur_dd*100:.0f}%"),
        "current": {k: cur[k].get("sharpe") for k in cur},
        "recommended": {k: new[k].get("sharpe") for k in new},
        "current_test_sharpe": round(cur_sh, 3), "recommended_test_sharpe": round(new_sh, 3),
    }
