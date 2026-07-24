"""P10/производительность: бэктест и сигнал должны укладываться в бюджет латентности.
Пороговые значения намеренно щедрые — ловят регрессии на порядок, не микрошум.
Замер через time.perf_counter (Date.now недоступен в песочнице сборки, но в pytest это обычный time)."""
import time
import numpy as np
from conftest import synth_panel
from engine.backtester import run_portfolio
from engine.costs import GATE_TAKER
from engine.metrics import stats
from ntlab.strategies.s11_signal import s11_run, S11Params


def test_backtest_throughput():
    p = synth_panel(T=2000, N=10)
    w = np.full((2000, 10), 0.1)
    t0 = time.perf_counter()
    run_portfolio(p, w, cost=GATE_TAKER)
    dt = time.perf_counter() - t0
    assert dt < 5.0, f"бэктест 2000x10 занял {dt:.2f}s (порог 5s)"


def test_signal_latency():
    p = synth_panel(T=5000, N=1)
    h, l, c = p.high[:, 0], p.low[:, 0], p.close[:, 0]
    t0 = time.perf_counter()
    s11_run(h, l, c, params=S11Params())
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"s11_run 5000 баров занял {dt:.2f}s (порог 2s)"


def test_metrics_fast():
    eq = np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, 10000))
    t0 = time.perf_counter()
    stats(eq)
    assert time.perf_counter() - t0 < 0.5
