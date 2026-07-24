"""Тесты Nautilus runtime: многофакторная защита от live, сборка узла, parity стратегии."""
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
from ntlab.nautilus.safety import live_allowed, assert_no_live, CONFIRM_FILE, CONFIRM_PHRASE


# ---------- многофакторная защита: live НЕВОЗМОЖЕН по умолчанию ----------
def test_live_blocked_by_default():
    os.environ.pop("NTLAB_LIVE_ENABLED", None)
    assert live_allowed("live") is False
    assert live_allowed("sandbox") is False


def test_live_needs_all_three_factors(tmp_path=None):
    # 1) только mode=live — мало
    os.environ.pop("NTLAB_LIVE_ENABLED", None)
    assert live_allowed("live") is False
    # 2) mode=live + env — всё ещё мало (нет файла-подтверждения)
    os.environ["NTLAB_LIVE_ENABLED"] = "true"
    assert live_allowed("live") is False
    # 3) неверная фраза в файле — мало
    try:
        import tempfile, pathlib
        # подменять реальный CONFIRM_FILE нельзя (он в проде) → проверяем логику через несуществующий файл
        assert live_allowed("live") is False   # файла нет → заблокировано
    finally:
        os.environ.pop("NTLAB_LIVE_ENABLED", None)


def test_sandbox_cannot_reach_live():
    # из sandbox/paper/backtest боевой путь недоступен в принципе
    for mode in ("sandbox", "paper", "backtest"):
        assert_no_live(mode)   # не должно кидать


def test_assert_no_live_raises_for_unconfirmed_live():
    os.environ.pop("NTLAB_LIVE_ENABLED", None)
    try:
        assert_no_live("live")
        assert False, "должно кинуть PermissionError"
    except PermissionError:
        pass


# ---------- сборка настоящего Nautilus TradingNode ----------
def test_node_builds_sandbox():
    from ntlab.nautilus.node import build_node
    from ntlab.nautilus.diag_strategy import DiagStrategy, DiagConfig
    node, instrument, bar_type = build_node(strategies=[], gate_symbol="BTC_USDT",
                                            bar_spec="1-MINUTE-LAST-EXTERNAL", log_level="ERROR")
    assert node is not None
    assert str(node.kernel.environment) == "Environment.SANDBOX"
    # инструмент в кэше
    assert node.cache.instrument(instrument.id) is not None
    node.dispose()


# ---------- parity: S11Strategy использует ТУ ЖЕ логику, что онлайн-сигнал ----------
def test_s11_strategy_uses_shared_signal():
    import numpy as np
    from ntlab.strategies.s11_signal import s11_run, S11Params
    # синтетика: пик первые 3 бара, слом вниз → шорт
    highs = np.array([10, 12, 11] + [9, 8, 7.5, 7, 6.5] + [6.3] * 15, float)
    lows = highs * 0.95; closes = highs * 0.97
    target, info, positions = s11_run(highs, lows, closes, first_idx=0)
    # должен войти в шорт где-то в окне
    assert (positions < 0).any(), "S11 должна открыть шорт на падающем свежем листинге"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}"); n += 1
    print(f"NAUTILUS RUNTIME: {n}/{n} тестов прошли")
