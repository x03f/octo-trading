"""Свести весь портфель: ноты S1/S3/S4/S5 + бенчмарки + S6 «Оркестр» + S2 carry (синтетика).
Запуск: python run_all.py [tf]"""
import sys, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import (load_panel, list_universe, buy_hold_single,
                    buy_hold_equal_weight, CostModel, run_portfolio)
from engine.strategies import Turtle, GridMR, Pairs, Fluger, Carry, Ensemble


def row(label, st, extra=""):
    def p(x):
        return f"{x*100:+6.1f}%" if np.isfinite(x) else "   n/a"
    def f(x):
        return f"{x:+5.2f}" if np.isfinite(x) else "  n/a"
    return (f"{label:22} ret {p(st['total_return'])} CAGR {p(st['cagr'])} "
            f"vol {p(st['vol_ann'])} Sharpe {f(st['sharpe'])} "
            f"maxDD {p(st['max_dd'])} Calmar {f(st['calmar'])} {extra}")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    p = load_panel(list_universe(tf), tf)
    cost = CostModel()
    span = (time.strftime("%Y-%m-%d", time.gmtime(p.ts[0] / 1000)),
            time.strftime("%Y-%m-%d", time.gmtime(p.ts[-1] / 1000)))
    print(f"╔═══ ПОРТФЕЛЬ strategy-lab | tf={tf} | {p.N} монет | {span[0]}→{span[1]} ({p.T} баров) ═══")
    print("║ косты: Gate taker 6bps + slippage 5bps | без look-ahead | in-sample (нужен OOS/walk-forward)")
    print("╠═══ НОТЫ (ценовой движок на спот-данных) ═══")
    notes = [("S1 «Флюгер»", Fluger()), ("S4 «Черепаха»", Turtle()),
             ("S5 «Маятник»", GridMR()), ("S3 «Спред»", Pairs())]
    for label, strat in notes:
        res = run_portfolio(p, strat.generate(p), cost=cost, ppy=p.ppy)
        st = res["stats"]
        print("║ " + row(label, st, f"gross {st['avg_gross_exposure']:.2f} net {st['avg_net_exposure']:+.2f}"))

    print("╠═══ БЕНЧМАРКИ ═══")
    print("║ " + row("BTC buy-hold", buy_hold_single(p, "BTC")["stats"]))
    print("║ " + row("EW buy-hold", buy_hold_equal_weight(p)["stats"]))

    print("╠═══ S6 «ОРКЕСТР» (ансамбль S1+S4+S5+S3, risk-parity+kill-switch) ═══")
    ens = Ensemble().run(p, cost)
    print("║ " + row("S6 «Оркестр»", ens["stats"], f"живых ног {ens['stats']['avg_alive_legs']:.1f}/4"))

    print("╠═══ S2 «Базис» carry — СИНТЕТИЧЕСКИЙ funding (логика, не реальные данные!) ═══")
    for reg in ("positive", "compressed", "mixed"):
        f = Carry.synthetic_funding(p, reg)
        c = Carry().run(f, ppy=p.ppy)
        print("║ " + row(f"S2 carry [{reg}]", c["stats"]))
    print("╚═══ (S2 требует реальный funding — задача #9) ═══")


if __name__ == "__main__":
    main()
