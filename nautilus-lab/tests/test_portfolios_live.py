"""Долгоживущий портфельный узел: детерминированный тест инкрементального сигнала (без Nautilus/WS)."""
from ntlab.nautilus.portfolios_node import live_signal, _kind_for


def test_donchian_breakout_enters_and_exits():
    highs = [10]*20 + [10]; lows = [8]*20 + [8]; closes = [9]*20 + [11]   # пробой вверх
    assert live_signal("donchian", highs, lows, closes, pos=0, entry_n=20, exit_n=10) == 1
    # выход при пробое вниз (close <= min low окна)
    highs2 = [10]*20; lows2 = [8]*20; closes2 = [9]*19 + [7]
    assert live_signal("donchian", highs2, lows2, closes2, pos=1, entry_n=20, exit_n=10) == 0


def test_donchian_holds_when_no_signal():
    highs = [10]*20; lows = [8]*20; closes = [9]*20
    assert live_signal("donchian", highs, lows, closes, pos=0, entry_n=20, exit_n=10) == 0   # нет пробоя → плоско


def test_sma_cross_long_when_fast_above_slow():
    closes = [1]*20 + [5]*10                          # растущий тренд: fast(10)>slow(30)
    assert live_signal("sma", [], [], closes, pos=0, fast=10, slow=30) == 1
    closes2 = [5]*20 + [1]*10                          # падающий: fast<slow
    assert live_signal("sma", [], [], closes2, pos=1, fast=10, slow=30) == 0


def test_meanrev_enters_on_low_z():
    closes = [10]*29 + [4]                             # резкий провал → z < -2
    assert live_signal("meanrev", [], [], closes, pos=0, slow=30) == 1


def test_insufficient_history_holds():
    assert live_signal("donchian", [10]*5, [8]*5, [9]*5, pos=0, entry_n=20) == 0
    assert live_signal("sma", [], [], [1]*5, pos=0, slow=30) == 0


def test_kind_mapping():
    assert _kind_for("S4") == "donchian"
    assert _kind_for("S1") == "sma"
    assert _kind_for("S5") == "meanrev"
    assert _kind_for("unknown") == "donchian"
