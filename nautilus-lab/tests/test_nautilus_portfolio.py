"""П.1 приёмки: основной paper-портфель РЕАЛЬНО проходит через Nautilus (Strategy → order lifecycle
→ SimulatedExchange → Nautilus Portfolio). Прогон изолирован в subprocess (Rust-логгер раз/процесс)."""


def test_portfolio_routes_through_nautilus():
    from ntlab.nautilus.paper_engine import run_isolated
    r = run_isolated("S4", ["BTC_USDT", "ETH_USDT"], 1000.0)
    assert r.get("is_nautilus") is True, r
    assert r["engine"] == "nautilus-backtest"
    assert r["fills"] > 0                          # ордера прошли через Nautilus lifecycle
    assert 0 < r["equity"] < 100000                # equity из Nautilus account (сайзинг корректен)
    assert "SimulatedExchange" in r["lifecycle"]


def test_portfolio_manager_nautilus_backed(tmp_path, monkeypatch):
    import ntlab.portfolios.manager as pm
    monkeypatch.setattr(pm, "STORE", tmp_path)
    monkeypatch.setattr(pm, "STATUS", tmp_path / "s.json")
    m = pm.PortfolioManager()
    p = m.create("NautTest", 1000.0, "S4", ["BTC_USDT"])
    m.run(p.pid)
    st = p.status()
    assert st["is_nautilus"] is True and st["engine"] == "nautilus-backtest"
    assert st["ran"] is True
    m.pause(p.pid)
    assert p.run() == {"skipped": "paused"}        # пауза блокирует прогон
    m.resume(p.pid)
    assert p.paused is False                        # resume восстанавливает
