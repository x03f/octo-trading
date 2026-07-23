"""Подпись запросов Gate.io API v4 (HMAC-SHA512). Чистая функция — тестируется без ключей и сети.

Спека Gate.io v4:
  s = METHOD \n URL_PATH \n QUERY \n SHA512(body_hex) \n TIMESTAMP
  SIGN = HMAC_SHA512(secret, s)
  заголовки: KEY, Timestamp, SIGN
Публичные эндпоинты подписи не требуют.
"""
import hashlib
import hmac
import time


def sign_request(method: str, url_path: str, query: str = "", body: str = "",
                 api_key: str = "", api_secret: str = "", timestamp: str | None = None) -> dict:
    """Возвращает заголовки авторизации. timestamp можно зафиксировать для детерминированного теста."""
    t = timestamp if timestamp is not None else str(int(time.time()))
    hashed_payload = hashlib.sha512((body or "").encode()).hexdigest()
    signature_string = f"{method.upper()}\n{url_path}\n{query}\n{hashed_payload}\n{t}"
    sign = hmac.new((api_secret or "").encode(), signature_string.encode(), hashlib.sha512).hexdigest()
    return {"KEY": api_key, "Timestamp": t, "SIGN": sign,
            "Content-Type": "application/json", "Accept": "application/json"}


def client_order_id(prefix: str = "ntlab") -> str:
    """Клиентский ID ордера (Gate.io поле `text`, требует префикс 't-'). Уникален по времени+счётчику.
    Используется для идемпотентности: повторная отправка с тем же text отклоняется биржей."""
    # Gate.io: text должен начинаться с 't-', длина ≤ 28, [0-9a-zA-Z_-.]
    ns = time.time_ns()
    return f"t-{prefix}-{ns % 10**12}"
