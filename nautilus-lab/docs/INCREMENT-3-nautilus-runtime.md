# Инкремент 3: S11 в ФАКТИЧЕСКОМ Nautilus TradingNode (SANDBOX)

24.07.2026. Терминология исправлена; S11 работает как штатная Nautilus Strategy в настоящем
TradingNode; данные/ордера/позиции/portfolio проходят через Nautilus. Реальные ордера НЕВОЗМОЖНЫ.

## Исправления терминологии/логики (сделаны ПЕРВЫМИ)
1. `ntlab-paper` переименован в **custom paper harness** (не Nautilus paper): прямой Gate.io data +
   PaperExecution + функция сигнала, БЕЗ TradingNode/Strategy lifecycle. Остаётся как независимый oracle.
2. **OctoBot НЕ валидирует S11** (S11 там не было). Реальная роль: сохранённый контур S4/S8,
   регрессионное сравнение инфраструктуры, откат. Ложное условие сноса убрано.
3. Поправка: Gate.io ФЬЮЧЕРСНЫЙ TestNet ЕСТЬ (`api-testnet.gateapi.io`, проверено) — спотового публичного нет.

## Что реально работает (доказательства — командами)
### Настоящий Nautilus TradingNode(SANDBOX) — `ntlab-nautilus` (systemd, Restart=always, active)
- **S11Strategy** (`ntlab/nautilus/s11_strategy.py`) — наследник `nautilus_trader.trading.strategy.Strategy`,
  ОДИН класс для BacktestNode и TradingNode. Сигнал/sizing/entry/exit — внутри стратегии (общий s11_signal).
- **GateioLiveDataClient** (`gateio_data_client.py`) — `LiveMarketDataClient`: polling публичных данных
  Gate.io, публикует Bar (стратегии) + QuoteTick (sandbox fill), дедуп по ts, обнаружение пропусков,
  reconnect-счётчик + backoff, structured-логи. Данные идут через шину Nautilus.
- **SandboxExecutionClient** (штатный Nautilus) — simulated execution ВНУТРИ Nautilus.
- Node: `Environment.SANDBOX`, exec — `SandboxLiveExecClientFactory`, data — наш `GateioLiveDataClientFactory`.

### ДОКАЗАННЫЙ полный order lifecycle через Nautilus (lifecycle-proof)
`ntlab lifecycle-proof` (диагностическая TestStrategy на 1m, S11 при этом ждёт реальный сигнал):
```
environment: Environment.SANDBOX | баров получено (живые Gate.io): 4
submit BUY  → filled O-...-1 @ 64956.25  (0.001)
submit SELL → filled O-...-2 @ 64909.75  (0.001)
заполнений через Nautilus: 2 | closed positions: 1 | баланс 100000 → 99999.82
```
submit → accepted → filled → position → portfolio — всё через Nautilus. Плюс тот же S11 class в
BacktestNode дал realized +86 USDT (шорт после листинга 0G).

### Многофакторная защита (live НЕВОЗМОЖЕН по умолчанию) — `safety.py`
Боевой путь требует ОДНОВРЕМЕННО: runtime=live + env NTLAB_LIVE_ENABLED=true + файл-подтверждение
с точной фразой. Из sandbox/paper/backtest боевой exec-client не создаётся в принципе. Тест доказывает.

## Проверено тестами (33/33, `ntlab test`)
- test_nautilus (6): live заблокирован по умолчанию, нужны 3 фактора, sandbox не достаёт live,
  узел собирается в SANDBOX, S11 использует общий сигнал.
- + test_gateio (13), test_paper_service (5), test_reconcile (5), test_adaptive (4).

## Parity BacktestNode vs online-сигнал
S11Strategy использует ntlab.strategies.s11_signal — тот же код, что online (100% parity с движком,
2222/2222, `ntlab compare-s11`). Ожидаемая разница результатов backtest vs sandbox — только из-за
модели исполнения (fill по quote, спред, latency), не из-за сигнала.

## Статус доказанности S11 (честно, `/api/contours`)
`runtime operational, execution validated, forward validation pending`.
- BACKTEST_VALIDATED = да; LOCAL_SANDBOX_OPERATIONAL = да; FORWARD_SIGNAL_OBSERVED = нет;
  ECONOMIC_EDGE_UNPROVEN = да; LIVE_READY = нет; LIVE_BLOCKED = да.
- **replay 0G — ТЕСТ механизма, НЕ forward validation.** Реальный forward начнётся с первого
  сигнала S11 на новом листинге после запуска.

## Что ещё НЕ доказано / ограничения (честно)
- **Websocket** не реализован — data client на REST-polling (WS + gap-recovery по sequence — следующий шаг).
- **Restart с открытой позицией/частичным заполнением В TRADINGNODE** — протестирован persist на уровне
  custom harness (идемпотентность) и strategy-логики; полный TradingNode-state recovery (order IDs,
  avg entry) через Nautilus Cache persistence — не доказан отдельным тестом, помечен как ограничение.
- **Экономический край S11 не доказан** — backtest ≠ forward. Ждём реальный сигнал.
- **Futures TestNet private execution** (разделы 11–14) — требует TestNet-аккаунта и ключей владельца
  (создание аккаунта/ключей — вне моих полномочий). Public data готово; private — за ключами.

## OctoBot
Не тронут (10/10 active), decommission не запускался. Объективные условия сноса — в INCREMENT-2.
