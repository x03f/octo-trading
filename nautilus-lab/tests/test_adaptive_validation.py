"""P6: валидатор Adaptive AI реально считает Monte Carlo CI и neighbor-sensitivity (не заглушки)."""
import numpy as np
from ntlab.adaptive.validator import _monte_carlo_sharpe, _sensitivity


def test_monte_carlo_positive_edge():
    rng = np.random.default_rng(0)
    r = rng.normal(0.004, 0.01, 400)          # устойчиво положительный дрейф
    mc = _monte_carlo_sharpe(r, ppy=365)
    assert mc["sharpe_ci_low"] is not None
    assert mc["prob_positive"] > 0.9          # почти всегда >0 при явном крае
    assert mc["sharpe_ci_low"] < mc["sharpe_ci_high"]


def test_monte_carlo_no_edge_crosses_zero():
    rng = np.random.default_rng(2)            # нулевой дрейф — эмп. среднее ~0, края нет
    r = rng.normal(0.0, 0.02, 400)
    mc = _monte_carlo_sharpe(r, ppy=365)
    assert mc["sharpe_ci_low"] < 0 < mc["sharpe_ci_high"]   # CI пересекает 0
    assert 0.1 < mc["prob_positive"] < 0.9    # не уверенный край ни в плюс, ни в минус


def test_monte_carlo_too_short():
    mc = _monte_carlo_sharpe([0.01, 0.02], ppy=365)
    assert mc["sharpe_ci_low"] is None        # мало данных — честно None, не выдумка


def test_monte_carlo_deterministic():
    r = np.random.default_rng(5).normal(0.001, 0.01, 300)
    assert _monte_carlo_sharpe(r, 365) == _monte_carlo_sharpe(r, 365)   # фикс. seed → воспроизводимо


def test_sensitivity_perturbs_numeric_params():
    from ntlab.adaptive import validator as V

    class ToyPanel:
        ppy = 365

    class ToyStrat:
        def __init__(self, k): self.k = k
        def generate(self, panel): return None

    orig = V._three_set
    V._three_set = lambda panel, strat, cvec: {"test": {"sharpe": 1.0}, "test_returns": np.zeros(50)}
    try:
        s = _sensitivity(lambda p: ToyStrat(p["k"]), {"k": 10}, ToyPanel(), None, 365)
        assert s["neighbors"] == 2                  # ±1 шаг по одному числовому параметру
        assert s["median_test_sharpe"] == 1.0
    finally:
        V._three_set = orig
