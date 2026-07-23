"""Базовый интерфейс стратегии + общие индикаторы (pure numpy, без look-ahead).

Стратегия реализует generate(panel) -> weights[T×N]. Веса на баре t ДОЛЖНЫ использовать
только данные ≤ t. Хелпер shift() сдвигает сигнал на 1 бар вперёд (решение по закрытой свече,
исполнение на следующей) — используйте его, если индикатор считается «на текущем» баре.
"""
import numpy as np


class Strategy:
    name = "base"

    def generate(self, panel):
        raise NotImplementedError

    def __repr__(self):
        return f"<Strategy {self.name}>"


# ---------- индикаторы (каждый столбец = актив; NaN-safe) ----------

def shift(a, n=1):
    """Сдвиг вниз на n баров (вперёд во времени): out[t] = a[t-n]. Верх = NaN."""
    a = np.asarray(a, float)
    out = np.full_like(a, np.nan)
    if n < a.shape[0]:
        out[n:] = a[:-n]
    return out


def rolling_max(a, w):
    a = np.asarray(a, float)
    T = a.shape[0]
    out = np.full_like(a, np.nan)
    for t in range(w - 1, T):
        out[t] = np.nanmax(a[t - w + 1:t + 1], axis=0)
    return out


def rolling_min(a, w):
    a = np.asarray(a, float)
    T = a.shape[0]
    out = np.full_like(a, np.nan)
    for t in range(w - 1, T):
        out[t] = np.nanmin(a[t - w + 1:t + 1], axis=0)
    return out


def rolling_mean(a, w):
    a = np.asarray(a, float)
    T = a.shape[0]
    out = np.full_like(a, np.nan)
    for t in range(w - 1, T):
        out[t] = np.nanmean(a[t - w + 1:t + 1], axis=0)
    return out


def rolling_std(a, w):
    a = np.asarray(a, float)
    T = a.shape[0]
    out = np.full_like(a, np.nan)
    for t in range(w - 1, T):
        out[t] = np.nanstd(a[t - w + 1:t + 1], axis=0, ddof=1)
    return out


def ema(a, span):
    a = np.asarray(a, float)
    alpha = 2.0 / (span + 1.0)
    out = np.full_like(a, np.nan)
    prev = None
    for t in range(a.shape[0]):
        x = a[t]
        if prev is None:
            prev = np.where(np.isfinite(x), x, np.nan)
        else:
            prev = np.where(np.isfinite(prev), (1 - alpha) * prev + alpha * np.where(np.isfinite(x), x, prev), x)
        out[t] = prev
    return out


def true_range(high, low, close):
    """TR = max(H-L, |H-Cprev|, |L-Cprev|)."""
    pc = shift(close, 1)
    a = high - low
    b = np.abs(high - pc)
    c = np.abs(low - pc)
    return np.nanmax(np.stack([a, b, c]), axis=0)


def atr(high, low, close, w=14):
    return rolling_mean(true_range(high, low, close), w)


def adx(high, low, close, w=14):
    """ADX по Wilder (упрощённо через SMA сглаживание). >25 тренд, <20 боковик."""
    up = high - shift(high, 1)
    dn = shift(low, 1) - low
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(high, low, close)
    atr_w = rolling_mean(tr, w)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * rolling_mean(plus_dm, w) / atr_w
        minus_di = 100.0 * rolling_mean(minus_dm, w) / atr_w
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return rolling_mean(dx, w)


def rsi(close, w=14):
    d = close - shift(close, 1)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = rolling_mean(gain, w)
    al = rolling_mean(loss, w)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)
