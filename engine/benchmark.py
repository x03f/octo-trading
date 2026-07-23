"""Независимые бенчмарки (свой расчёт, НЕ метрика чужого движка).
Всегда сравниваем стратегию с равновзвешенной корзиной и с BTC buy-hold."""
import numpy as np
from .backtester import run_portfolio


def buy_hold_equal_weight(panel, cost=None, ppy=None):
    """Равный вес среди листящихся на каждом баре активов (ре-баланс каждый бар)."""
    C = panel.close
    T, N = C.shape
    W = np.zeros((T, N))
    for t in range(T):
        valid = np.isfinite(C[t]) & (C[t] > 0)
        k = int(valid.sum())
        if k > 0:
            W[t, valid] = 1.0 / k
    return run_portfolio(panel, W, cost=cost, ppy=ppy)


def buy_hold_single(panel, coin, ppy=None):
    """Купил-и-держи один инструмент (100% вес, без ре-баланса-костов)."""
    j = panel.coins.index(coin)
    C = panel.close
    T, N = C.shape
    W = np.zeros((T, N))
    W[:, j] = 1.0
    return run_portfolio(panel, W, cost=None, ppy=ppy)
