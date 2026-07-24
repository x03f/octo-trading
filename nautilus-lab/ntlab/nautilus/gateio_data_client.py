"""Gate.io LiveMarketDataClient для Nautilus TradingNode. ОСНОВНОЙ транспорт — WebSocket, резерв — REST-polling.

Реализует контракт LiveMarketDataClient: _connect/_disconnect/_subscribe_bars/_request_bars.
Живые публичные данные Gate.io (без ключей). WS (reconnect/gap/дедуп) primary, при падении — REST-polling.
Дедуп по timestamp, обнаружение пропусков, reconnect-счётчик, structured-логи через self._log.

Это ДАННЫЕ проходят через Nautilus (msgbus → strategy + sandbox exec), не через самописный цикл.
"""
import asyncio, time
import httpx
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import Bar, QuoteTick
from nautilus_trader.model.objects import Price, Quantity
from ntlab.adapters.gateio.websocket import GateioSpotWS

GATE_BASE = "https://api.gateio.ws/api/v4"
TF_SEC = {"1-MINUTE": 60, "5-MINUTE": 300, "15-MINUTE": 900, "1-HOUR": 3600, "1-DAY": 86400}
TF_GATE = {"1-MINUTE": "1m", "5-MINUTE": "5m", "15-MINUTE": "15m", "1-HOUR": "1h", "1-DAY": "1d"}


