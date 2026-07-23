"""S11 «Новичок» — шорт распада внимания после листинга.

Edge-тезис: на листинге сталкиваются два потока с разными мандатами. Продавцы —
структурные и принудительные (команда/фонды/эйрдроп-фермеры, себестоимость ≈0, обязаны
распределять объём неделями). Покупатели — розница за «новой монетой», листинг-боты, FOMO;
их топливо — ВНИМАНИЕ, а оно затухает за дни. Мы встаём на сторону структурного продавца.
Кто проигрывает: поздняя FOMO-розница.

Единственная ШОРТ-идея в лонговом портфеле → отрицательная корреляция с текущим P&L.
Survivorship работает В НАШУ ПОЛЬЗУ: обнулившиеся дампы вырезаны → бэктест ЗАНИЖАЕТ шорт-профит.

Правила (стратег): вселенная — токены, чей первый бар в озере ПОЗЖЕ старта озера (реальный
листинг, а не обрезка). H0 = максимум первых listing_hi_days дней. Окно торговли день +3…+20.
SHORT на закрытии ниже min(low дней +1..+3), если после дня +1 цена не обновляла H0.
Стоп выше max(high 5 дней) / +2.5·ATR. Выход трейл 20-барный max / тайм-стоп / таргет.
Без look-ahead: всё по данным ≤ t. Работает на 1d-панели, «возраст» считается от первого
валидного бара КАЖДОЙ монеты внутри панели.
"""
import numpy as np
from ..strategy import Strategy, rolling_max, rolling_min, atr, shift


class NewListing(Strategy):
    name = "S11-newlisting"

    def __init__(self, listing_hi_days=3, start_day=3, end_day=20, confirm_n=3,
                 stop_hi_n=5, atr_n=14, atr_k=2.5, trail_n=20, target=-0.35,
                 time_stop=30, risk=0.005, max_w=0.2, max_gross=1.0,
                 min_age_from_lake=30):
        self.listing_hi_days = listing_hi_days
        self.start_day, self.end_day = start_day, end_day
        self.confirm_n = confirm_n
        self.stop_hi_n, self.atr_n, self.atr_k = stop_hi_n, atr_n, atr_k
        self.trail_n, self.target, self.time_stop = trail_n, target, time_stop
        self.risk, self.max_w, self.max_gross = risk, max_w, max_gross
        self.min_age_from_lake = min_age_from_lake   # чтобы взять только реальные листинги

    def generate(self, panel):
        H, L, C = panel.high, panel.low, panel.close
        T, N = C.shape
        A = atr(H, L, C, self.atr_n)

        # первый валидный бар каждой монеты (день листинга внутри панели)
        first = np.full(N, -1)
        for i in range(N):
            idx = np.where(np.isfinite(C[:, i]) & (C[:, i] > 0))[0]
            if len(idx):
                first[i] = idx[0]
        # реальный листинг: появился ПОЗЖЕ старта панели (не обрезка истории слева)
        real_listing = first > self.min_age_from_lake

        stop_hi = shift(rolling_max(H, self.stop_hi_n), 1)
        trail_hi = shift(rolling_max(H, self.trail_n), 1)

        W = np.zeros((T, N))
        for i in range(N):
            if not real_listing[i]:
                continue
            f = first[i]
            # H0 = максимум первых listing_hi_days дней ЭТОЙ монеты (индекс i обязателен!)
            hi_win = H[f:f + self.listing_hi_days, i]
            if not np.isfinite(hi_win).any():
                continue
            H0 = np.nanmax(hi_win)
            broke_H0 = False        # обновляла ли цена H0 после дня +1 (тогда отменяем сетап)
            pos = 0.0
            entry_bar = -1
            for t in range(f + 1, T):
                c = C[t, i]
                if not np.isfinite(c):
                    pos = 0.0; continue
                age = t - f
                if np.isfinite(H[t, i]) and H[t, i] > H0 and age > 1:
                    broke_H0 = True
                # выходы
                if pos < 0:
                    hit_stop = ((np.isfinite(stop_hi[t, i]) and c > stop_hi[t, i]) or
                                (np.isfinite(A[t, i]) and c > C[entry_bar, i] + self.atr_k * A[entry_bar, i]))
                    hit_trail = np.isfinite(trail_hi[t, i]) and c > trail_hi[t, i]
                    hit_target = c <= C[entry_bar, i] * (1 + self.target)
                    hit_time = (t - entry_bar) >= self.time_stop
                    if hit_stop or hit_trail or hit_target or hit_time:
                        pos = 0.0
                # вход: окно дней start..end, слом вниз, H0 не обновлён
                if pos == 0.0 and self.start_day <= age <= self.end_day and not broke_H0:
                    lo_win = L[max(f + 1, t - self.confirm_n):t, i]   # min low дней +1..+confirm (монета i!)
                    if lo_win.size and np.isfinite(lo_win).any():
                        trig = np.nanmin(lo_win)
                        if np.isfinite(trig) and c < trig:
                            pos = -1.0; entry_bar = t
                # сайзинг
                a = A[t, i]
                if pos < 0 and np.isfinite(a) and a > 0:
                    unit = self.risk / (a / c)
                    W[t, i] = -min(unit, self.max_w)

        gross = np.sum(np.abs(W), axis=1, keepdims=True)
        scale = np.where(gross > self.max_gross, self.max_gross / gross, 1.0)
        return W * scale
