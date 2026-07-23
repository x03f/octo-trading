"""Сверка: мой движок на ТЕХ ЖЕ свечах, что бэктест OctoBot.
Реплицирует Donchian-тентакл (single-channel, long-only спот) и считает P&L моим движком —
это «мой ожидаемый OctoBot-результат». Дальше сравниваем с реальным бэктестом OctoBot (bt_run2)."""
import sys, warnings, time
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine.octobot_data import load_octobot_panel, describe, octobot_signal_donchian
from engine import CostModel, run_portfolio, buy_hold_single, buy_hold_equal_weight
from engine.metrics import stats, fmt
from engine.strategies import Turtle, GridMR


def single_asset(close, pos, cost, ppy):
    """Изолированный по-символьный бэктест (как OctoBot: каждый символ отдельно, long-only)."""
    T = len(close)
    eq = np.ones(T)
    p_prev = 0.0
    ntr = 0
    flips = []
    for t in range(1, T):
        c0, c1 = close[t - 1], close[t]
        r = c1 / c0 - 1 if (np.isfinite(c0) and np.isfinite(c1) and c0 > 0) else 0.0
        g = 1 + p_prev * r
        pd_ = p_prev * (1 + r) / g if (g > 0 and p_prev != 0) else p_prev
        pt = pos[t] if np.isfinite(pos[t]) else 0.0
        eq[t] = eq[t - 1] * g * (1 - abs(pt - pd_) * cost.rate)
        if abs(pt - p_prev) > 1e-9:
            ntr += 1
            flips.append(t)
        p_prev = pt
    return eq, ntr, flips


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    d = describe()
    print(f"OctoBot .data: {d['exchange']} | "
          f"{time.strftime('%Y-%m-%d', time.gmtime(float(d['start_timestamp'])))}→"
          f"{time.strftime('%Y-%m-%d', time.gmtime(float(d['end_timestamp'])))} | tf={tf}")
    p = load_octobot_panel(tf)
    print(f"panel: {p.N} монет × {p.T} баров")
    cost = CostModel()

    trend = octobot_signal_donchian(p, period=20)
    longpos = np.where(trend == -1, 1.0, 0.0)          # спот long-only = long при пробое вверх
    print("\n=== РЕПЛИКА Donchian-20 тентакла (single-channel, LONG-ONLY), по символам ===")
    eqs, total_tr, per = [], 0, []
    for j, co in enumerate(p.coins):
        eq, ntr, _ = single_asset(p.close[:, j], longpos[:, j], cost, p.ppy)
        per.append((co, stats(eq, p.ppy)["total_return"], ntr))
        eqs.append(eq)
        total_tr += ntr
    stew = stats(np.nanmean(np.array(eqs), axis=0), p.ppy)
    for co, ret, ntr in sorted(per, key=lambda x: -x[1]):
        print(f"  {co:6} ret {ret*100:+6.1f}%  сделок {ntr}")
    print(f"  ── EW-портфель реплики: {fmt(stew)} | всего сделок {total_tr}")

    # BTC: даты сигналов — чтобы глазами сверить с трейдами OctoBot
    j = p.coins.index("BTC")
    _, _, flips = single_asset(p.close[:, j], longpos[:, j], cost, p.ppy)
    dates = [time.strftime("%m-%d", time.gmtime(p.ts[t] / 1000)) for t in flips]
    print(f"  BTC флипы сигнала ({len(flips)}): {dates}")

    print("\n=== мои полные ноты на ЭТИХ ЖЕ данных (портфельные, лонг-шорт) ===")
    for label, strat in [("S4 «Черепаха»", Turtle()), ("S5 «Маятник»", GridMR())]:
        r = run_portfolio(p, strat.generate(p), cost=cost, ppy=p.ppy)
        print(f"  {label:16} {fmt(r['stats'])}")
    print(f"  BTC buy-hold     {fmt(buy_hold_single(p, 'BTC')['stats'])}")
    print(f"  EW  buy-hold     {fmt(buy_hold_equal_weight(p)['stats'])}")


if __name__ == "__main__":
    main()
