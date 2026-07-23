"""Честная валидация портфеля: IS/OOS holdout + чувствительность + walk-forward.
Запуск: python run_validate.py [tf]"""
import sys, warnings, time
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import load_panel, list_universe, CostModel
from engine.strategies import Turtle, GridMR, Pairs, Fluger, Ensemble
from engine.validate import holdout, sensitivity, walk_forward, _stats_from_returns


def pct(x):
    return f"{x*100:+6.1f}%" if np.isfinite(x) else "   n/a"


def f2(x):
    return f"{x:+5.2f}" if np.isfinite(x) else "  n/a"


def verdict(sh):
    if not np.isfinite(sh):
        return "н/д"
    return "держится" if sh > 0.3 else ("слабо+" if sh > 0 else "РАЗВАЛ")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    p = load_panel(list_universe(tf), tf)
    cost = CostModel()
    span = (time.strftime("%Y-%m-%d", time.gmtime(p.ts[0] / 1000)),
            time.strftime("%Y-%m-%d", time.gmtime(p.ts[-1] / 1000)))
    print(f"== ВАЛИДАЦИЯ | {p.N} монет | {span[0]}→{span[1]} ({p.T} баров) | IS=первые 60%, OOS=хвост 40% ==")

    print("\n=== 1) IS/OOS HOLDOUT — держится ли edge на невиданном хвосте ===")
    print(f"{'нота':15} {'IS ret':>8} {'IS Shp':>7} | {'OOS ret':>8} {'OOS Shp':>7} {'OOS maxDD':>9}  вердикт")
    for label, strat in [("S1 «Флюгер»", Fluger()), ("S4 «Черепаха»", Turtle()),
                         ("S5 «Маятник»", GridMR()), ("S3 «Спред»", Pairs())]:
        h = holdout(p, strat, cost, is_frac=0.6)
        print(f"{label:15} {pct(h['IS']['total_return'])} {f2(h['IS']['sharpe'])} | "
              f"{pct(h['OOS']['total_return'])} {f2(h['OOS']['sharpe'])} {pct(h['OOS']['max_dd'])}  {verdict(h['OOS']['sharpe'])}")
    ens = Ensemble().run(p, cost)
    rr = np.asarray(ens["equity"]); rr = rr[1:] / rr[:-1] - 1
    k = int(len(rr) * 0.6)
    eis, eoos = _stats_from_returns(rr[:k], p.ppy), _stats_from_returns(rr[k:], p.ppy)
    print(f"{'S6 «Оркестр»':15} {pct(eis['total_return'])} {f2(eis['sharpe'])} | "
          f"{pct(eoos['total_return'])} {f2(eoos['sharpe'])} {pct(eoos['max_dd'])}  {verdict(eoos['sharpe'])}")

    print("\n=== 2) ЧУВСТВИТЕЛЬНОСТЬ (Sharpe по сетке) — ПЛАТО=робастно, ПИК=удача ===")
    print("S5 «Маятник» — z_entry × adx_max:")
    ax = [15, 20, 25]
    print("        adx_max→ " + " ".join(f"{a:>7}" for a in ax))
    for z in [1.5, 2.0, 2.5, 3.0]:
        row = [sensitivity(p, lambda pr: GridMR(z_entry=pr["z"], adx_max=pr["a"]),
                           [{"z": z, "a": a}], cost)[0][1] for a in ax]
        print(f"  z={z:<4}   " + " ".join(f"{v:+7.2f}" for v in row))
    print("S4 «Черепаха» — entry_n × adx_min (0=фильтр off):")
    ams = [0, 20, 25]
    print("        adx_min→ " + " ".join(f"{a:>7}" for a in ams))
    for e in [10, 20, 30, 55]:
        row = [sensitivity(p, lambda pr: Turtle(entry_n=pr["e"], adx_min=pr["a"], use_adx=(pr["a"] > 0)),
                           [{"e": e, "a": a}], cost)[0][1] for a in ams]
        print(f"  n={e:<4}   " + " ".join(f"{v:+7.2f}" for v in row))

    print("\n=== 3) WALK-FORWARD S5 (ре-оптимизация z×adx на train → тест на OOS) ===")
    grid = [{"z": z, "a": a} for z in [1.5, 2.0, 2.5, 3.0] for a in [15, 20, 25]]
    wf = walk_forward(p, lambda pr: GridMR(z_entry=pr["z"], adx_max=pr["a"]),
                      grid, cost, n_folds=4, train_frac=0.5)
    for fo in wf["folds"]:
        print(f"  fold [{fo['test'][0]}:{fo['test'][1]}] → выбран z={fo['best_params']['z']} "
              f"adx={fo['best_params']['a']} (train Sharpe {fo['train_sharpe']})")
    print(f"  ⇒ OOS walk-forward: {pct(wf['oos']['total_return'])} | Sharpe {f2(wf['oos']['sharpe'])} | "
          f"maxDD {pct(wf['oos']['max_dd'])} | {verdict(wf['oos']['sharpe'])}")


if __name__ == "__main__":
    main()
