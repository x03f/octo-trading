"""S5 «Маятник» — regime-gated mean-reversion (ФИКС провала обычных сеток −46%).

Провал сеток был в том, что они докупали нож в СИЛЬНОМ ДАУНТРЕНДЕ. Здесь mean-reversion
работает ТОЛЬКО в боковике (ADX < adx_max) — а сильный тренд (в любую сторону) даёт высокий ADX
и полностью выключает вход. Это прямое лечение: в режиме, где сетка разоряется, нас просто нет.

Механика: z = (close − MA)/std. Вход LONG при z<−z_entry (перепродано), SHORT при z>+z_entry;
выход у среднего (|z|<z_exit); хард-стоп при |z|>z_stop или уходе из боковика (ADX вырос).
Флаг use_gate=False отключает режим-фильтр — чтобы ПОКАЗАТЬ, что именно gate спасает от ножа.
Без look-ahead: MA/std/ADX по данным ≤ t, вес держится (t, t+1).
"""
import numpy as np
from ..strategy import Strategy, rolling_mean, rolling_std, adx


class GridMR(Strategy):
    name = "S5-mayatnik"

    def __init__(self, ma_n=20, z_entry=2.0, z_exit=0.4, z_stop=3.5,
                 adx_max=20.0, risk=0.01, max_w=0.4, max_gross=1.0,
                 use_gate=True, allow_short=True):
        self.ma_n = ma_n
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.z_stop = z_stop
        self.adx_max = adx_max
        self.risk = risk
        self.max_w = max_w
        self.max_gross = max_gross
        self.use_gate = use_gate
        self.allow_short = allow_short

    def generate(self, panel):
        H, L, C = panel.high, panel.low, panel.close
        T, N = C.shape
        MA = rolling_mean(C, self.ma_n)
        SD = rolling_std(C, self.ma_n)
        with np.errstate(divide="ignore", invalid="ignore"):
            Z = (C - MA) / SD
        AD = adx(H, L, C, 14)
        # прокси-волатильность для сайзинга: std доходностей окна
        ret = np.zeros_like(C)
        ret[1:] = C[1:] / C[:-1] - 1.0
        VOL = rolling_std(ret, self.ma_n)

        W = np.zeros((T, N))
        pos = np.zeros(N)

        for t in range(T):
            for i in range(N):
                c = C[t, i]
                if not np.isfinite(c):
                    pos[i] = 0.0
                    continue
                z = Z[t, i]
                a = AD[t, i]
                range_ok = (not self.use_gate) or (np.isfinite(a) and a < self.adx_max)
                p = pos[i]
                # выходы: достигли среднего
                if p > 0 and np.isfinite(z) and z >= -self.z_exit:
                    p = 0.0
                elif p < 0 and np.isfinite(z) and z <= self.z_exit:
                    p = 0.0
                # хард-стоп: тренд вернулся (вышли из боковика) или z разнесло
                if p != 0.0 and (not range_ok or (np.isfinite(z) and abs(z) > self.z_stop)):
                    p = 0.0
                # входы — только в боковике
                if p == 0.0 and range_ok and np.isfinite(z):
                    if z < -self.z_entry:
                        p = 1.0
                    elif self.allow_short and z > self.z_entry:
                        p = -1.0
                pos[i] = p
                # сайзинг vol-target
                v = VOL[t, i]
                if p != 0.0 and np.isfinite(v) and v > 0:
                    W[t, i] = p * min(self.risk / v, self.max_w)

        g = np.abs(W).sum(axis=1, keepdims=True)
        scale = np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
        return W * scale
