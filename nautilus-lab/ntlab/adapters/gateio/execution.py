"""Gate.io API v4 — приватное исполнение (СПОТ). Балансы, ордера, позиции, исполнения, place/cancel.

⚠️ БЕЗОПАСНОСТЬ: реальные ордера НЕВОЗМОЖНЫ без ЯВНОГО переключателя. Конструктор требует
live_enabled=True И наличия ключей; иначе любой мутирующий вызов (place/cancel) кидает исключение.
Публичное чтение (для reconciliation) работает только если явно переданы ключи.

Этот класс покрыт mock-тестами (подпись, разбор моделей, place/cancel/partial/reject), но НЕ
вызывается с боевыми ключами на этом этапе. Непрерывный paper использует PaperExecution (paper.py).
"""
import time
import httpx
from .signing import sign_request, client_order_id

BASE = "https://api.gateio.ws"
V4 = "/api/v4"


class RateLimiter:
    """Простой лимитер: не чаще N запросов в окно, с экспоненциальным backoff при 429."""
    def __init__(self, max_per_sec=8):
        self.min_interval = 1.0 / max_per_sec
        self._last = 0.0
        self._backoff = 0.0

    def wait(self):
        now = time.time()
        gap = now - self._last
        delay = max(0.0, self.min_interval - gap) + self._backoff
        if delay > 0:
            time.sleep(delay)
        self._last = time.time()

    def on_429(self):
        self._backoff = min(self._backoff * 2 + 0.5, 10.0)

    def on_ok(self):
        self._backoff = max(0.0, self._backoff * 0.5)


