"""Прогон стратегии-ноты по озеру. Честные метрики + независимые бенчмарки.

Запуск: python run.py <name> [tf]      напр.  python run.py turtle 1d
Сохраняет кривую эквити в results/<name>_<tf>.equity.npy и метрики в results/<name>_<tf>.json
"""
import sys, os, json, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import (load_panel, list_universe, buy_hold_single,
                    buy_hold_equal_weight, CostModel, run_portfolio)
from engine.metrics import fmt
from engine.strategies import REGISTRY

RESULTS = "/opt/octobot/strategy-lab/results"


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in REGISTRY:
        print("варианты:", ", ".join(sorted(REGISTRY)))
        return
    name = sys.argv[1]
    tf = sys.argv[2] if len(sys.argv) > 2 else "1d"
    os.makedirs(RESULTS, exist_ok=True)

    coins = list_universe(tf)
    p = load_panel(coins, tf)
    span = (time.strftime("%Y-%m-%d", time.gmtime(p.ts[0] / 1000)),
            time.strftime("%Y-%m-%d", time.gmtime(p.ts[-1] / 1000)))
    print(f"== {name} | tf={tf} | {p.N} монет | {span[0]}→{span[1]} ({p.T} баров) ==")

    strat = REGISTRY[name]()
    W = strat.generate(p)
    res = run_portfolio(p, W, cost=CostModel(), ppy=p.ppy)
    st = res["stats"]
    print(f"[{strat.name:12}] {fmt(st)}")
    print(f"              turnover/бар {st['avg_turnover']:.3f} | "
          f"gross {st['avg_gross_exposure']:.2f} | net {st['avg_net_exposure']:+.2f}")
    # бенчмарки
    print(f"[BTC buy-hold ] {fmt(buy_hold_single(p, 'BTC')['stats'])}")
    print(f"[EW  buy-hold ] {fmt(buy_hold_equal_weight(p)['stats'])}")

    np.save(f"{RESULTS}/{name}_{tf}.equity.npy", res["equity"])
    json.dump({"name": strat.name, "tf": tf, "span": span, "stats": st},
              open(f"{RESULTS}/{name}_{tf}.json", "w"), indent=1)
    print(f"→ results/{name}_{tf}.json")


if __name__ == "__main__":
    main()
