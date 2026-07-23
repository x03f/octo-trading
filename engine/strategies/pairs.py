"""S3 «Спред» — статистический арбитраж коинтегрированных пар (market-neutral).

Edge: пары мажоров коинтегрированы; спред возвращается к среднему. Низкая бета к рынку.
Честность (walk-forward, без look-ahead):
  • каждые refit баров на ТРЕЙЛИНГ-окне (form баров, БЕЗ текущего) заново оцениваем hedge-ratio β
    (OLS log-цен) и тестируем коинтеграцию hand-rolled ADF на остатках спреда;
  • пара торгуется ТОЛЬКО пока ADF-t-stat < крит (стационарность остатков), иначе — вне рынка;
  • z-score текущего спреда считается относительно среднего/σ ПРОШЛОГО окна;
  • ноги сайзятся по β (коинтеграционный вектор): long spread = long A / short β·B.
Пары выбраны по ЭКОНОМИЧЕСКОМУ смыслу (не по бэктест-результату) — так избегаем selection-bias.
⚠️ Коинтеграция в крипте нестабильна и ломается в стрессе; числа требуют строгого OOS.
"""
import numpy as np
from ..strategy import Strategy

# кандидаты по экономическому смыслу (родственные активы / L1-L1 / форки)
CANDIDATE_PAIRS = [
    ("ETH", "BTC"), ("SOL", "ETH"), ("BNB", "BTC"), ("LTC", "BCH"),
    ("XRP", "XLM"), ("ADA", "ETH"), ("LINK", "ETH"), ("DOGE", "BTC"),
    ("AVAX", "SOL"), ("SUI", "SOL"),
]


def ols_hedge(logA, logB):
    """logA = α + β·logB. Возвращает (β, α)."""
    X = np.column_stack([logB, np.ones(len(logB))])
    coef, *_ = np.linalg.lstsq(X, logA, rcond=None)
    return float(coef[0]), float(coef[1])


def adf_tstat(s, maxlag=1):
    """Hand-rolled ADF (const, без тренда): t-stat коэффициента при s_{t-1}.
    < крит (~−2.86 @5%) → отвергаем единичный корень → остатки стационарны → коинтеграция."""
    s = np.asarray(s, float)
    s = s[np.isfinite(s)]
    n = len(s)
    if n < 30:
        return np.nan
    ds = np.diff(s)
    slag = s[:-1]
    Y = ds[maxlag:]
    cols = [slag[maxlag:], np.ones(len(Y))]
    for k in range(1, maxlag + 1):
        cols.append(ds[maxlag - k:len(ds) - k])
    X = np.column_stack(cols)
    if len(Y) <= X.shape[1]:
        return np.nan
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    dof = len(Y) - X.shape[1]
    s2 = float(resid @ resid) / dof
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return np.nan
    se = np.sqrt(s2 * XtX_inv[0, 0])
    return float(beta[0] / se) if se > 0 else np.nan


class Pairs(Strategy):
    name = "S3-spread"

    def __init__(self, form=180, refit=20, z_entry=2.0, z_exit=0.5, z_stop=4.0,
                 adf_crit=-2.86, pair_gross=0.35, max_gross=1.0):
        self.form = form
        self.refit = refit
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.z_stop = z_stop
        self.adf_crit = adf_crit
        self.pair_gross = pair_gross
        self.max_gross = max_gross

    def generate(self, panel):
        C = panel.close
        T, N = C.shape
        with np.errstate(divide="ignore", invalid="ignore"):
            LOG = np.log(C)
        W = np.zeros((T, N))
        pairs = [(a, b) for a, b in CANDIDATE_PAIRS
                 if a in panel.coins and b in panel.coins]

        for a, b in pairs:
            ia, ib = panel.coins.index(a), panel.coins.index(b)
            la, lb = LOG[:, ia], LOG[:, ib]
            beta = alpha = mu = sd = np.nan
            active = False
            state = 0

            for t in range(T):
                # --- переоценка β/коинтеграции на трейлинг-окне (без текущего бара) ---
                if t >= self.form and t % self.refit == 0:
                    wa, wb = la[t - self.form:t], lb[t - self.form:t]
                    m = np.isfinite(wa) & np.isfinite(wb)
                    if m.sum() >= max(40, self.form // 2):
                        beta, alpha = ols_hedge(wa[m], wb[m])
                        spr = wa[m] - beta * wb[m] - alpha
                        tstat = adf_tstat(spr, maxlag=1)
                        active = np.isfinite(tstat) and tstat < self.adf_crit
                        mu, sd = float(np.nanmean(spr)), float(np.nanstd(spr, ddof=1))
                    else:
                        active = False

                if not (np.isfinite(la[t]) and np.isfinite(lb[t])) or not active \
                        or not np.isfinite(beta) or not (sd > 0):
                    state = 0
                    continue

                z = (la[t] - beta * lb[t] - alpha - mu) / sd
                if not np.isfinite(z):
                    state = 0
                    continue
                # выходы к среднему / хард-стоп на разрыв коинтеграции
                if state > 0 and z >= -self.z_exit:
                    state = 0
                elif state < 0 and z <= self.z_exit:
                    state = 0
                if state != 0 and abs(z) > self.z_stop:
                    state = 0
                # входы
                if state == 0:
                    if z < -self.z_entry:
                        state = 1     # long spread: long A / short β·B
                    elif z > self.z_entry:
                        state = -1    # short spread
                # веса ног по коинтеграционному вектору
                if state != 0:
                    u = self.pair_gross
                    W[t, ia] += state * u
                    W[t, ib] += -state * beta * u

        g = np.abs(W).sum(axis=1, keepdims=True)
        scale = np.where(g > self.max_gross, self.max_gross / np.maximum(g, 1e-9), 1.0)
        return W * scale
