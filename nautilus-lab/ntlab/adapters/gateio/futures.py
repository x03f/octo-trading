"""Gate.io USDT Perpetual Futures — TestNet + mainnet. Public data + private scaffold + hostname-safety.

Gate.io ФЬЮЧЕРСНЫЙ TestNet РЕАЛЕН (проверено): api-testnet.gateapi.io отдаёт контракты/стакан/свечи/
funding. Спотового публичного testnet нет. Private (balance/orders) требует TestNet-аккаунта и ключей
владельца — их создание вне полномочий агента.

⚠️ БЕЗОПАСНОСТЬ: TestNet-хост зашит и проверяется; запуск private-пути ЗАПРЕЩЁН, если URL совпадает
с production. Отдельный префикс client order ID. Никаких production-ключей в окружении.
"""
import time
import httpx
from .signing import sign_request

TESTNET_BASE = "https://api-testnet.gateapi.io"       # Gate.io Futures TestNet (проверено 200)
MAINNET_BASE = "https://api.gateio.ws"
V4 = "/api/v4"
TESTNET_HOSTS = {"api-testnet.gateapi.io"}


def _assert_testnet(base):
    """Жёсткая проверка: запрещаем private, если хост не TestNet (защита от боевого)."""
    host = base.split("//", 1)[-1].split("/", 1)[0]
    if host not in TESTNET_HOSTS:
        raise PermissionError(f"private-путь разрешён ТОЛЬКО на TestNet-хосте, получен: {host}")


class GateioFuturesPublic:
    """Публичные данные фьючерсов (без ключей). По умолчанию — TestNet."""
    def __init__(self, base=TESTNET_BASE, timeout=15.0):
        self.base = base
        self._c = httpx.Client(base_url=base, timeout=timeout, headers={"Accept": "application/json"})

    def close(self):
        self._c.close()

    def availability(self):
        """Программная таблица доступности public endpoints (реальные запросы, не предположения)."""
        checks = {
            "contracts": "/futures/usdt/contracts?limit=1",
            "tickers": "/futures/usdt/tickers?contract=BTC_USDT",
            "order_book": "/futures/usdt/order_book?contract=BTC_USDT&limit=1",
            "candlesticks": "/futures/usdt/candlesticks?contract=BTC_USDT&interval=1h&limit=1",
            "funding_rate": "/futures/usdt/funding_rate?contract=BTC_USDT&limit=1",
        }
        out = {}
        for name, path in checks.items():
            try:
                r = self._c.get(V4 + path)
                out[name] = {"status": r.status_code, "ok": r.status_code == 200}
            except Exception as e:
                out[name] = {"status": 0, "ok": False, "error": str(e)[:60]}
        return {"host": self.base, "endpoints": out,
                "public_ready": all(v["ok"] for v in out.values())}

    def contract(self, name="BTC_USDT"):
        r = self._c.get(f"{V4}/futures/usdt/contracts")
        r.raise_for_status()
        for c in r.json():
            if c["name"] == name:
                return {
                    "name": c["name"], "type": c.get("type"),
                    "quanto_multiplier": float(c.get("quanto_multiplier", 0) or 0),
                    "tick_size": c.get("order_price_round"),
                    "order_size_min": c.get("order_size_min"),
                    "leverage_min": c.get("leverage_min"), "leverage_max": c.get("leverage_max"),
                    "maker_fee": float(c.get("maker_fee_rate", 0) or 0),
                    "taker_fee": float(c.get("taker_fee_rate", 0) or 0),
                    "mark_price": float(c.get("mark_price", 0) or 0),
                    "index_price": float(c.get("index_price", 0) or 0),
                    "funding_rate": float(c.get("funding_rate", 0) or 0),
                    "funding_interval": c.get("funding_interval"),
                    "maintenance_rate": c.get("maintenance_rate"),
                    "status": c.get("in_delisting"),
                }
        return None


class GateioFuturesPrivate:
    """ПРИВАТНОЕ исполнение фьючерсов на TestNet. Требует TestNet-ключей владельца.
    Hostname-safety: работает ТОЛЬКО на TestNet-хосте. Отдельный префикс client order ID."""
    CID_PREFIX = "t-tn"        # TestNet-префикс (отделён от mainnet/paper)

    def __init__(self, api_key, api_secret, base=TESTNET_BASE, live_testnet_enabled=False):
        _assert_testnet(base)                      # запрет боевого хоста
        if not (api_key and api_secret):
            raise ValueError("нужны TestNet-ключи (создание аккаунта/ключей — действие владельца)")
        self._key, self._secret, self.base = api_key, api_secret, base
        self.enabled = bool(live_testnet_enabled)
        self._c = httpx.Client(base_url=base, timeout=20.0)

    def close(self):
        self._c.close()

    def _private(self, method, path, query="", body=""):
        headers = sign_request(method, V4 + path, query, body, self._key, self._secret)
        url = V4 + path + (("?" + query) if query else "")
        r = self._c.request(method, url, headers=headers, content=body or None)
        r.raise_for_status()
        return r.json()

    def accounts(self):
        return self._private("GET", "/futures/usdt/accounts")

    def positions(self):
        return self._private("GET", "/futures/usdt/positions")

    # мутирующие — только при явном включении (даже на TestNet)
    def place_order(self, contract, size, price=None, tif="gtc", reduce_only=False, text=None):
        if not self.enabled:
            raise PermissionError("TestNet-ордера отключены: нужен live_testnet_enabled=True")
        import json as _j
        body = {"contract": contract, "size": int(size), "tif": tif,
                "reduce_only": reduce_only, "text": text or f"{self.CID_PREFIX}-{time.time_ns()%10**10}"}
        if price is not None:
            body["price"] = str(price)
        return self._private("POST", "/futures/usdt/orders", body=_j.dumps(body))
