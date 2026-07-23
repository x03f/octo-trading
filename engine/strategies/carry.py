"""S2 «Базис» — delta-neutral funding/basis carry (СКЕЛЕТ, ждёт funding-данные задачи #9).

Идея: держим спот против перпа так, что чистая дельта ≈ 0, и инкассируем funding. Доход почти
не зависит от цены → это «облигационная» ballast-нога. Вход только если |funding| за период
покрывает break-even (комиссии двух ног + слипедж). Сторона выбирается так, чтобы ПОЛУЧАТЬ funding.

⚠️ Реального funding у нас пока нет → P&L считается по переданному массиву funding[T×N]. Для проверки
ЛОГИКИ есть synthetic_funding(). Настоящий прогон — после сбора истории funding по перпам.
"""
import numpy as np


class Carry:
    name = "S2-basis"

    def __init__(self, breakeven_bps=3.0, per_asset=0.25, max_gross=1.0, fee_bps=6.0):
        self.breakeven = breakeven_bps / 1e4     # порог входа на период
        self.per_asset = per_asset
        self.max_gross = max_gross
        self.rate2 = 2.0 * fee_bps / 1e4          # две ноги (спот+перп) на открытие/закрытие

    def target_weights(self, funding):
        """funding[t,i] — ставка за период (доля). Возвращает |веса| капитала на carry (delta-neutral)."""
        funding = np.asarray(funding, float)
        T, N = funding.shape
        W = np.zeros((T, N))
        for t in range(T):
            for i in range(N):
                f = funding[t, i]
                if np.isfinite(f) and abs(f) > self.breakeven:
                    W[t, i] = self.per_asset      # всегда позиционируемся на приём funding
        g = W.sum(axis=1, keepdims=True)
        scale = np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
        return W * scale

    def run(self, funding, ppy=365):
        """Эквити carry-ноги. Доход = Σ|funding|·вес − косты ребаланса двух ног."""
        from ..metrics import stats
        funding = np.asarray(funding, float)
        T, N = funding.shape
        W = self.target_weights(funding)
        equity = np.ones(T)
        wprev = np.zeros(N)
        turn_s = np.zeros(T)
        for t in range(1, T):
            wheld = wprev
            f = np.nan_to_num(funding[t], nan=0.0)
            income = float(np.dot(np.abs(f), wheld))     # всегда получаем |funding|
            equity[t] = equity[t - 1] * (1.0 + income)
            turn = float(np.abs(W[t] - wprev).sum())
            equity[t] *= (1.0 - turn * self.rate2)
            turn_s[t] = turn
            wprev = W[t]
        st = stats(equity, ppy)
        st["avg_turnover"] = float(turn_s[1:].mean()) if T > 1 else 0.0
        st["avg_gross_exposure"] = float(W.sum(axis=1)[1:].mean()) if T > 1 else 0.0
        return {"equity": equity, "stats": st}

    @staticmethod
    def synthetic_funding(panel, regime="positive", seed=7):
        """Синтетический funding для проверки логики (НЕ реальные данные).
        regime: 'positive' (лонг-биас, funding>0), 'compressed' (≈0), 'mixed' (знак плавает)."""
        rng = np.random.default_rng(seed)
        T, N = panel.close.shape
        base = {"positive": 0.0004, "compressed": 0.00003, "mixed": 0.0}[regime]  # за 8ч-период
        f = np.full((T, N), np.nan)
        for i in range(N):
            x = base
            for t in range(T):
                if not np.isfinite(panel.close[t, i]):
                    continue
                x = 0.92 * x + 0.08 * base + rng.normal(0, 0.0003)  # AR(1) вокруг base
                if regime == "mixed":
                    x += 0.0006 * np.sin(t / 30.0 + i)
                f[t, i] = x
        return f
