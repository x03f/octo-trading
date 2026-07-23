"""Шаг 0: паспорт ликвидности + пер-монетные косты + терцильный тест пробойного края.

Ключевой вопрос стратега: живёт ли край S8/S4 только в ВЕРХНИХ терцилях ликвидности,
а нижний съеден костами? Если да — это меняет карту: нишевый эксперимент имеет смысл лишь
там, где спред не убивает пробой.

Запуск: python run_liquidity.py [tf]   (по умолчанию 1d)
"""
import sys, time, json, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import load_panel, list_universe, CostModel, run_portfolio
from engine.strategies import Squeeze, Turtle
from engine.liquidity import passport, terciles, cost_model


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    coins = list_universe(tf)
    t0 = time.time()
    print(f"╔═══ ШАГ 0: паспорт ликвидности | {len(coins)} монет | tf={tf} ═══", flush=True)

    pp = passport(coins)
    cm = cost_model(pp)
    print(f"║ паспорт построен за {time.time()-t0:.0f}s", flush=True)

    # --- 1. насколько плоский кост занижает реальность ---
    rt = np.array([r["rt_cost_bps"] for r in pp.values() if r.get("rt_cost_bps")], float)
    print("╠═══ ПЕР-МОНЕТНАЯ СТОИМОСТЬ КРУГА (bps) vs плоские 15 ═══")
    for q, lbl in [(10, "p10"), (50, "медиана"), (75, "p75"), (90, "p90"), (100, "макс")]:
        print(f"║   {lbl:8} {np.percentile(rt, q):6.1f} bps")
    print(f"║   доля монет дороже 30 bps (2× плоского): {(rt > 30).mean()*100:.0f}%")

    # --- 2. терцили по ликвидности ---
    top, mid, bot = terciles(pp)
    def band(name, cs):
        dv = np.array([pp[c]["med_dv"] for c in cs], float)
        rtb = np.array([cm[c] for c in cs], float)
        print(f"║ {name:8} n={len(cs):3}  оборот ${np.median(dv)/1e6:6.1f}M(мед)  "
              f"кост {np.median(rtb):5.1f}bps(мед)")
    print("╠═══ ТЕРЦИЛИ ПО ОБОРОТУ ═══")
    band("ВЕРХНИЙ", top); band("СРЕДНИЙ", mid); band("НИЖНИЙ", bot)

    # --- 3. пробойный край по терцилям (одинаковый плоский кост, чтобы изолировать эффект) ---
    cost = CostModel()   # Gate taker 6+5 bps
    print("╠═══ ПРОБОЙНЫЙ КРАЙ ПО ТЕРЦИЛЯМ (Sharpe, плоский кост — изолируем ликвидность) ═══")
    print(f"║ {'терциль':8} {'S8 Сквиз':>18} {'S4 Черепаха':>18}")
    band_results = {}
    for name, cs in [("ВЕРХНИЙ", top), ("СРЕДНИЙ", mid), ("НИЖНИЙ", bot)]:
        p = load_panel(cs, tf)
        out = {}
        for lbl, strat in [("S8", Squeeze()), ("S4", Turtle())]:
            res = run_portfolio(p, strat.generate(p), cost=cost, ppy=p.ppy)
            out[lbl] = res["stats"]
        band_results[name] = out
        def s(x): return f"{x['sharpe']:+.2f} ({x['total_return']*100:+.0f}%)"
        print(f"║ {name:8} {s(out['S8']):>18} {s(out['S4']):>18}")

    print(f"╚═══ готово за {time.time()-t0:.0f}s ═══")

    # сохраняем паспорт и косты для дальнейших бэктестов
    out = {"tf": tf, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "passport": pp, "cost_model": cm,
           "terciles": {"top": top, "mid": mid, "bot": bot},
           "tercile_edge": {k: {kk: {m: vv[m] for m in ("sharpe", "total_return", "max_dd")}
                                for kk, vv in v.items()} for k, v in band_results.items()}}
    path = "/opt/octobot/strategy-lab/results/liquidity_passport.json"
    json.dump(out, open(path, "w"), default=lambda x: None)
    print(f"паспорт сохранён: {path}")


if __name__ == "__main__":
    main()
