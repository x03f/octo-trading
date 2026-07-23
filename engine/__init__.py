"""strategy-lab бэктест-движок (pure numpy, без pandas/scipy).

Честный портфельный бэктестер БЕЗ look-ahead: веса формируются на закрытии бара t
из данных ≤t и держатся на интервале (t, t+1). Реалистичные косты и funding.
См. STRATEGY-SUITE.md (ноты S1–S6) и BACKTEST-METHODOLOGY.md (правила честности).
"""
from .data import Panel, load, load_panel, list_universe, PPY
from .metrics import stats, max_drawdown, equity_returns
from .costs import CostModel
from .backtester import run_portfolio
from .benchmark import buy_hold_equal_weight, buy_hold_single
from .strategy import Strategy

__all__ = ["Panel", "load", "load_panel", "list_universe", "PPY",
           "stats", "max_drawdown", "equity_returns",
           "CostModel", "run_portfolio",
           "buy_hold_equal_weight", "buy_hold_single", "Strategy"]