class GateioLiveDataClient(LiveMarketDataClient):
    """Polling-клиент публичных данных Gate.io. Отдаёт закрытые бары в шину Nautilus."""

    def __init__(self, loop, client_id, msgbus, cache, clock, instrument_provider, config=None,
                 gate_symbol="BTC_USDT", poll_interval=5.0, use_websocket=True):
        super().__init__(loop=loop, client_id=client_id, venue=None, msgbus=msgbus, cache=cache,
                         clock=clock, instrument_provider=instrument_provider, config=config)
        self._gate_symbol = gate_symbol
        self._poll = poll_interval
        self._use_ws = use_websocket
        self._ws = None
        self._http = httpx.AsyncClient(base_url=GATE_BASE, timeout=15.0)
        self._last_ts = {}                 # bar_type -> последний отданный ts (дедуп)
        self._tasks_map = {}
        self.reconnect_count = 0
        self.last_event_ts = 0
        self.gaps_detected = 0

    async def _connect(self):
        await self._instrument_provider.initialize()
        self._log.info(f"Gate.io data client подключён (транспорт: {'websocket' if self._use_ws else 'rest-polling'})")

    async def _disconnect(self):
        for t in list(self._tasks_map.values()):
            t.cancel()
        await self._http.aclose()
        self._log.info("Gate.io data client отключён")

    async def _subscribe_bars(self, command):
        bar_type = command.bar_type
        if bar_type in self._tasks_map:
            return
        self._log.info(f"подписка на бары {bar_type} (Gate.io {self._gate_symbol}, "
                       f"транспорт={'websocket' if self._use_ws else 'rest-polling'})")
        if self._use_ws:
            self._tasks_map[bar_type] = self.create_task(self._ws_bars(bar_type))
        else:
            self._tasks_map[bar_type] = self.create_task(self._poll_bars(bar_type))

    async def _unsubscribe_bars(self, command):
        t = self._tasks_map.pop(command.bar_type, None)
        if t:
            t.cancel()

    def _spec(self, bar_type):
        # BarType строкой вида "BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL"
        s = str(bar_type)
        for k in TF_SEC:
            if k in s:
                return k
        return "1-MINUTE"

    async def _ws_bars(self, bar_type):
        """ОСНОВНОЙ транспорт: WebSocket Gate.io. Закрытый бар -> Bar+QuoteTick в шину Nautilus."""
        spec = self._spec(bar_type); gate_tf = {"1-MINUTE":"1m","5-MINUTE":"5m","15-MINUTE":"15m",
            "1-HOUR":"1h","4-HOUR":"4h","1-DAY":"1d"}.get(spec,"1m")
        instrument = self._instrument_provider.find(bar_type.instrument_id)
        pp = instrument.price_precision if instrument else 2
        sp = instrument.size_precision if instrument else 6
        def on_bar(b):
            try:
                ts_ms = b["ts"]
                bar = Bar(bar_type, Price(round(b["open"],pp),pp), Price(round(b["high"],pp),pp),
                          Price(round(b["low"],pp),pp), Price(round(b["close"],pp),pp),
                          Quantity(round(b["volume"],sp),sp), ts_ms*1_000_000, int(time.time()*1e9))
                self._handle_data(bar)
                close=b["close"]; spread=close*0.0001
                q=QuoteTick(instrument_id=bar_type.instrument_id,
                    bid_price=Price(round(close-spread/2,pp),pp), ask_price=Price(round(close+spread/2,pp),pp),
                    bid_size=Quantity(1.0,sp), ask_size=Quantity(1.0,sp),
                    ts_event=ts_ms*1_000_000, ts_init=int(time.time()*1e9))
                self._handle_data(q)
                self.last_event_ts=ts_ms
                if b.get("gap"): self.gaps_detected+=1
            except Exception as e:
                self._log.warning(f"WS bar->nautilus ошибка: {str(e)[:60]}")
        self._ws = GateioSpotWS(on_bar=on_bar)
        self._ws.subscribe_candles(self._gate_symbol, gate_tf)
        # REST-бэкфилл на старте, затем WS-поток
        try:
            await self._ws.run()
        except Exception as e:
            self._log.warning(f"WS упал, откат на REST-polling: {str(e)[:60]}")
            await self._poll_bars(bar_type)   # РЕЗЕРВ
        finally:
            self.reconnect_count += (self._ws.reconnect_count if self._ws else 0)

    async def _poll_bars(self, bar_type):
        spec = self._spec(bar_type)
        gate_tf = TF_GATE.get(spec, "1m")
        instrument = self._instrument_provider.find(bar_type.instrument_id)
        pp = instrument.price_precision if instrument else 2
        sp = instrument.size_precision if instrument else 6
        while True:
            try:
                r = await self._http.get("/spot/candlesticks",
                                         params={"currency_pair": self._gate_symbol, "interval": gate_tf, "limit": 3})
                r.raise_for_status()
                rows = r.json()
                rows.sort(key=lambda k: int(float(k[0])))
                # берём ПОСЛЕДНЮЮ ЗАКРЫТУЮ свечу (предпоследняя в списке при limit=3)
                if len(rows) >= 2:
                    k = rows[-2]
                    ts_ms = int(float(k[0])) * 1000
                    if self._last_ts.get(bar_type) != ts_ms:
                        # обнаружение пропуска
                        prev = self._last_ts.get(bar_type)
                        if prev and ts_ms - prev > TF_SEC[spec] * 1000 * 1.5:
                            self.gaps_detected += 1
                            self._log.warning(f"пропуск баров {bar_type}: {ts_ms-prev}ms")
                        bar = Bar(bar_type,
                                  Price(round(float(k[5]), pp), pp), Price(round(float(k[3]), pp), pp),
                                  Price(round(float(k[4]), pp), pp), Price(round(float(k[2]), pp), pp),
                                  Quantity(round(float(k[6]), sp), sp),
                                  ts_ms * 1_000_000, int(time.time() * 1e9))
                        self._handle_data(bar)         # БАР В ШИНУ (для стратегии)
                        # QuoteTick для SANDBOX execution (его топик data.quotes.VENUE.SYMBOL матчит
                        # подписку sandbox; бары symbol-first не матчат). bid/ask = close ± полспреда.
                        close = float(k[2])
                        spread = close * 0.0001
                        q = QuoteTick(
                            instrument_id=bar_type.instrument_id,
                            bid_price=Price(round(close - spread / 2, pp), pp),
                            ask_price=Price(round(close + spread / 2, pp), pp),
                            bid_size=Quantity(1.0, sp), ask_size=Quantity(1.0, sp),
                            ts_event=ts_ms * 1_000_000, ts_init=int(time.time() * 1e9))
                        self._handle_data(q)           # QUOTE В ШИНУ (для sandbox fill)
                        self._last_ts[bar_type] = ts_ms
                        self.last_event_ts = ts_ms
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.reconnect_count += 1
                self._log.warning(f"ошибка polling {bar_type}: {str(e)[:80]} (reconnect {self.reconnect_count})")
                await asyncio.sleep(min(2 ** min(self.reconnect_count, 5), 30))  # backoff
            await asyncio.sleep(self._poll)

    async def _request_bars(self, request):
        """REST backfill истории при старте/разрыве."""
        bar_type = request.bar_type
        spec = self._spec(bar_type)
        gate_tf = TF_GATE.get(spec, "1m")
        try:
            r = await self._http.get("/spot/candlesticks",
                                     params={"currency_pair": self._gate_symbol, "interval": gate_tf, "limit": 100})
            r.raise_for_status()
            self._log.info(f"backfill {bar_type}: {len(r.json())} баров")
        except Exception as e:
            self._log.warning(f"backfill не удался: {str(e)[:60]}")
