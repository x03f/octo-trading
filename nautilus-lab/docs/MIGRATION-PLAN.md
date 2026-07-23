# План миграции NautilusTrader

# План реализации: Nautilus Trading Lab (миграция OctoBot → NautilusTrader 1.230.0)

## Ключевой факт, определяющий всё

Nautilus даёт архитектуру «один код стратегии — три режима» бесплатно (это его штатная модель). Дорого и итеративно — только одно: **своего адаптера Gate.io в комплекте НЕТ**, его пишем сами. Всё остальное — это конфиги и материализация данных. Поэтому приоритет: сначала выжать бэктест-контур (закрыт стандартными классами), параллельно долго строить Gate.io-адаптер.

---

## (1) Целевая структура проекта — `octo-trading` репо

```
nautilus_lab/
├── pyproject.toml            # deps: nautilus_trader==1.230.0 (пин!), optuna, msgspec
├── lab/
│   ├── strategies/           # ОДИН код на все режимы
│   │   ├── s11_short_after_listing.py   # Strategy + StrategyConfig
│   │   ├── s5_pendulum.py               # BB mean-reversion (аналог examples/BBMeanReversion)
│   │   ├── s4_turtle.py                 # Donchian breakout
│   │   └── base.py                      # общий mixin (логирование, guardrails)
│   ├── models/               # честность движка = сюда
│   │   ├── fees.py           # кастомный FeeModel (косто-модель numpy-движка 1:1)
│   │   └── fills.py          # кастомный FillModel (слиппедж/queue под Gate)
│   ├── data/
│   │   ├── wrangler.py       # parquet-озеро → ParquetDataCatalog
│   │   └── liquidity_passport.py  # maker/taker/precision/min_notional per монета
│   ├── configs/              # конверты прогонов
│   │   ├── venue_gateio.py   # BacktestVenueConfig / SandboxExecutionClientConfig
│   │   ├── backtest.py       # сборка BacktestRunConfig
│   │   └── live.py           # сборка TradingNodeConfig (sandbox/live тумблер)
│   ├── adapters/gateio/      # НАШ адаптер (см. п.3)
│   │   ├── core.py           # GATEIO = Venue('GATEIO'), константы, интервалы ТФ
│   │   ├── config.py         # GateioDataClientConfig / GateioExecClientConfig
│   │   ├── factories.py      # GateioLiveDataClientFactory / ...ExecClientFactory
│   │   ├── providers.py      # GateioInstrumentProvider
│   │   ├── http.py           # v4 REST + HMAC-SHA512 подпись
│   │   ├── websocket.py      # WS v4 + reconnect/resubscribe
│   │   ├── data.py           # GateioLiveMarketDataClient
│   │   └── execution.py      # GateioLiveExecutionClient (сначала scaffold)
│   ├── research/             # автовалидация/WFO (см. п.5)
│   │   ├── wfo.py            # walk-forward orchestration
│   │   ├── optimize.py       # Optuna parameter search
│   │   ├── validate.py       # verdict-гейты (OOS-деградация, survivorship)
│   │   └── registry.py       # реестр стратегий {id → ImportableStrategyConfig}
│   ├── run_backtest.py       # CLI: BacktestNode
│   ├── run_paper.py          # CLI: TradingNode environment='sandbox'
│   └── run_live.py           # CLI: TradingNode environment='live' (позже)
├── catalog/                  # НАТИВНЫЙ Nautilus-parquet (материализация озера)
├── results/                  # артефакты прогонов (parquet) → дашборд без пере-прогона
└── tests/
    ├── test_signature.py     # подпись Gate v4 против примера из доков
    ├── test_ws_parsers.py    # моки WS-payload → Nautilus-типы
    └── test_engine_parity.py # PnL numpy-движок vs Nautilus < допуска
```