class GateioExecution:
    def __init__(self, api_key: str, api_secret: str, live_enabled: bool = False,
                 base: str = BASE, max_per_sec: int = 8):
        if not (api_key and api_secret):
            raise ValueError("нужны ключи Gate.io (env GATEIO_API_KEY/SECRET)")
        self._key, self._secret = api_key, api_secret
        self.live_enabled = bool(live_enabled)       # жёсткий переключатель боевых ордеров
        self._base = base
        self._rl = RateLimiter(max_per_sec)
        self._c = httpx.Client(base_url=base, timeout=20.0)
        self._time_offset_ms = 0

    def close(self):
        self._c.close()

    # ---- синхронизация времени с биржей ----
    def sync_time(self):
        r = self._c.get(f"{V4}/spot/time")
        r.raise_for_status()
        server_ms = r.json()["server_time"]
        self._time_offset_ms = server_ms - int(time.time() * 1000)
        return self._time_offset_ms

    def _ts(self):
        return str(int((time.time() * 1000 + self._time_offset_ms) / 1000))

    # ---- низкоуровневый приватный вызов с подписью, лимитом и backoff ----
    def _private(self, method, path, query="", body="", retries=3):
        url_path = V4 + path
        for attempt in range(retries):
            self._rl.wait()
            headers = sign_request(method, url_path, query, body, self._key, self._secret, self._ts())
            url = url_path + (("?" + query) if query else "")
            r = self._c.request(method, url, headers=headers, content=body or None)
            if r.status_code == 429:
                self._rl.on_429()
                continue
            self._rl.on_ok()
            if r.status_code >= 400:
                # понятная ошибка без утечки ключа
                try:
                    err = r.json()
                except Exception:
                    err = {"label": "HTTP", "message": r.text[:200]}
                raise GateioError(r.status_code, err.get("label", ""), err.get("message", ""))
            return r.json()
        raise GateioError(429, "TOO_MANY_REQUESTS", "исчерпаны ретраи по rate-limit")

    # ---- чтение состояния (для reconciliation) ----
    def balances(self):
        data = self._private("GET", "/spot/accounts")
        return {b["currency"]: {"available": float(b["available"]), "locked": float(b["locked"])} for b in data}

    def open_orders(self, currency_pair=None):
        q = f"currency_pair={currency_pair}" if currency_pair else ""
        data = self._private("GET", "/spot/open_orders", query=q)
        return [self._parse_order(o) for grp in (data if isinstance(data, list) else [])
                for o in (grp.get("orders", []) if isinstance(grp, dict) else [grp])]

    def order(self, order_id, currency_pair):
        o = self._private("GET", f"/spot/orders/{order_id}", query=f"currency_pair={currency_pair}")
        return self._parse_order(o)

    def my_trades(self, currency_pair, limit=100):
        data = self._private("GET", "/spot/my_trades", query=f"currency_pair={currency_pair}&limit={limit}")
        return [self._parse_fill(t) for t in data]

    # ---- мутирующие вызовы: ТОЛЬКО при live_enabled ----
    def place_order(self, currency_pair, side, amount, price=None, order_type="limit", text=None):
        self._require_live()
        text = text or client_order_id()
        body = {"currency_pair": currency_pair, "side": side, "amount": str(amount),
                "type": order_type, "text": text, "time_in_force": "gtc"}
        if order_type == "limit":
            body["price"] = str(price)
        import json as _j
        o = self._private("POST", "/spot/orders", body=_j.dumps(body))
        return self._parse_order(o)

    def cancel_order(self, order_id, currency_pair):
        self._require_live()
        o = self._private("DELETE", f"/spot/orders/{order_id}", query=f"currency_pair={currency_pair}")
        return self._parse_order(o)

    def _require_live(self):
        if not self.live_enabled:
            raise LiveDisabledError("боевые ордера отключены: нужен явный live_enabled=True + подтверждение")

    # ---- инструменты: точность и минимальные размеры (публично, для валидации ордеров) ----
    def instrument(self, currency_pair):
        r = self._c.get(f"{V4}/spot/currency_pairs/{currency_pair}")
        r.raise_for_status()
        d = r.json()
        return {"pair": d.get("id"), "base": d.get("base"), "quote": d.get("quote"),
                "amount_precision": int(d.get("amount_precision", 8)),
                "price_precision": int(d.get("precision", 8)),
                "min_base_amount": float(d.get("min_base_amount", 0) or 0),
                "min_quote_amount": float(d.get("min_quote_amount", 0) or 0),   # min notional
                "trade_status": d.get("trade_status"), "maker_fee": float(d.get("fee", 0) or 0)}

    @staticmethod
    def validate_order(spec, side, amount, price):
        """Проверка против ограничений биржи: min amount, min notional, precision, торгуемость.
        Возвращает нормализованные (amount, price) или кидает OrderValidationError."""
        errs = []
        amt = round(float(amount), spec["amount_precision"])
        px = round(float(price), spec["price_precision"]) if price is not None else None
        if spec["min_base_amount"] > 0 and amt < spec["min_base_amount"]:
            errs.append(f"amount {amt} < min_base_amount {spec['min_base_amount']}")
        if px is not None and spec["min_quote_amount"] > 0 and amt * px < spec["min_quote_amount"]:
            errs.append(f"notional {amt*px:.4f} < min_notional {spec['min_quote_amount']}")
        if spec.get("trade_status") and spec["trade_status"] != "tradable":
            errs.append(f"пара не торгуется (trade_status={spec['trade_status']})")
        if errs:
            raise OrderValidationError("; ".join(errs))
        return amt, px

    def find_by_client_id(self, currency_pair, client_id):
        """Идемпотентность: найти уже открытый ордер по client_id (text) до повторной отправки."""
        for o in self.open_orders(currency_pair):
            if o.get("client_id") == client_id:
                return o
        return None

    def place_order_safe(self, currency_pair, side, amount, price=None, order_type="limit", text=None, spec=None):
        """Валидирующая + ИДЕМПОТЕНТНАЯ обёртка place_order: проверка min/precision по spec и защита
        от дублей (если ордер с таким client_id уже открыт — возвращает его, не создаёт второй)."""
        self._require_live()
        text = text or client_order_id()
        spec = spec or self.instrument(currency_pair)
        amt, px = self.validate_order(spec, side, amount, price if order_type == "limit" else None)
        existing = self.find_by_client_id(currency_pair, text)
        if existing:
            return {**existing, "idempotent": True}
        return self.place_order(currency_pair, side, amt, px if order_type == "limit" else None, order_type, text)

    def cancel_all(self, currency_pair=None):
        """Отменить все открытые ордера (по паре или все) — основа emergency stop."""
        self._require_live()
        out = []
        for o in self.open_orders(currency_pair):
            try:
                out.append(self.cancel_order(o["id"], o["symbol"]))
            except Exception as e:
                out.append({"id": o["id"], "error": str(e)[:60]})
        return out

    def emergency_stop(self, currency_pair=None):
        """АВАРИЙНАЯ ОСТАНОВКА: отменить все ордера и ЖЁСТКО отключить боевой режим.
        После вызова любой мутирующий вызов снова требует явного live_enabled=True."""
        result = {"cancelled": [], "live_disabled": True}
        try:
            if self.live_enabled:
                result["cancelled"] = self.cancel_all(currency_pair)
        finally:
            self.live_enabled = False
        return result

    # ---- нормализация моделей биржи → внутренний формат ----
    @staticmethod
    def _parse_order(o):
        filled = float(o.get("filled_total", 0) or 0)
        amount = float(o.get("amount", 0) or 0)
        st = o.get("status", "")
        # partial: часть исполнена, но не вся
        partial = st == "open" and filled > 0 and filled < amount
        return {
            "id": o.get("id"), "client_id": o.get("text"),
            "symbol": o.get("currency_pair"), "side": o.get("side"),
            "type": o.get("type"), "price": float(o.get("price", 0) or 0),
            "amount": amount, "filled": filled,
            "left": float(o.get("left", 0) or 0),
            "status": st,                                 # open|closed|cancelled
            "partial": partial,
            "fee": float(o.get("fee", 0) or 0), "fee_currency": o.get("fee_currency"),
            "create_time_ms": int(o.get("create_time_ms", 0) or 0),
            "finish_as": o.get("finish_as"),              # filled|cancelled|ioc|...
        }

    @staticmethod
    def _parse_fill(t):
        return {
            "id": t.get("id"), "order_id": t.get("order_id"), "symbol": t.get("currency_pair"),
            "side": t.get("side"), "price": float(t.get("price", 0) or 0),
            "amount": float(t.get("amount", 0) or 0),
            "fee": float(t.get("fee", 0) or 0), "fee_currency": t.get("fee_currency"),
            "role": t.get("role"),                        # maker|taker
            "create_time_ms": int(t.get("create_time_ms", 0) or 0),
        }


class GateioError(Exception):
    def __init__(self, status, label, message):
        self.status, self.label, self.message = status, label, message
        super().__init__(f"Gate.io {status} {label}: {message}")


class LiveDisabledError(Exception):
    pass


class OrderValidationError(Exception):
    """Ордер нарушает ограничения биржи (min amount / min notional / precision / не торгуется)."""
    pass
