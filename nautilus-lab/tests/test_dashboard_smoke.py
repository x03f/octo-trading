"""P10/smoke дашборда: все API-эндпойнты отвечают 200 и валидным JSON, index отдаётся.
Не проверяет содержимое чисел — только что бэкенд собран и контракт цел."""
import sys
sys.path.insert(0, "/opt/octobot/nautilus-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab")
import pytest
from fastapi.testclient import TestClient
from ntlab.api.app import app

client = TestClient(app)

ENDPOINTS = ["/api/health", "/api/overview", "/api/lake", "/api/strategies",
             "/api/experiments", "/api/leaderboard", "/api/backtests", "/api/paper",
             "/api/nautilus-runtime", "/api/contours", "/api/portfolio", "/api/portfolios",
             "/api/adaptive", "/api/adaptive-lifecycle", "/api/system"]


@pytest.mark.parametrize("ep", ENDPOINTS)
def test_endpoint_200_json(ep):
    r = client.get(ep)
    assert r.status_code == 200, f"{ep} -> {r.status_code}"
    assert isinstance(r.json(), (dict, list))              # валидный JSON, без NaN-краша


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Nautilus Trading Lab" in r.text


def test_health_contract():
    h = client.get("/api/health").json()
    assert set(("ok", "components", "uptime_s")).issubset(h)
    assert "gateio_keys" in h["components"]                 # ключи в контракте (сейчас False)
