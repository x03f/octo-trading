"""P10/воспроизводимость: одинаковый вход → бит-в-бит одинаковый результат.
Требование ТЗ: seed/data_sha/git_sha фиксируют эксперимент, повтор даёт то же."""
import numpy as np
from conftest import synth_panel
from engine.backtester import run_portfolio
from engine.costs import GATE_TAKER
from ntlab.strategies.s11_signal import s11_run, S11Params


def _weights(panel, seed):
    rng = np.random.default_rng(seed)
    T, N = panel.close.shape
    w = rng.random((T, N)); w /= w.sum(axis=1, keepdims=True)
    return w


def test_backtest_bit_identical():
    p = synth_panel()
    w = _weights(p, 1)
    a = run_portfolio(p, w, cost=GATE_TAKER)
    b = run_portfolio(p, w, cost=GATE_TAKER)
    assert np.array_equal(a["equity"], b["equity"])          # без стохастики — бит-в-бит
    assert a["stats"]["sharpe"] == b["stats"]["sharpe"]


def test_different_seed_diff_result():
    p = synth_panel()
    a = run_portfolio(p, _weights(p, 1), cost=GATE_TAKER)
    b = run_portfolio(p, _weights(p, 2), cost=GATE_TAKER)
    assert not np.array_equal(a["equity"], b["equity"])      # seed реально влияет


def test_s11_signal_deterministic():
    p = synth_panel()
    h, l, c = p.high[:, 0], p.low[:, 0], p.close[:, 0]
    _, _, pos1 = s11_run(h, l, c, params=S11Params())
    _, _, pos2 = s11_run(h, l, c, params=S11Params())
    assert np.array_equal(np.asarray(pos1), np.asarray(pos2))   # весь ряд позиций совпадает


def test_data_version_stable():
    from ntlab.data.catalog import data_version
    assert data_version() == data_version()                  # манифест sha стабилен
