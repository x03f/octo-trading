"""Gate.io Spot WebSocket market data — ОСНОВНОЙ транспорт (REST polling — резерв).

Возможности: подписка на свечи/сделки/стакан, reconnect с экспоненциальным backoff,
дедупликация по timestamp, обнаружение пропусков (gap), корректные метки времени.
Каждый закрытый бар/сделка отдаётся через callback (on_bar / on_trade).

Gate.io v4 WS: wss://api.gateio.ws/ws/v4/ · каналы spot.candlesticks / spot.trades / spot.book_ticker.
Свеча приходит с 'window_close' (bool) — берём только закрытые.
"""
import asyncio, json, time
import websockets

WS_URI = "wss://api.gateio.ws/ws/v4/"
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class GateioSpotWS:
    def __init__(self, on_bar=None, on_trade=None, uri=WS_URI):
        self.on_bar = on_bar
        self.on_trade = on_trade
        self.uri = uri
        self._subs = []                 # список (channel, payload)
        self._last_bar_ts = {}          # (symbol,tf) -> ts (дедуп + gap)
        self.reconnect_count = 0
        self.gaps_detected = 0
        self.messages = 0
        self.last_event_ms = 0
        self._stop = False
        self._backoff = 1.0

    def subscribe_candles(self, symbol, tf="1m"):
        self._subs.append(("spot.candlesticks", [tf, symbol]))

    def subscribe_trades(self, symbol):
        self._subs.append(("spot.trades", [symbol]))

    async def _send_subs(self, ws):
        for ch, payload in self._subs:
            await ws.send(json.dumps({"time": int(time.time()), "channel": ch,
                                      "event": "subscribe", "payload": payload}))

    def _handle_candle(self, result):
        # result: {t, v, c, h, l, o, n:'1m_BTC_USDT', a, w:window_close}
        n = result.get("n", "")
        parts = n.split("_", 1)
        tf = parts[0] if parts else "1m"
        symbol = parts[1] if len(parts) > 1 else result.get("currency_pair", "")
        ts_ms = int(float(result["t"])) * 1000
        key = (symbol, tf)
        # только закрытые свечи; дедуп
        if not result.get("w", result.get("window_close", False)):
            return
        prev = self._last_bar_ts.get(key)
        if prev == ts_ms:
            return                                  # дубль
        if prev and ts_ms - prev > TF_MS.get(tf, 60_000) * 1.5:
            self.gaps_detected += 1                 # пропуск баров
        self._last_bar_ts[key] = ts_ms
        self.last_event_ms = ts_ms
        bar = {"symbol": symbol, "tf": tf, "ts": ts_ms,
               "open": float(result["o"]), "high": float(result["h"]),
               "low": float(result["l"]), "close": float(result["c"]),
               "volume": float(result.get("v", 0) or 0), "gap": bool(prev and ts_ms - prev > TF_MS.get(tf,60_000)*1.5)}
        if self.on_bar:
            self.on_bar(bar)

    async def run(self, max_seconds=None):
        start = time.time()
        while not self._stop:
            try:
                async with websockets.connect(self.uri, open_timeout=10, ping_interval=20) as ws:
                    await self._send_subs(ws)
                    self._backoff = 1.0             # успешное подключение сбрасывает backoff
                    while not self._stop:
                        if max_seconds and time.time() - start > max_seconds:
                            self._stop = True; break
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        self.messages += 1
                        d = json.loads(msg)
                        if d.get("channel") == "spot.candlesticks" and d.get("event") == "update":
                            res = d.get("result")
                            for item in (res if isinstance(res, list) else [res]):
                                if item:
                                    self._handle_candle(item)
                        elif d.get("channel") == "spot.trades" and d.get("event") == "update" and self.on_trade:
                            self.on_trade(d.get("result"))
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._stop:
                    break
                self.reconnect_count += 1
                await asyncio.sleep(min(self._backoff, 30))
                self._backoff = min(self._backoff * 2, 30)   # экспоненциальный backoff

    def stop(self):
        self._stop = True
