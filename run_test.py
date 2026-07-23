"""Честный трёхчастный тест: train → valid (отбор победителя) → test (один замер, не для отбора).

ЗАЧЕМ: старый run_full.py отбирал победителя по OOS-Sharpe → OOS стал валидацией, честного
теста не осталось. Здесь TEST-срез НЕ участвует в выборе: победитель выбирается по VALID,
его число на TEST — единственная непредвзятая оценка вне выборки.

Плюс два урока Шага 0:
  · вселенная = ВЕРХНИЙ терциль ликвидности (только там пробойный край существует);
  · косты честные (плоские 15 bps оправданы, т.к. верхний терциль упирается в пол спреда).

Запуск: python run_test.py [tf]
"""
import sys, json, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import load_panel, list_universe, CostModel, run_portfolio
from engine.strategies import Squeeze, Turtle, GridMR, Fluger
from engine.validate import slice_panel, _stats_from_returns
from engine.metrics import equity_returns
from engine.liquidity import passport, terciles


def seg_stats(panel, strat, cost, a, b):
    """Метрики стратегии на срезе [a,b) — прогон на ПОЛНОЙ панели, метрики на куске кривой.
    (Прогон на полной панели сохраняет warmup индикаторов; look-ahead нет — веса из данных ≤ t.)"""
    res = run_portfolio(panel, strat.generate(panel), cost=cost, ppy=panel.ppy)
    r = equity_returns(res["equity"])
    return _stats_from_returns(r[a:b], panel.ppy)


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    t0 = time.time()
    # верхний терциль ликвидности — где край вообще есть (Шаг 0)
    pp = passport(list_universe(tf))
    top, _, _ = terciles(pp)
    p = load_panel(top, tf)
    cost = CostModel()
    T = p.T
    a_tr, a_va, a_te = 0, int(T * 0.50), int(T * 0.75)   # 50/25/25
    span = lambda i: time.strftime("%Y-%m-%d", time.gmtime(p.ts[i] / 1000))
    print(f"╔═══ ЧЕСТНЫЙ ТРЁХЧАСТНЫЙ ТЕСТ | tf={tf} | верхний терциль {p.N} монет ═══")
    print(f"║ TRAIN {span(a_tr)}→{span(a_va)} | VALID {span(a_va)}→{span(a_te)} | "
          f"TEST {span(a_te)}→{span(T-1)}  (50/25/25)")
    print("║ TEST не участвует в отборе — победитель выбирается по VALID")

    strategies = [("S8 «Сквиз»", Squeeze()), ("S4 «Черепаха»", Turtle()),
                  ("S5 «Маятник»", GridMR()), ("S1 «Флюгер»", Fluger())]
    rows = []
    print(f"║ {'стратегия':16} {'TRAIN Sh':>9} {'VALID Sh':>9} {'TEST Sh':>9} {'TEST ret':>9}")
    for label, strat in strategies:
        tr = seg_stats(p, strat, cost, a_tr, a_va)
        va = seg_stats(p, strat, cost, a_va, a_te)
        te = seg_stats(p, strat, cost, a_te, T)
        rows.append((label, tr, va, te))
        print(f"║ {label:16} {tr['sharpe']:+9.2f} {va['sharpe']:+9.2f} "
              f"{te['sharpe']:+9.2f} {te['total_return']*100:+8.0f}%")

    # отбор ТОЛЬКО по VALID, TEST читаем один раз как непредвзятую оценку
    winner = max(rows, key=lambda r: r[1]['sharpe'] if np.isfinite(r[1]['sharpe']) else -99)
    wl, _, wv, wt = winner[0], winner[1], winner[2], winner[3]
    print("╠═══ ВЕРДИКТ ═══")
    print(f"║ Победитель по VALID: {wl} (VALID Sharpe {wv['sharpe']:+.2f})")
    print(f"║ Его ЧЕСТНАЯ оценка вне выборки — TEST Sharpe {wt['sharpe']:+.2f}, "
          f"ret {wt['total_return']*100:+.0f}%, DD {wt['max_dd']*100:+.0f}%")
    if wt['sharpe'] < 0.3:
        print("║ ⚠️ TEST Sharpe < 0.3 — на честном тесте края НЕТ. Прошлые OOS-числа были оптимистичны.")
    print(f"╚═══ готово за {time.time()-t0:.0f}s ═══")

    json.dump({"tf": tf, "universe": "top_tercile", "n": p.N,
               "splits": {"train": [span(a_tr), span(a_va)], "valid": [span(a_va), span(a_te)],
                          "test": [span(a_te), span(T-1)]},
               "rows": [{"strategy": l, "train": tr, "valid": va, "test": te}
                        for l, tr, va, te in rows],
               "winner": wl},
              open("/opt/octobot/strategy-lab/results/three_set_test.json", "w"),
              default=lambda x: None)


if __name__ == "__main__":
    main()
