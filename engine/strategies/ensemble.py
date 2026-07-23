"""S6 «Оркестр» — ensemble / risk-parity мета-слой («комбинированная стратегия»).

Комбинирует кривые нот S1–S5:
  • inverse-vol (risk-parity) сайзинг — вес ноги ∝ 1/vol на трейлинг-окне (никакая не доминирует риск);
  • kill-switch — нога с трейлинг-просадкой хуже порога временно отключается (вес 0);
  • target-vol скалярование всего портфеля (потолок плеча lev_cap).
Диверсификация по некоррелированным edge — единственный «бесплатный обед». Ансамбль НЕ создаёт edge
из ничего: если все ноги слабы, портфель заработает мало, просто ровнее (меньше просадка).

Без look-ahead: аллокация на период t считается ТОЛЬКО из доходностей ног строго ДО t.
"""
import numpy as np
from ..backtester import run_portfolio
from ..metrics import stats, equity_returns


class Ensemble:
    name = "S6-orchestra"

    def __init__(self, legs=None, vol_lb=60, kill_lb=60, kill_thresh=-0.12,
                 target_vol=0.15, lev_cap=1.5):
        if legs is None:
            from .fluger import Fluger
            from .turtle import Turtle
            from .gridmr import GridMR
            from .pairs import Pairs
            legs = [Fluger(), Turtle(), GridMR(), Pairs()]
        self.legs = legs
        self.vol_lb = vol_lb
        self.kill_lb = kill_lb
        self.kill_thresh = kill_thresh
        self.target_vol = target_vol
        self.lev_cap = lev_cap

    def run(self, panel, cost):
        ppy = panel.ppy
        leg_rets, leg_names, leg_stats = [], [], {}
        for leg in self.legs:
            res = run_portfolio(panel, leg.generate(panel), cost=cost, ppy=ppy)
            leg_rets.append(equity_returns(res["equity"]))
            leg_names.append(leg.name)
            leg_stats[leg.name] = res["stats"]
        R = np.vstack(leg_rets)          # [L, M]  M = T-1
        L, M = R.shape

        comb_raw = np.zeros(M)
        scaled = np.zeros(M)
        whist = np.zeros((M, L))
        tv_bar = self.target_vol / np.sqrt(ppy)

        for t in range(M):
            w = np.zeros(L)
            for l in range(L):
                hist = R[l, max(0, t - self.vol_lb):t]      # строго до t
                if len(hist) >= 10:
                    vol = np.std(hist, ddof=1)
                    kh = R[l, max(0, t - self.kill_lb):t]
                    cum = float(np.prod(1.0 + kh) - 1.0) if len(kh) else 0.0
                    if vol > 0 and cum > self.kill_thresh:   # жив, не убит просадкой
                        w[l] = 1.0 / vol
            s = w.sum()
            if s > 0:
                w = w / s
            whist[t] = w
            comb_raw[t] = float(np.dot(w, R[:, t]))
            past = comb_raw[max(0, t - self.vol_lb):t]
            scal = 1.0
            if len(past) >= 10:
                sd = np.std(past, ddof=1)
                if sd > 0:
                    scal = min(self.lev_cap, tv_bar / sd)
            scaled[t] = scal * comb_raw[t]

        equity = np.concatenate([[1.0], np.cumprod(1.0 + scaled)])
        st = stats(equity, ppy)
        st["avg_alive_legs"] = float((whist > 0).sum(axis=1).mean())
        return {"equity": equity, "stats": st, "leg_names": leg_names,
                "leg_stats": leg_stats, "weights": whist}
