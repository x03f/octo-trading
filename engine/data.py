"""Загрузка озера данных (parquet) в numpy. Панель = выровненные по общей сетке времени матрицы."""
import os
import numpy as np
import pyarrow.parquet as pq

LAKE = "/opt/octobot/strategy-lab/data/ohlcv"
_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]

# баров в году по таймфрейму (крипта 24/7 → 365 дней)
PPY = {"1d": 365, "4h": 365 * 6, "1h": 365 * 24, "15m": 365 * 24 * 4, "5m": 365 * 24 * 12}


def list_universe(tf="1d"):
    d = f"{LAKE}/{tf}"
    if not os.path.isdir(d):
        return []
    suf = "USDT.parquet"
    return sorted(f[:-len(suf)] for f in os.listdir(d) if f.endswith(suf))


def load(coin, tf="1d"):
    """Один инструмент → dict numpy-массивов, отсортирован по времени."""
    path = f"{LAKE}/{tf}/{coin}USDT.parquet"
    t = pq.read_table(path)
    d = {c: np.asarray(t.column(c).to_numpy(zero_copy_only=False)) for c in _FIELDS}
    order = np.argsort(d["timestamp"])
    return {k: v[order] for k, v in d.items()}


class Panel:
    """Выровненные матрицы [T×N]. NaN = инструмент ещё не листился на этом баре."""
    def __init__(self, coins, ts, o, h, l, c, v, tf="1d"):
        self.coins = list(coins)
        self.ts = ts
        self.open, self.high, self.low, self.close, self.volume = o, h, l, c, v
        self.tf = tf
        self.T, self.N = c.shape
        self.ppy = PPY.get(tf, 365)

    def col(self, coin):
        return self.coins.index(coin)

    def __repr__(self):
        return f"Panel(T={self.T}, N={self.N}, tf={self.tf}, coins={self.coins})"


def load_panel(coins, tf="1d"):
    """Список монет → Panel на объединённой сетке времени (outer-join, пропуски = NaN)."""
    series = {co: load(co, tf) for co in coins}
    allts = np.unique(np.concatenate([s["timestamp"] for s in series.values()]))
    T, N = len(allts), len(coins)

    def mat(field):
        m = np.full((T, N), np.nan)
        for j, co in enumerate(coins):
            s = series[co]
            pos = np.searchsorted(allts, s["timestamp"])  # allts отсортирован, ts ⊆ allts
            m[pos, j] = s[field]
        return m

    return Panel(coins, allts,
                 mat("open"), mat("high"), mat("low"), mat("close"), mat("volume"), tf)
