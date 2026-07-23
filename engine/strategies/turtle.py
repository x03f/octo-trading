"""S4 «Черепаха» — Donchian/Turtle time-series breakout (лонг+шорт).

Edge: time-series momentum — самый сильный документированный edge в крипте (STRATEGY-SUITE §1).
Механика (классические Черепахи, адаптировано):
  • вход LONG:  close[t] пробивает ВЕРХ Donchian(entry_n) прошлых баров (канал БЕЗ текущего бара);
  • вход SHORT: close[t] пробивает НИЗ Donchian(entry_n);
  • выход: обратный пробой более короткого Donchian(exit_n);
  • сайзинг: vol-target по ATR — вес такой, что 1×ATR-ход ≈ risk% эквити (cap max_w);
  • режим-фильтр: входы только если ADX≥adx_min (гасит пилу в боковике).
Без look-ahead: каналы сдвинуты на 1 бар (только прошлое), ATR/ADX по данным ≤ t, вес держится (t,t+1).
"""
import numpy as np
from ..strategy import Strategy, rolling_max, rolling_min, atr, adx, shift


class Turtle(Strategy):
    name = "S4-turtle"

    def __init__(self, entry_n=20, exit_n=10, atr_n=20, risk=0.01, max_w=0.5,
                 max_gross=1.0, use_adx=True, adx_min=20.0, allow_short=True):
        self.entry_n = entry_n
        self.exit_n = exit_n
        self.atr_n = atr_n
        self.risk = risk            # целевой риск на позицию (доля эквити на 1 ATR)
        self.max_w = max_w          # потолок веса одной позиции
        self.max_gross = max_gross  # потолок суммарного |веса| (1.0 = без плеча)
        self.use_adx = use_adx
        self.adx_min = adx_min
        self.allow_short = allow_short

    def generate(self, panel):
        H, L, C = panel.high, panel.low, panel.close
        T, N = C.shape
        chan_hi = shift(rolling_max(H, self.entry_n), 1)   # прошлый N-максимум (без сегодня)
        chan_lo = shift(rolling_min(L, self.entry_n), 1)
        exit_lo = shift(rolling_min(L, self.exit_n), 1)
        exit_hi = shift(rolling_max(H, self.exit_n), 1)
        A = atr(H, L, C, self.atr_n)
        AD = adx(H, L, C, 14) if self.use_adx else None

        W = np.zeros((T, N))
        pos = np.zeros(N)  # состояние по каждому активу: −1 / 0 / +1

        for t in range(T):
            for i in range(N):
                c = C[t, i]
                if not np.isfinite(c):
                    pos[i] = 0.0
                    continue
                p = pos[i]
                # --- выходы (обратный короткий канал) ---
                if p > 0 and np.isfinite(exit_lo[t, i]) and c < exit_lo[t, i]:
                    p = 0.0
                elif p < 0 and np.isfinite(exit_hi[t, i]) and c > exit_hi[t, i]:
                    p = 0.0
                # --- входы (с режим-фильтром) ---
                trend_ok = (not self.use_adx) or (np.isfinite(AD[t, i]) and AD[t, i] >= self.adx_min)
                if p == 0.0 and trend_ok:
                    if np.isfinite(chan_hi[t, i]) and c > chan_hi[t, i]:
                        p = 1.0
                    elif self.allow_short and np.isfinite(chan_lo[t, i]) and c < chan_lo[t, i]:
                        p = -1.0
                pos[i] = p
                # --- сайзинг (vol-target по ATR) ---
                a = A[t, i]
                if p != 0.0 and np.isfinite(a) and a > 0:
                    unit = self.risk / (a / c)          # 1×ATR ≈ risk% эквити
                    W[t, i] = p * min(unit, self.max_w)

        # нормировка суммарного гросса ≤ max_gross
        g = np.abs(W).sum(axis=1, keepdims=True)
        scale = np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
        return W * scale
