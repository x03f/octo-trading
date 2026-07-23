"""Gate.io API v4 — публичные рыночные данные (спот). Работает БЕЗ ключей.

Первая (data) половина адаптера: инструменты, свечи, сделки, стакан. Приватная половина
(balances/orders/fills) — в execution.py, требует ключей. Реалистичный paper использует
именно этот живой поток данных Gate.io.

Док: https://www.gate.io/docs/developers/apiv4/  (spot: /spot/currency_pairs, /spot/candlesticks, /spot/trades, /spot/order_book)
"""
import time
import httpx

BASE = "https://api.gateio.ws/api/v4"
# соответствие наших ТФ интервалам Gate.io
TF_MAP = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}


class GateioData:
    def __init__(self, timeout=20.0):
        self._c = httpx.Client(base_url=BASE, timeout=timeout,
                               headers={"Accept": "application/json"})

    def close(self):
        self._c.close()

    def ping(self):
        """Проверка доступности публичного API + серверное время."""
        t0 = time.time()
        r = self._c.get("/spot/time")
        r.raise_for_status()
        return {"ok": True, "server_time_ms": r.json().get("server_time"),
                "latency_ms": round((time.time() - t0) * 1000)}

    def instruments(self):
        """Все спот-пары с торговыми ограничениями (precision, min_amount, min_notional)."""
        r = self._c.get("/spot/currency_pairs")
        r.raise_for_status()
        out = []
        for p in r.json():
            out.append({
                "symbol": p["id"],                       # BTC_USDT
                "base": p["base"], "quote": p["quote"],
                "amount_precision": p.get("amount_precision"),
                "price_precision": p.get("precision"),
                "min_base_amount": p.get("min_base_amount"),
                "min_quote_amount": p.get("min_quote_amount"),   # ≈ min notional
                "fee": p.get("fee"),
                "trade_status": p.get("trade_status"),
            })
        return out

    def instrument(self, symbol):
        """Ограничения одной пары. symbol в формате BTC_USDT."""
        for i in self.instruments():
            if i["symbol"] == symbol.upper():
                return i
        return None

    def candles(self, symbol, tf="1h", limit=1000, frm=None, to=None):
        """OHLCV свечи. Gate.io отдаёт [ts, volume_quote, close, high, low, open, volume_base, ...]."""
        params = {"currency_pair": symbol.upper(), "interval": TF_MAP.get(tf, tf), "limit": limit}
        if frm: params["from"] = int(frm)
        if to: params["to"] = int(to)
        r = self._c.get("/spot/candlesticks", params=params)
        r.raise_for_status()
        out = []
        for k in r.json():
            out.append({
                "ts": int(float(k[0])) * 1000,           # сек → мс
                "open": float(k[5]), "high": float(k[3]),
                "low": float(k[4]), "close": float(k[2]),
                "volume": float(k[6]),                   # объём в базовой валюте
            })
        out.sort(key=lambda x: x["ts"])
        return out

    def recent_trades(self, symbol, limit=100):
        r = self._c.get("/spot/trades", params={"currency_pair": symbol.upper(), "limit": limit})
        r.raise_for_status()
        return [{"ts": int(float(t["create_time_ms"])), "price": float(t["price"]),
                 "amount": float(t["amount"]), "side": t["side"]} for t in r.json()]

    def order_book(self, symbol, limit=20):
        r = self._c.get("/spot/order_book", params={"currency_pair": symbol.upper(), "limit": limit})
        r.raise_for_status()
        d = r.json()
        return {"bids": [[float(p), float(a)] for p, a in d.get("bids", [])],
                "asks": [[float(p), float(a)] for p, a in d.get("asks", [])],
                "ts": d.get("current")}
