"""ПОЛНЫЙ ПРОГОН: все ноты + новые кандидаты на полном озере, отбор ТОЛЬКО по OOS.

Отбираем не по красоте in-sample (мы уже знаем, чем это кончается — S5), а по хвосту,
который стратегия не видела. Запуск: python run_full.py [tf]
"""
import sys, time, json, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore")
import numpy as np
from engine import load_panel, list_universe, CostModel, run_portfolio, buy_hold_single, buy_hold_equal_weight
from engine.strategies import Turtle, GridMR, Pairs, Fluger, Squeeze, Rotation, Ensemble
from engine.validate import holdout, _stats_from_returns
from engine.metrics import equity_returns

RESULTS = "/opt/octobot/strategy-lab/results"


def pct(x):
    return f"{x*100:+7.1f}%" if np.isfinite(x) else "    n/a"


def f2(x):
    return f"{x:+6.2f}" if np.isfinite(x) else "   n/a"


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    t0 = time.time()
    p = load_panel(list_universe(tf), tf)
    cost = CostModel()
    span = (time.strftime("%Y-%m-%d", time.gmtime(p.ts[0] / 1000)),
            time.strftime("%Y-%m-%d", time.gmtime(p.ts[-1] / 1000)))
    print(f"== ПОЛНЫЙ ПРОГОН | {p.N} монет | {span[0]}→{span[1]} ({p.T} баров, {tf}) ==", flush=True)
    print("   отбор по OOS (хвост 40%), IS=первые 60%. Косты Gate включены.\n", flush=True)

    cands = [
        ("S4 «Черепаха»-20", Turtle()),
        ("S4 «Черепаха»-55", Turtle(entry_n=55, exit_n=20)),   # робастная находка сетки
        ("S1 «Флюгер»", Fluger()),
        ("S5 «Маятник»", GridMR()),
        ("S3 «Спред»", Pairs()),
        ("S8 «Сквиз»", Squeeze()),
        ("S9 «Ротация»", Rotation()),
    ]
    rows = []
    for label, strat in cands:
        t1 = time.time()
        h = holdout(p, strat, cost, is_frac=0.6)
        rows.append((label, h))
        print(f"  {label:20} IS {pct(h['IS']['total_return'])} {f2(h['IS']['sharpe'])} | "
              f"OOS {pct(h['OOS']['total_return'])} {f2(h['OOS']['sharpe'])} "
              f"DD {pct(h['OOS']['max_dd'])}  ({time.time()-t1:.0f}с)", flush=True)

    # ансамбль из тех, что вообще торгуют
    print("\n  --- ансамбль S6 «Оркестр» (все ноты) ---", flush=True)
    ens = Ensemble(legs=[Fluger(), Turtle(entry_n=55, exit_n=20), GridMR(), Squeeze()]).run(p, cost)
    rr = np.asarray(ens["equity"]); rr = rr[1:] / rr[:-1] - 1
    k = int(len(rr) * 0.6)
    eis, eoos = _stats_from_returns(rr[:k], p.ppy), _stats_from_returns(rr[k:], p.ppy)
    rows.append(("S6 «Оркестр»", {"IS": eis, "OOS": eoos}))
    print(f"  {'S6 «Оркестр»':20} IS {pct(eis['total_return'])} {f2(eis['sharpe'])} | "
          f"OOS {pct(eoos['total_return'])} {f2(eoos['sharpe'])} DD {pct(eoos['max_dd'])}", flush=True)

    print(f"\n  бенчмарки: BTC {pct(buy_hold_single(p,'BTC')['stats']['total_return'])} | "
          f"EW-корзина {pct(buy_hold_equal_weight(p)['stats']['total_return'])}", flush=True)

    print("\n=== ИТОГ: сортировка по OOS Sharpe (что реально отбираем) ===")
    rows.sort(key=lambda r: (r[1]["OOS"]["sharpe"] if np.isfinite(r[1]["OOS"]["sharpe"]) else -99), reverse=True)
    for label, h in rows:
        sh = h["OOS"]["sharpe"]
        mark = "✅ БЕРЁМ" if np.isfinite(sh) and sh > 0.3 else ("⚠️ слабо" if np.isfinite(sh) and sh > 0 else "❌ мимо")
        print(f"  {label:20} OOS Sharpe {f2(sh)}  DD {pct(h['OOS']['max_dd'])}  {mark}")

    json.dump({l: {"IS": h["IS"], "OOS": h["OOS"]} for l, h in rows},
              open(f"{RESULTS}/full_{tf}.json", "w"), indent=1, default=float)
    print(f"\n  готово за {time.time()-t0:.0f}с → results/full_{tf}.json")


if __name__ == "__main__":
    main()
