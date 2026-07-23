"""Онлайн-сигнал S11 «Новичок» — ОДНА логика для backtest и paper/live.

Пер-монетное решение: по дневным high/low/close ОДНОЙ монеты + индексу листинга + доступности
шорта возвращает целевую позицию (0 или -1). Полностью эквивалентно engine/strategies/newlisting.py
(проверяется тестом parity), но пригодно для потоковой (онлайн) работы, где данные приходят по монете.

Правила (те же, что в бэктесте): H0 = max первых listing_hi_days; окно входа день start..end;
SHORT если close < min(low последних confirm_n) И H0 не обновлён после дня +1 И перп доступен.
Выход: стоп выше max(high stop_hi_n) / +atr_k·ATR; трейл выше max(high trail_n); таргет; тайм-стоп.
Без look-ahead: решение на баре t использует данные ≤ t.
"""
import numpy as np


class S11Params:
    def __init__(self, listing_hi_days=3, start_day=3, end_day=20, confirm_n=3,
                 stop_hi_n=5, atr_n=14, atr_k=2.5, trail_n=20, target=-0.35, time_stop=30):
        self.listing_hi_days = listing_hi_days
        self.start_day, self.end_day = start_day, end_day
        self.confirm_n = confirm_n
        self.stop_hi_n, self.atr_n, self.atr_k = stop_hi_n, atr_n, atr_k
        self.trail_n, self.target, self.time_stop = trail_n, target, time_stop


def _atr(h, l, c, n):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    for t in range(n, len(c)):
        out[t] = np.mean(tr[t - n:t])
    return out


def s11_run(highs, lows, closes, first_idx=0, shortable_from_idx=0, params=None):
    """Прогон S11 по истории одной монеты. Возвращает (target_position, state) на ПОСЛЕДНЕМ баре,
    плюс полный список позиций по барам (для parity-теста). first_idx — бар листинга внутри массива."""
    p = params or S11Params()
    H, L, C = np.asarray(highs, float), np.asarray(lows, float), np.asarray(closes, float)
    T = len(C)
    A = _atr(H, L, C, p.atr_n)
    f = first_idx
    hi_win = H[f:f + p.listing_hi_days]
    positions = np.zeros(T)
    if not np.isfinite(hi_win).any() or T <= f + p.start_day:
        return 0.0, {"reason": "мало данных"}, positions
    H0 = np.nanmax(hi_win)
    broke_H0 = False
    pos = 0.0
    entry_bar = -1
    for t in range(f + 1, T):
        c = C[t]
        if not np.isfinite(c):
            pos = 0.0; positions[t] = pos; continue
        age = t - f
        if np.isfinite(H[t]) and H[t] > H0 and age > 1:
            broke_H0 = True
        # выходы
        if pos < 0:
            stop_hi = np.nanmax(H[max(f, t - p.stop_hi_n):t]) if t > f else np.nan
            hit_stop = ((np.isfinite(stop_hi) and c > stop_hi) or
                        (np.isfinite(A[entry_bar]) and c > C[entry_bar] + p.atr_k * A[entry_bar]))
            trail_hi = np.nanmax(H[max(f, t - p.trail_n):t]) if t > f else np.nan
            hit_trail = np.isfinite(trail_hi) and c > trail_hi
            hit_target = c <= C[entry_bar] * (1 + p.target)
            hit_time = (t - entry_bar) >= p.time_stop
            if hit_stop or hit_trail or hit_target or hit_time:
                pos = 0.0
        # вход
        shortable = t >= shortable_from_idx
        if pos == 0.0 and p.start_day <= age <= p.end_day and not broke_H0 and shortable:
            lo_win = L[max(f + 1, t - p.confirm_n):t]
            if lo_win.size and np.isfinite(lo_win).any():
                trig = np.nanmin(lo_win)
                if np.isfinite(trig) and c < trig:
                    pos = -1.0; entry_bar = t
        positions[t] = pos
    return pos, {"H0": float(H0), "broke_H0": broke_H0, "entry_bar": int(entry_bar), "age": int(T - 1 - f)}, positions
