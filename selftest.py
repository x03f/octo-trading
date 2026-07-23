"""Smoke-тест движка на текущем озере. Запуск: python selftest.py"""
import sys, time
sys.path.insert(0, "/opt/octobot/strategy-lab")
import numpy as np
from engine import (load_panel, list_universe, buy_hold_single,
                    buy_hold_equal_weight, CostModel)
from engine.metrics import fmt
from engine import strategy as S


def main():
    coins = list_universe("1d")
    print(f"universe ({len(coins)}): {coins}")
    p = load_panel(coins, "1d")
    print(p)
    print("span:", time.strftime("%Y-%m-%d", time.gmtime(p.ts[0] / 1000)),
          "→", time.strftime("%Y-%m-%d", time.gmtime(p.ts[-1] / 1000)))

    for c in ["BTC", "ETH", "SOL"]:
        if c in coins:
            print(f"{c:5} buy-hold:", fmt(buy_hold_single(p, c)["stats"]))
    print("EW basket :", fmt(buy_hold_equal_weight(p, cost=None)["stats"]))
    print("EW basket$:", fmt(buy_hold_equal_weight(p, cost=CostModel())["stats"]),
          " (с ежедневным ре-балансом+косты)")

    # индикаторы — smoke на отсутствие ошибок и разумную заполненность
    a = S.adx(p.high, p.low, p.close, 14)
    at = S.atr(p.high, p.low, p.close, 14)
    dh = S.rolling_max(p.high, 20)
    print(f"indicators finite frac: adx={np.isfinite(a).mean():.2f} "
          f"atr={np.isfinite(at).mean():.2f} donchianH={np.isfinite(dh).mean():.2f}")
    print("SMOKE OK")


if __name__ == "__main__":
    main()
