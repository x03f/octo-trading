"""Чистый трёхчастный тест НОВЫХ стратегий (S11 «Новичок», S12 «Абсорбция») на ИХ вселенных,
с ПЕР-МОНЕТНЫМ костом (Шаг 0). Порог похорон объявлен ДО прогона.

S12 «Абсорбция» — нижний+средний терциль (там виден отпечаток накопления). Кост честный (высокий).
S11 «Новичок» — вся вселенная, стратегия сама фильтрует реальные листинги; шорт-онли.

Порог (стратег): TEST Sharpe > 0.3 на срезе, не участвовавшем в отборе. Иначе — мертва.
Запуск: python run_test_new.py [tf]
"""
import sys, json, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore", category=RuntimeWarning)
import numpy as np
from engine import load_panel, list_universe, run_portfolio
from engine.strategies import Absorption, NewListing, Squeeze, Turtle
from engine.validate import _stats_from_returns
from engine.metrics import equity_returns
from engine.liquidity import passport, terciles, cost_model


def three_split(p, strat, cvec):
    res = run_portfolio(p, strat.generate(p), cost_vec=cvec, ppy=p.ppy)
    r = equity_returns(res["equity"])
    T = len(r); a, b = int(T * 0.50), int(T * 0.75)
    return (_stats_from_returns(r[:a], p.ppy),
            _stats_from_returns(r[a:b], p.ppy),
            _stats_from_returns(r[b:], p.ppy), res["stats"])


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    t0 = time.time()
    coins = list_universe(tf)
    pp = passport(coins)
    cm = cost_model(pp)                       # {coin: rt_cost доля}
    top, mid, bot = terciles(pp)
    print(f"╔═══ ЧИСТЫЙ ТЕСТ НОВЫХ СТРАТЕГИЙ | tf={tf} | пер-монетный кост ═══", flush=True)
    print(f"║ паспорт за {time.time()-t0:.0f}s | порог похорон: TEST Sharpe > 0.30\n║")

    def run_on(label, strat, universe, tag):
        u = [c for c in universe if c in cm]
        p = load_panel(u, tf)
        cvec = np.array([cm[c] / 1e4 if cm[c] > 1 else cm[c] for c in p.coins])  # bps→доля
        # cost_model отдаёт bps; переводим в долю (÷1e4). Значения уже в bps (15..360).
        cvec = np.array([cm[c] / 1e4 for c in p.coins])
        tr, va, te, full = three_split(p, strat, cvec)
        verdict = "ЖИВА" if (np.isfinite(te["sharpe"]) and te["sharpe"] > 0.30) else "мертва"
        print(f"║ {label:16} [{tag}, {p.N} монет]", flush=True)
        print(f"║   TRAIN Sh {tr['sharpe']:+.2f} | VALID Sh {va['sharpe']:+.2f} | "
              f"TEST Sh {te['sharpe']:+.2f} ret {te['total_return']*100:+.0f}% → {verdict}\n║", flush=True)
        return {"strategy": label, "universe": tag, "n": p.N,
                "train": tr, "valid": va, "test": te, "verdict": verdict}

    rows = []
    rows.append(run_on("S12 «Абсорбция»", Absorption(), mid + bot, "неликвид mid+bot"))
    rows.append(run_on("S11 «Новичок»", NewListing(), coins, "вся вселенная, шорт листингов"))
    # контроль: S8/S4 на неликвиде — должны быть плохи (сверка, что кост честный)
    rows.append(run_on("S8 контроль", Squeeze(), mid + bot, "неликвид (контроль)"))

    print("╚═══ готово за {:.0f}s ═══".format(time.time() - t0))
    json.dump({"tf": tf, "rows": rows},
              open("/opt/octobot/strategy-lab/results/new_strategies_test.json", "w"),
              default=lambda x: None)


if __name__ == "__main__":
    main()
