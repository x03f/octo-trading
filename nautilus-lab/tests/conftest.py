"""Общие хелперы для P10-категорий тестов."""
import numpy as np
import sys
sys.path.insert(0, "/opt/octobot/strategy-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
from engine.data import Panel


def synth_panel(T=400, N=4, seed=7, tf="1d"):
    """Детерминированная синтетическая панель (геом. броуновское блуждание)."""
    rng = np.random.default_rng(seed)
    ts = np.arange(T, dtype=np.int64) * 86400
    closes = np.zeros((T, N))
    for i in range(N):
        steps = rng.normal(0.0005, 0.03, T)
        closes[:, i] = 100.0 * np.exp(np.cumsum(steps))
    o = closes * (1 + rng.normal(0, 0.002, (T, N)))
    h = np.maximum(o, closes) * (1 + np.abs(rng.normal(0, 0.005, (T, N))))
    l = np.minimum(o, closes) * (1 - np.abs(rng.normal(0, 0.005, (T, N))))
    v = np.abs(rng.normal(1e6, 2e5, (T, N)))
    coins = [f"C{i}USDT" for i in range(N)]
    return Panel(coins, ts, o, h, l, closes, v, tf=tf)


class FakeMarket:
    """Подставной источник данных для PaperExecution (стакан/свечи/инструмент) — без сети."""
    def __init__(self, mid=100.0, depth=None, precision=(2, 4), mins=(0.0, 0.0)):
        self.mid = mid
        self.depth = depth or [(0.5,), (1.0,), (5.0,)]   # уровни глубины (qty)
        self.pp, self.ap = precision
        self.min_q, self.min_b = mins

    def set_mid(self, m): self.mid = m

    def order_book(self, symbol, limit=20):
        asks = [[self.mid * (1 + 0.001 * (i + 1)), q[0]] for i, q in enumerate(self.depth)]
        bids = [[self.mid * (1 - 0.001 * (i + 1)), q[0]] for i, q in enumerate(self.depth)]
        return {"asks": asks, "bids": bids}

    def candles(self, symbol, tf="1m", limit=1):
        return [{"close": self.mid}]

    def instrument(self, symbol):
        return {"price_precision": self.pp, "amount_precision": self.ap,
                "min_quote_amount": self.min_q, "min_base_amount": self.min_b}
