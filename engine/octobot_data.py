"""Мост к бэктест-данным OctoBot: читает его SQLite .data → наш Panel.
Так мой движок гоняется на ТЕХ ЖЕ свечах, что и бэктест OctoBot → сверка без расхождения данных."""
import sqlite3, json, glob
import numpy as np
from .data import Panel

BT_DATA_DIR = "/opt/octobot/backtest/backtesting/data"


def find_data_file(path=None):
    if path:
        return path
    files = sorted(glob.glob(f"{BT_DATA_DIR}/ExchangeHistoryDataCollector_*.data"))
    if not files:
        raise FileNotFoundError("нет .data файлов бэктеста OctoBot")
    return files[-1]


def describe(path=None):
    path = find_data_file(path)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("SELECT * FROM description")
    cols = [d[0] for d in cur.description]
    d = dict(zip(cols, cur.fetchone()))
    con.close()
    return d


def load_octobot_panel(tf="1d", path=None):
    """OctoBot .data → Panel на тех же свечах. candle = [ts_sec, o, h, l, c, v]."""
    path = find_data_file(path)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("SELECT symbol, candle FROM ohlcv WHERE time_frame=?", (tf,))
    rows = cur.fetchall()
    con.close()
    if not rows:
        raise ValueError(f"нет свечей tf={tf} в {path}")

    series = {}
    for sym, candle in rows:
        c = json.loads(candle) if isinstance(candle, str) else candle
        base = sym.split("/")[0]
        series.setdefault(base, []).append([float(x) for x in c])
    coins = sorted(series)
    for co in coins:
        a = np.array(series[co], float)
        series[co] = a[np.argsort(a[:, 0])]

    allts = np.unique(np.concatenate([series[co][:, 0] for co in coins]))
    T, N = len(allts), len(coins)

    def mat(idx):
        m = np.full((T, N), np.nan)
        for j, co in enumerate(coins):
            a = series[co]
            pos = np.searchsorted(allts, a[:, 0])
            m[pos, j] = a[:, idx]
        return m

    ts_ms = (allts * 1000).astype("int64")   # OctoBot хранит секунды → в мс, как в озере
    return Panel(coins, ts_ms, mat(1), mat(2), mat(3), mat(4), mat(5), tf)


def octobot_signal_donchian(panel, period=20):
    """ТОЧНАЯ реплика DonchianBreakoutEvaluator (single-channel, persistent, из tentacle-кода):
    upper=max(high[-period-1:-1]), lower=min(low[...]); price>=upper→trend up(лонг), <=lower→down(флэт/шорт).
    Возвращает trend[T,N] ∈ {−1 up, +1 down, 0}. Спот-эквивалент: long = (trend==−1)."""
    H, L, C = panel.high, panel.low, panel.close
    T, N = C.shape
    trend = np.zeros((T, N))
    for i in range(N):
        prev = 0
        for t in range(T):
            c = C[t, i]
            if not np.isfinite(c) or t < period + 1:
                trend[t, i] = prev
                continue
            win_h = H[t - period:t, i]     # прошлые period свечей (текущую исключаем)
            win_l = L[t - period:t, i]
            if not (np.isfinite(win_h).all() and np.isfinite(win_l).all()):
                trend[t, i] = prev
                continue
            upper, lower = float(np.max(win_h)), float(np.min(win_l))
            if c >= upper:
                cur = -1
            elif c <= lower:
                cur = 1
            else:
                cur = prev
            trend[t, i] = cur
            prev = cur
    return trend
