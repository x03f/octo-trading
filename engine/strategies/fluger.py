"""S1 «Флюгер» — режим-адаптивная директивная стратегия (лонг-шорт).

Ядро на TS-моментуме (сильный edge, STRATEGY-SUITE §1); в боковике переключается на mean-reversion.
Механика по каждому активу:
  • ADX > adx_trend → ТРЕНД-режим: правила пробоя Donchian (как S4);
  • ADX < adx_range → БОКОВИК: правила z-score fade (как S5);
  • между — переходная зона: держим открытое, новых входов нет.
  • Портфельный risk-фильтр: BTC vs SMA200 → gross_scalar (risk-off урезает плечо — урок folio).
  • Сайзинг vol-target по ATR; лонг-шорт; потолок гросса max_gross.
⚠️ Funding-tilt — СТАБ (funding по перпам ещё не собран, задача #9). Ценовой движок тестируется на
   спот-данных уже сейчас; при появлении funding войдёт как асимметрия порогов и carry-P&L.
Без look-ahead: каналы сдвинуты на 1 бар, индикаторы по данным ≤ t, вес держится (t, t+1).
"""
import numpy as np
from ..strategy import (Strategy, rolling_max, rolling_min, rolling_mean,
                        rolling_std, atr, adx, shift)


class Fluger(Strategy):
    name = "S1-fluger"

    def __init__(self, entry_n=20, exit_n=10, ma_n=20, atr_n=20,
                 adx_trend=25.0, adx_range=20.0, z_entry=2.0, z_exit=0.4, z_stop=3.5,
                 risk=0.01, max_w=0.5, max_gross=1.0, btc_sma=200,
                 riskoff_scalar=0.5, allow_short=True):
        self.entry_n, self.exit_n, self.ma_n, self.atr_n = entry_n, exit_n, ma_n, atr_n
        self.adx_trend, self.adx_range = adx_trend, adx_range
        self.z_entry, self.z_exit, self.z_stop = z_entry, z_exit, z_stop
        self.risk, self.max_w, self.max_gross = risk, max_w, max_gross
        self.btc_sma, self.riskoff_scalar = btc_sma, riskoff_scalar
        self.allow_short = allow_short

    def generate(self, panel):
        H, L, C = panel.high, panel.low, panel.close
        T, N = C.shape
        chan_hi = shift(rolling_max(H, self.entry_n), 1)
        chan_lo = shift(rolling_min(L, self.entry_n), 1)
        exit_lo = shift(rolling_min(L, self.exit_n), 1)
        exit_hi = shift(rolling_max(H, self.exit_n), 1)
        A = atr(H, L, C, self.atr_n)
        AD = adx(H, L, C, 14)
        MA = rolling_mean(C, self.ma_n)
        SD = rolling_std(C, self.ma_n)
        with np.errstate(divide="ignore", invalid="ignore"):
            Z = (C - MA) / SD

        # портфельный risk-фильтр по BTC vs SMA200
        gross_scalar = np.ones(T)
        if "BTC" in panel.coins:
            bc = C[:, panel.coins.index("BTC")]
            bsma = rolling_mean(bc, self.btc_sma)
            for t in range(T):
                if np.isfinite(bsma[t]) and np.isfinite(bc[t]) and bc[t] < bsma[t]:
                    gross_scalar[t] = self.riskoff_scalar

        W = np.zeros((T, N))
        pos = np.zeros(N)
        mode = [""] * N   # 'T' тренд / 'M' боковик — как вошли, так и выходим

        for t in range(T):
            for i in range(N):
                c = C[t, i]
                if not np.isfinite(c):
                    pos[i] = 0.0; mode[i] = ""
                    continue
                a = AD[t, i]
                z = Z[t, i]
                trend_reg = np.isfinite(a) and a > self.adx_trend
                range_reg = np.isfinite(a) and a < self.adx_range
                p = pos[i]

                # --- выходы по режиму входа ---
                if p != 0.0 and mode[i] == "T":
                    if p > 0 and np.isfinite(exit_lo[t, i]) and c < exit_lo[t, i]:
                        p = 0.0
                    elif p < 0 and np.isfinite(exit_hi[t, i]) and c > exit_hi[t, i]:
                        p = 0.0
                elif p != 0.0 and mode[i] == "M":
                    if (p > 0 and np.isfinite(z) and z >= -self.z_exit) or \
                       (p < 0 and np.isfinite(z) and z <= self.z_exit) or \
                       (np.isfinite(z) and abs(z) > self.z_stop) or (not range_reg):
                        p = 0.0
                if p == 0.0:
                    mode[i] = ""

                # --- входы ---
                if p == 0.0:
                    if trend_reg:  # трендовый пробой
                        if np.isfinite(chan_hi[t, i]) and c > chan_hi[t, i]:
                            p, mode[i] = 1.0, "T"
                        elif self.allow_short and np.isfinite(chan_lo[t, i]) and c < chan_lo[t, i]:
                            p, mode[i] = -1.0, "T"
                    elif range_reg and np.isfinite(z):  # mean-reversion в боковике
                        if z < -self.z_entry:
                            p, mode[i] = 1.0, "M"
                        elif self.allow_short and z > self.z_entry:
                            p, mode[i] = -1.0, "M"
                pos[i] = p

                # --- сайзинг vol-target × BTC-risk-scalar ---
                av = A[t, i]
                if p != 0.0 and np.isfinite(av) and av > 0:
                    unit = self.risk / (av / c)
                    W[t, i] = p * min(unit, self.max_w) * gross_scalar[t]

        g = np.abs(W).sum(axis=1, keepdims=True)
        scale = np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
        return W * scale
