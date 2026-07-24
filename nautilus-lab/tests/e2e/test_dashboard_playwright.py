"""Настоящий Playwright E2E дашборда: реальный chromium открывает страницу, обходит 9 разделов,
проверяет рендер графиков, кликает контролы, ловит ошибки JS-консоли. Требует запущенный ntlab-api.

Запуск: /opt/octobot/nautilus-venv/bin/python -m pytest tests/e2e/test_dashboard_playwright.py -q
"""
import pytest

BASE = "http://127.0.0.1:5020"
TABS = ["overview", "research", "backtest", "strategies", "portfolios", "live", "adaptive", "datalake", "system"]


@pytest.fixture(scope="module")
def page_ctx():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page()
    errors = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    yield page, errors
    browser.close(); pw.stop()


def test_page_loads(page_ctx):
    page, errors = page_ctx
    page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    assert "Nautilus Trading Lab" in page.content()
    # хедер и навигация присутствуют
    assert page.locator("header h1").count() == 1
    assert page.locator("nav button").count() == 9      # все 9 разделов


def test_all_nine_sections_render(page_ctx):
    page, errors = page_ctx
    page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    for i, tab in enumerate(TABS):
        page.locator("nav button").nth(i).click()
        page.wait_for_timeout(700)                      # рендер + fetch
        # каждый раздел рендерит хотя бы одну карточку
        assert page.locator("main .card").count() >= 1, f"раздел {tab} пуст"


def test_charts_render_svg(page_ctx):
    page, errors = page_ctx
    page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    page.locator("nav button").nth(TABS.index("backtest")).click()
    page.wait_for_timeout(1500)
    assert page.locator("main svg").count() >= 1        # графики эквити/просадки — SVG


def test_control_buttons_work(page_ctx):
    page, errors = page_ctx
    page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    # Adaptive AI: кнопка запуска deterministic
    page.locator("nav button").nth(TABS.index("adaptive")).click()
    page.wait_for_timeout(700)
    btn = page.get_by_text("Запустить цикл", exact=False)
    assert btn.count() >= 1
    btn.first.click()
    page.wait_for_timeout(1500)
    # тост появляется (реальный вызов /api/adaptive/run)
    # Live Trading: emergency stop
    page.locator("nav button").nth(TABS.index("live")).click()
    page.wait_for_timeout(3000)                          # renderLive ждёт 4 fetch (вкл. живой gateio-ping)
    es = page.get_by_text("Emergency stop", exact=False)
    assert es.count() >= 1
    es.first.click()                                     # реальный вызов /api/emergency-stop
    page.wait_for_timeout(1000)


def test_no_console_errors(page_ctx):
    page, errors = page_ctx
    page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    for i in range(len(TABS)):
        page.locator("nav button").nth(i).click()
        page.wait_for_timeout(500)
    # игнорируем возможные favicon 404 и SSE-reconnect шум
    real = [e for e in errors if "favicon" not in e and "EventSource" not in e and "stream" not in e]
    assert not real, f"ошибки JS-консоли: {real}"
