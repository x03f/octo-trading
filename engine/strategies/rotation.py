"""S9 «Ротация» — кросс-секционный моментум (лонг сильнейших / шорт слабейших).

⚠️ Проверка ЗАЯВЛЕНИЯ, а не ставка на успех. В market-research мы зафиксировали: свежие
исследования 2026 говорят, что cross-sectional momentum в крипте СЛАБ (шорт-нога режется отскоками
лузеров, косты убивают значимость). Здесь мы это ПРОВЕРЯЕМ на своих 316 монетах, а не верим на слово.
Ожидание честное: скорее провалится. Но измерить дёшево, а тип края принципиально иной, чем у
трендовых/MR-нот — если вдруг работает, это ценная НЕкоррелированная нога для ансамбля.

Механика: ранжируем по доходности за look баров; лонг верхний квантиль, шорт нижний;
ребаланс раз в hold баров (реже = меньше костов). Равный вес внутри ноги, гросс ≤ max_gross.
Без look-ahead: ранг считается по данным ≤ t, позиция держится (t, t+1).
"""
import numpy as np
from ..strategy import Strategy


class Rotation(Strategy):
    name = "S9-rotation"

    def __init__(self, look=30, hold=7, q=0.1, max_gross=1.0, allow_short=True):
        self.look = look        # окно моментума (баров)
        self.hold = hold        # ребаланс раз в N баров
        self.q = q              # доля в каждой ноге (0.1 = дециль)
        self.max_gross = max_gross
        self.allow_short = allow_short

    def generate(self, panel):
        C = panel.close
        T, N = C.shape
        W = np.zeros((T, N))
        cur = np.zeros(N)
        for t in range(T):
            if t >= self.look and t % self.hold == 0:      # день ребаланса
                past, now = C[t - self.look], C[t]
                ok = np.isfinite(past) & np.isfinite(now) & (past > 0)
                mom = np.full(N, np.nan)
                mom[ok] = now[ok] / past[ok] - 1.0
                valid = np.isfinite(mom)
                k = int(valid.sum())
                cur = np.zeros(N)
                if k >= 20:                                # нужна ширина среза
                    n_leg = max(1, int(k * self.q))
                    order = np.argsort(np.where(valid, mom, -np.inf))
                    losers, winners = order[:n_leg], order[-n_leg:]
                    cur[winners] = 1.0 / n_leg
                    if self.allow_short:
                        cur[losers] = -1.0 / n_leg
            W[t] = cur
        g = np.abs(W).sum(axis=1, keepdims=True)
        return W * np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