Принцип «прогон → артефакт (results/*.parquet) → терминальный дашборд читает без пере-прогона» — берём как есть у DanRedelien/backtesting-engine.

---

## (2) ОДИН код стратегии в backtest/paper/live — конкретные классы

Стратегия пишется **ровно один раз** как:

```python
# lab/strategies/s11_short_after_listing.py
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.trading.config import StrategyConfig

class S11Config(StrategyConfig):
    instrument_id: str
    bar_type: str
    lookback: int = 20
    # ... параметры

class S11ShortAfterListing(Strategy):
    def on_start(self): self.subscribe_bars(...)
    def on_bar(self, bar): ...  # логика шорта после листинга, self.order_factory / self.submit_order()
    def on_stop(self): ...
```

Подключение во **всех** режимах — через один и тот же объект:

```python
from nautilus_trader.config import ImportableStrategyConfig
s11 = ImportableStrategyConfig(
    strategy_path="lab.strategies.s11_short_after_listing:S11ShortAfterListing",
    config_path="lab.strategies.s11_short_after_listing:S11Config",
    config={"instrument_id": "BTC_USDT.GATEIO", "bar_type": "...", "lookback": 20},
)
```

| Режим | Обёртка (что меняется) | Класс исполнения |
|---|---|---|
| **BACKTEST** | `BacktestNode(configs=[BacktestRunConfig(engine=BacktestEngineConfig(strategies=[s11]), data=[BacktestDataConfig(catalog_path=...)], venues=[BacktestVenueConfig(name='GATEIO', account_type='CASH', fee_model=..., fill_model=..., latency_model=...)])]).run()` | встроенный matching engine |
| **PAPER** | `TradingNode(TradingNodeConfig(environment='sandbox', strategies=[s11], data_clients={'GATEIO': <live public>}, exec_clients={'GATEIO': SandboxExecutionClientConfig(account_type='CASH', starting_balances=['10_000 USDT'])}))` | `SandboxExecutionClient` (симфиллы на живых данных) |
| **LIVE** | тот же `TradingNodeConfig`, `environment='live'`, `exec_clients` → боевой `GateioExecClientConfig` | наш `GateioLiveExecutionClient` |

**Код стратегии между режимами не трогается.** Спот Gate.io: `account_type='CASH'`, `oms_type='NETTING'`, `bar_execution=True` (кормим барами).

---

## (3) Порядок реализации Gate.io-адаптера (спот; data → execution)

Чисто-Python адаптер, наследуем от Python-базовых классов, **Rust-ядро не трогаем** (для спота не нужно, не блокирует live позже). Скелет — копия `nautilus_trader/adapters/_template` (в нём 5 файлов: `__init__.py, core.py, data.py, execution.py, providers.py`; раскладку `config.py/constants.py/factories.py` подсматриваем у binance/bybit — в _template их НЕТ).

**Фаза A — транспорт и инструменты (фундамент):**
1. `http.py`: REST v4 + подпись HMAC-SHA512. `signature_string = METHOD\nPATH\nQUERY\nSHA512(body)\nTIMESTAMP`, заголовки `KEY/Timestamp/SIGN`. Публичные вызовы без подписи. → тест против примера из доков Gate.
2. `providers.py`: `GateioInstrumentProvider(InstrumentProvider)`. Реализовать **только** `load_all_async` (`load_ids_async/load_async` имеют дефолт в базовом классе, делегируют в load_all). `GET /spot/currency_pairs` → `CurrencyPair` (precision, amount_precision, min_quote_amount→min_notional, maker/taker fee из паспорта ликвидности). Символ Gate — `BTC_USDT` (underscore), держим единый `raw_symbol`.

**Фаза B — data client (закрывает задачу #29 «data public»):**
3. `data.py`: `GateioLiveMarketDataClient(LiveMarketDataClient)`. Обязательно `_connect/_disconnect`. Subscribe: `_subscribe_trade_ticks` (spot.trades), `_subscribe_bars` (spot.candlesticks), `_subscribe_quote_ticks` (spot.book_ticker), `_subscribe_order_book_deltas` (на старте — периодический снапшот `spot.order_book`, инкремент `order_book_update` позже с тестами sequence). `_subscribe_funding_rates` → **no-op на споте**. Отдача через `self._handle_data/_handle_bars`.
4. History: `_request_bars` (`GET /spot/candlesticks` с from/to, пагинация, лимит ~1000 точек), `_request_trade_ticks`, `_request_order_book_snapshot` — мост к нашему parquet-озеру (сверка/догрузка).
5. `config.py + factories.py`, регистрация `node.add_data_client_factory('GATEIO', ...)`. Запустить live-data-узел на чтение, проверить поток свечей в Cache.

**Фаза C — execution scaffold (без ключей):**
6. `execution.py`: `GateioLiveExecutionClient(LiveExecutionClient)`. Сначала **реконсиляция-репорты**: `generate_order_status_reports` (`/spot/open_orders`), `generate_fill_reports` (`/spot/my_trades`), `generate_position_status_reports` (`/spot/accounts`). `_submit_order/_cancel_order` → пока `log + generate_order_rejected('trading disabled')`.

**Фаза D — приватный контур (когда владелец введёт ключи):**
7. Приватный WS: `auth={method:'api_key', KEY, SIGN(HMAC_SHA512(secret,'channel=..&event=..&time=..'))}`, каналы `spot.orders/spot.usertrades/spot.balances` → `generate_order_accepted/filled` + `AccountState`. Тела `_submit_order/_modify_order/_cancel_order`. Rate-limits — читать заголовки `X-Gate-RateLimit-*/Requests-Remain`, адаптивный троттлинг, на 429 бэкофф.

> **Честно: это самый большой и многоитерационный кусок.** Фазы A–B — рабочий data-контур за разумный срок. Фазы C–D (особенно корректная сборка инкрементального стакана и приватный WS) — классические источники багов, требуют тестов на sequence и реальных замеров latency. Не блокирует бэктест и paper (paper держим на Sandbox-филлах, пока exec-клиент scaffold).

---

## (4) Загон parquet-озера в ParquetDataCatalog

Это **отдельная материализация** в нативный Nautilus-parquet (не чтение сырых parquet напрямую) — дубликат озера (~316 монет × 5 ТФ), нужно место + ETL-шаг.

`lab/data/wrangler.py`:
```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler

catalog = ParquetDataCatalog("catalog/")
for coin in coins:
    inst = build_currency_pair(coin, passport)   # maker/taker/precision/min_notional
    catalog.write_data([inst])
    for tf in tfs:
        df = read_lake_parquet(coin, tf)          # колонки open/high/low/close/volume + ts-индекс
        bars = BarDataWrangler(bar_type, inst).process(df)
        catalog.write_data(bars)
# funding — нативная поддержка!
catalog.write_data(funding_rates_objects)         # читается через catalog.funding_rates()
catalog.consolidate_catalog_by_period()           # схлопнуть мелкие файлы после массовой заливки
```

Ключевое: `catalog.funding_rates()` есть нативно — наши funding-данные ложатся прямо. Для озера больше RAM — потоковый путь: `BacktestNode + ParquetDataCatalog` сам чанкует, либо низкоуровневый `engine.add_data_iterator()` + `engine.run(streaming=True)`.

**Комиссии/точность — на объекте Instrument, НЕ глобально.** Если паспорт ликвидности (maker/taker/price_increment/size_increment/min_notional) не перенести в `CurrencyPair`, бэктест разойдётся с боевыми ордерами (эту граблю уже проходили в folio с округлением).

---

## (5) Adaptive AI Strategy с автовалидацией

Каркас research-слоя (`lab/research/`), собранный из паттернов DanRedelien + mwk96/cross-asset-trend-following:

**Скелет цикла:**
1. **Registry** — `{strategy_id → ImportableStrategyConfig}`. Стратегия параметризуется через `config={dict}`, не хардкодом.
2. **WFO harness** (`wfo.py`) — walk-forward only, no look-ahead. **Subprocess-изоляция на каждую комбинацию параметров** (паттерн mwk96 — гоняем `BacktestNode` в отдельном процессе, чтобы состояние не текло между прогонами).
3. **Optuna** (`optimize.py`) — parameter search внутри каждого train-окна WFO; на OOS-окне параметры зафиксированы.
4. **Verdict-гейты** (`validate.py`) — автоматический вердикт «годна/нет»:
   - деградация OOS vs IS не хуже порога (full-data завышает метрики в 2–3× — это подтверждено методикой #24);
   - тест на чистом survivorship-корректном срезе (задача #24);
   - `synthetic_data_pnl_test`-паттерн — прогон на синтетике для проверки честности движка;
   - **engine parity gate**: PnL S11 в numpy-движке vs Nautilus < допуска (иначе всё дальнейшее недостоверно).
5. **Артефакты** — verdict-heatmap в `results/*.parquet`, дашборд читает без пере-прогона.

«AI» часть (авто-подбор/генерация конфигов стратегий) навешивается **поверх** этого цикла: LLM/оптимайзер предлагает `config={dict}`, WFO+verdict-гейты его отбраковывают автоматически. Мета-стратегия типа «Оркестр» (S6) строится на actor-слое + msgbus (`examples/example_*/messaging_with_msgbus`, `actor_signals`) — сигналы стратегий голосуют через шину.

> **Честно: это большое, многоитерационное.** Сам механизм WFO + Optuna + гейты — обозримо (есть два готовых community-чертежа). «Adaptive AI» с автогенерацией и надёжной автовалидацией без переобучения — исследовательская задача на много итераций; начинать надо с детерминированного WFO-ядра и engine-parity, «AI» добавлять только когда парити и гейты доказаны.

---

## (6) Skills / MCP — что реально ставить

**Ставить (прямая ценность):**
- **skill `backtesting-frameworks`** — прямо в цель: look-ahead / survivorship / transaction costs. Использовать при построении WFO и verdict-гейтов (п.5). Это единственный skill с 1:1 релевантностью.

**Возможно полезно точечно:**
- **skill `xlsx` / `dataviz`** — только для выгрузки/визуализации verdict-heatmap и метрик, если понадобится отчёт вне дашборда. Не приоритет.
- **MCP `scheduled-tasks` / skill `schedule`** — для фоновых задач (пересчёт стратегий, сбор озера данных) вместо ручного запуска. Ложится на существующие фоновые контуры OctoBot-лаба.

**НЕ ставить (нерелевантно задаче):** docx/pptx/pdf, morning, chrome-браузер, claude-api, artifact-* — к миграции движка отношения не имеют.

**Не «skill/MCP», а прямая зависимость проекта:** `optuna` (parameter search), `nautilus_trader==1.230.0` (пин версии — Beta, API течёт между минорами; верить интроспекции установленного пакета, а не докам: docstring `LatencyModel` уже врёт про дефолт 1 с, реально 1 мс).

---

## Приоритизация (по ценности)

| # | Работа | Ценность | Объём | Когда |
|---|---|---|---|---|
| 1 | Wrangler озера → ParquetDataCatalog (п.4) | Высокая | Средний | Сразу |
| 2 | Кастомные FeeModel/FillModel + **engine parity gate** | Высокая | Средний | Сразу (без парити всё недостоверно) |
| 3 | S11 как `Strategy`+`StrategyConfig`, прогон `BacktestNode` | Высокая | Малый | Сразу |
| 4 | Gate.io adapter Фаза A–B (data public, #29) | Высокая | **Большой, итеративный** | Параллельно с 1–3 |
| 5 | WFO + Optuna + verdict-гейты (п.5, ядро) | Высокая | Средний | После 1–3 |
| 6 | Paper-узел Sandbox (#30, филлы на Sandbox, данные — наш data-client или Tardis) | Средняя | Малый | После 4-B |
| 7 | Gate.io adapter Фаза C–D (execution, приватный WS) | Средняя | **Большой, риск-баги** | С ключами владельца |
| 8 | Adaptive-AI слой поверх WFO | Средняя | **Большой, исследовательский** | После 5 доказан |
| 9 | Persistence на PostgreSQL 17 (`PostgresCacheDatabase`, load/save_state) | Низкая | Малый | Опц., если нужна живучесть live между рестартами (Redis нет — ок) |

**Три вещи, которые не «конфиг», а реальная инженерия и много итераций:** (а) Gate.io execution + инкрементальный стакан (п.3 C–D), (б) engine parity numpy↔Nautilus до сходимости (без него бэктест/paper/боевые разойдутся), (в) Adaptive-AI автовалидация без переобучения. Всё остальное — стандартные классы Nautilus и материализация данных.

Релевантные пути (в целевом репо `octo-trading`): `nautilus_lab/lab/adapters/gateio/`, `nautilus_lab/lab/data/wrangler.py`, `nautilus_lab/lab/models/{fees,fills}.py`, `nautilus_lab/lab/research/`, `nautilus_lab/catalog/`. Скелет адаптера копировать из установленного `nautilus_trader/adapters/_template/` (5 файлов), раскладку config/factories — из `adapters/binance`.