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
