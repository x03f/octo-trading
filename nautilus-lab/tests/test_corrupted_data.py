"""P10/устойчивость к битым данным: NaN, дыры, нулевые/отрицательные цены, вырожденная панель.
Движок обязан не падать и НЕ выдавать бесконечный/фиктивный P&L на мусоре."""
import numpy as np
from conftest import synth_panel
from engine.backtester import run_portfolio
from engine.costs import GATE_TAKER
from engine.metrics import stats, max_drawdown


def _eq_weights(p):
    T, N = p.close.shape
    return np.full((T, N), 1.0 / N)


def test_nan_in_prices_no_crash():
    p = synth_panel()
    p.close[50:60, 1] = np.nan                    # дыра в одном ряду
    r = run_portfolio(p, _eq_weights(p), cost=GATE_TAKER)
    assert np.all(np.isfinite(r["equity"]))       # эквити конечна вопреки NaN
    assert r["equity"][0] == 1.0


def test_zero_and_negative_prices_masked():
    p = synth_panel()
    p.close[30, 2] = 0.0
    p.close[31, 2] = -5.0                          # мусор
    r = run_portfolio(p, _eq_weights(p), cost=GATE_TAKER)
    assert np.all(np.isfinite(r["equity"]))        # невалидные бары маскируются (prev>0)


def test_all_nan_column():
    p = synth_panel()
    p.close[:, 0] = np.nan                          # целиком мёртвый актив
    r = run_portfolio(p, _eq_weights(p), cost=GATE_TAKER)
    assert np.all(np.isfinite(r["equity"]))


def test_degenerate_single_bar():
    s = stats(np.array([1.0]))                      # T=1 — метрики не должны падать
    assert s["n_bars"] == 0 or np.isnan(s["sharpe"])


def test_flat_equity_no_fake_sharpe():
    s = stats(np.ones(500))                          # нулевая волатильность
    assert not np.isfinite(s["sharpe"])              # нельзя выдавать конечный Sharpe на нуле
    assert max_drawdown(np.ones(500)) == 0.0


def test_empty_equity():
    s = stats(np.array([]))
    assert s["n_bars"] == 0
