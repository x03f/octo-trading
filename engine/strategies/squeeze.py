"""S8 «Сквиз» — прорыв после сжатия волатильности.

Edge-тезис: волатильность кластеризуется и возвращается к среднему. Период аномального СЖАТИЯ
(узкий диапазон) статистически предшествует РАСШИРЕНИЮ — и выход из узкого коридора чаще
продолжается, чем гаснет. Классика (Bollinger squeeze / NR7), но здесь с честным режим-фильтром.
Дополнительно бьёт в наш рыночный тезис-2026: сжатая волатильность → таких сетапов много.

Механика: vol(20) в нижнем квинтиле своего же распределения за last_n баров → «взведено».
Вход по выходу цены за границы коридора сжатия, стоп по ATR, выход по затуханию импульса
(vol перестала расширяться) или обратному пробою. Лонг+шорт, сайзинг vol-target.
Без look-ahead: коридор и пороги считаются по данным < t, вход по close[t], держим (t, t+1).
"""
import numpy as np
from ..strategy import (Strategy, rolling_max, rolling_min, rolling_mean,
                        rolling_std, atr, shift)


class Squeeze(Strategy):
    name = "S8-squeeze"

    def __init__(self, vol_n=20, hist_n=100, pct=0.25, chan_n=20, exit_n=10,
                 atr_n=20, risk=0.01, max_w=0.4, max_gross=1.0, allow_short=True):
        self.vol_n = vol_n          # окно расчёта волатильности
        self.hist_n = hist_n        # окно, относительно которого волатильность «низкая»
        self.pct = pct              # нижний квантиль = сжатие
        self.chan_n = chan_n        # коридор для пробоя
        self.exit_n = exit_n
        self.atr_n = atr_n
        self.risk, self.max_w, self.max_gross = risk, max_w, max_gross
        self.allow_short = allow_short

    def generate(self, panel):
        H, L, C = panel.high, panel.low, panel.close
        T, N = C.shape
        ret = np.zeros_like(C)
        ret[1:] = C[1:] / C[:-1] - 1.0
        VOL = rolling_std(ret, self.vol_n)

        # порог «сжатия»: нижний квантиль волатильности за hist_n баров (только прошлое)
        thr = np.full((T, N), np.nan)
        for t in range(self.hist_n, T):
            w = VOL[t - self.hist_n:t]
            thr[t] = np.nanquantile(w, self.pct, axis=0)
        squeezed = shift(VOL, 1) <= shift(thr, 1)      # взведено по данным ДО текущего бара

        chan_hi = shift(rolling_max(H, self.chan_n), 1)
        chan_lo = shift(rolling_min(L, self.chan_n), 1)
        exit_lo = shift(rolling_min(L, self.exit_n), 1)
        exit_hi = shift(rolling_max(H, self.exit_n), 1)
        A = atr(H, L, C, self.atr_n)

        W = np.zeros((T, N))
        pos = np.zeros(N)
        for t in range(T):
            for i in range(N):
                c = C[t, i]
                if not np.isfinite(c):
                    pos[i] = 0.0
                    continue
                p = pos[i]
                # выход по обратному короткому пробою
                if p > 0 and np.isfinite(exit_lo[t, i]) and c < exit_lo[t, i]:
                    p = 0.0
                elif p < 0 and np.isfinite(exit_hi[t, i]) and c > exit_hi[t, i]:
                    p = 0.0
                # вход: только если было сжатие И цена вышла из коридора
                if p == 0.0 and bool(squeezed[t, i]):
                    if np.isfinite(chan_hi[t, i]) and c > chan_hi[t, i]:
                        p = 1.0
                    elif self.allow_short and np.isfinite(chan_lo[t, i]) and c < chan_lo[t, i]:
                        p = -1.0
                pos[i] = p
                a = A[t, i]
                if p != 0.0 and np.isfinite(a) and a > 0:
                    W[t, i] = p * min(self.risk / (a / c), self.max_w)

        g = np.abs(W).sum(axis=1, keepdims=True)
        return W * np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
