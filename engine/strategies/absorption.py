"""S12 «Абсорбция» — след информированного накопления в неликвиде.

Edge-тезис: крупный информированный покупатель в неликвидной монете НЕ может брать рынком —
он неделями поглощает предложение лимитами. Его отпечаток в OHLCV однозначен: объём РАСТЁТ,
диапазон — НЕТ, ценовое воздействие на единицу оборота (Amihud) КОЛЛАПСИРУЕТ. Мы входим на
пробое ПОСЛЕ фазы накопления, вставая на сторону того, кто уже набрал позицию.
Кто проигрывает: продавцы, которых поглотили, и поздние трендследящие.

Источник края — ПОТОК участника (не ценовой паттерн), поэтому не дублирует S8/S4: те живут
в верхнем терциле на чистом пробое, эта — в нижнем на отпечатке накопления.

Правила (стратег): Amihud_7d в нижнем дециле своего 180д-распределения; Vol_7/Vol_90 > 2;
|Δцены 7д| < 8%; ATR14/Close ниже 180д-медианы → «накопление». LONG на пробое max(high 20д)
в течение 15 дней. Стоп min(low 7д) / 2·ATR. Выход Chandelier 3·ATR, тайм-стоп 60д.
Без look-ahead: всё считается по данным < t, вход по close[t], держим (t, t+1).
"""
import numpy as np
from ..strategy import Strategy, rolling_max, rolling_min, rolling_mean, rolling_std, atr, shift


def _rolling_pctrank_last(x, w):
    """Перцентиль последнего значения окна внутри окна [t-w+1..t]. Только прошлое. [T×N]→[T×N]."""
    x = np.asarray(x, float)
    T, N = x.shape
    out = np.full((T, N), np.nan)
    for t in range(w - 1, T):
        win = x[t - w + 1:t + 1]           # включает t
        cur = win[-1]
        # доля значений окна строго меньше текущего
        with np.errstate(invalid="ignore"):
            less = np.sum(win < cur, axis=0).astype(float)
            valid = np.sum(np.isfinite(win), axis=0).astype(float)
        out[t] = np.where(valid > 1, less / (valid - 1), np.nan)
    return out


class Absorption(Strategy):
    name = "S12-absorption"

    def __init__(self, amihud_n=7, amihud_win=180, vol_short=7, vol_long=90,
                 drift_max=0.08, atr_n=14, atr_win=180, chan_n=20, arm_bars=15,
                 stop_n=7, chand_k=3.0, time_stop=60, risk=0.01, max_w=0.3, max_gross=1.0):
        self.amihud_n, self.amihud_win = amihud_n, amihud_win
        self.vol_short, self.vol_long = vol_short, vol_long
        self.drift_max = drift_max
        self.atr_n, self.atr_win = atr_n, atr_win
        self.chan_n, self.arm_bars = chan_n, arm_bars
        self.stop_n, self.chand_k, self.time_stop = stop_n, chand_k, time_stop
        self.risk, self.max_w, self.max_gross = risk, max_w, max_gross

    def generate(self, panel):
        H, L, C, V = panel.high, panel.low, panel.close, panel.volume
        T, N = C.shape
        ret = np.zeros_like(C)
        ret[1:] = C[1:] / C[:-1] - 1.0
        dvol = C * V

        # Amihud за amihud_n дней = среднее(|ret|/dollar_vol); его перцентиль в 180д окне
        illiq = np.abs(ret) / np.where(dvol > 0, dvol, np.nan)
        amihud = rolling_mean(illiq, self.amihud_n)
        amihud_rank = _rolling_pctrank_last(amihud, self.amihud_win)   # низкий → накопление

        # «объём РАСТЁТ» — отношение среднего ОБОРОТА (не волатильности доходности!).
        # Прежняя версия брала vol доходностей — это противоречило low-Amihud (цена стабильна).
        vol_s = rolling_mean(dvol, self.vol_short)
        vol_l = rolling_mean(dvol, self.vol_long)
        vol_ratio = vol_s / np.where(vol_l > 0, vol_l, np.nan)

        drift = np.abs(C / shift(C, self.vol_short) - 1.0)
        A = atr(H, L, C, self.atr_n)
        atrp = A / C
        atrp_med = rolling_mean(atrp, self.atr_win)   # прокси медианы (среднее 180д)

        # условие накопления по данным ДО текущего бара
        accum = ((shift(amihud_rank, 1) < 0.10) &
                 (shift(vol_ratio, 1) > 2.0) &
                 (shift(drift, 1) < self.drift_max) &
                 (shift(atrp, 1) < shift(atrp_med, 1)))

        chan_hi = shift(rolling_max(H, self.chan_n), 1)
        stop_lo = shift(rolling_min(L, self.stop_n), 1)
        chand = shift(rolling_max(H, self.chan_n), 1) - self.chand_k * shift(A, 1)

        W = np.zeros((T, N))
        pos = np.zeros(N)          # 0 / 1 (лонг-онли)
        armed = np.zeros(N)        # сколько баров назад взведено накопление (0 = не взведено)
        entry_bar = np.zeros(N)
        for t in range(T):
            for i in range(N):
                c = C[t, i]
                if not np.isfinite(c):
                    pos[i] = 0.0; armed[i] = 0.0; continue
                # взвод/сброс окна накопления
                if np.isfinite(accum[t, i]) and accum[t, i]:
                    armed[i] = 1.0
                elif armed[i] > 0:
                    armed[i] = armed[i] + 1.0
                    if armed[i] > self.arm_bars:
                        armed[i] = 0.0
                # выходы
                if pos[i] > 0:
                    hit_stop = np.isfinite(stop_lo[t, i]) and c < stop_lo[t, i]
                    hit_chand = np.isfinite(chand[t, i]) and c < chand[t, i]
                    hit_time = (t - entry_bar[i]) >= self.time_stop
                    if hit_stop or hit_chand or hit_time:
                        pos[i] = 0.0
                # вход: пробой в окне взведённого накопления
                if pos[i] == 0.0 and 0 < armed[i] <= self.arm_bars:
                    if np.isfinite(chan_hi[t, i]) and c > chan_hi[t, i]:
                        pos[i] = 1.0; entry_bar[i] = t; armed[i] = 0.0
                # сайзинг vol-target
                a = A[t, i]
                if pos[i] > 0 and np.isfinite(a) and a > 0:
                    unit = self.risk / (a / c)
                    W[t, i] = min(unit, self.max_w)

        gross = np.sum(np.abs(W), axis=1, keepdims=True)
        scale = np.where(gross > self.max_gross, self.max_gross / gross, 1.0)
        return W * scale
