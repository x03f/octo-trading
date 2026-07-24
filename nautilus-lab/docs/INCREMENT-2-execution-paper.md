# Инкремент 2: Gate.io execution adapter + CUSTOM PAPER HARNESS S11

> ⚠️ ТЕРМИНОЛОГИЯ ИСПРАВЛЕНА: `ntlab-paper` — это CUSTOM PAPER HARNESS (прямой Gate.io data +
> собственный PaperExecution + функция сигнала), НЕ Nautilus paper. Настоящий Nautilus runtime —
> отдельный сервис `ntlab-nautilus` (TradingNode). См. INCREMENT-3.

24.07.2026. Всё проверено (`ntlab test` → 27/27, сервисы active). Реальные ордера НЕВОЗМОЖНЫ.

## Что реально работает
### Gate.io adapter — private execution (код + тесты, БЕЗ боевых вызовов)
- `signing.py` — подпись v4 (HMAC-SHA512), детерминированная, `client_order_id` с префиксом `t-`.
- `execution.py` `GateioExecution` — балансы, открытые ордера, ордер по id, my_trades (fills),
  place/cancel. Разбор моделей: partial/rejected/cancelled/filled, maker/taker, комиссии.
  Rate limiter + экспоненциальный backoff на 429. Синхронизация времени с биржей.
  **⚠️ Мутирующие вызовы (place/cancel) кидают `LiveDisabledError` без `live_enabled=True`.**
- `reconcile.py` — сверка локального состояния с биржей после рестарта (диагностика без мутаций).
- Gate.io СПОТОВОГО публичного testnet нет, НО ФЬЮЧЕРСНЫЙ TestNet ЕСТЬ и работает
  (api-testnet.gateapi.io — контракты/стакан/свечи/funding 200). Поправка к прежнему выводу.

### Paper execution — симуляция на ЖИВЫХ данных Gate.io (не биржа)
- `paper.py` `PaperExecution` (SIMULATION=True) — заполнение по реальному стакану Gate.io с
  проскальзыванием (обход глубины), комиссии taker/maker, min_notional/precision из инструмента,
  частичные заполнения при тонком стакане.

### Custom paper harness S11 — systemd `ntlab-paper` (Restart=always) — НЕ Nautilus
- `s11_signal.py` — онлайн-сигнал S11, **100% parity с движком** (2222/2222 бар-позиций).
  Это и есть «один код стратегии»: backtest и paper/live решают идентично.
- `service.py` `S11PaperService` — тянет живые дневные свечи Gate.io, гоняет S11, исполняет
  переходы через PaperExecution. Гейт по возрасту листинга (действует только на СВЕЖИХ).
  Состояние на диске; после рестарта восстанавливается БЕЗ дублей (действие на ИЗМЕНЕНИЕ + дедуп
  client_order_id по дню). Структурные JSON-логи. Статус в API/дашборд.
- `NTLAB_LIVE_ENABLED=false` в юните — явный запрет боевых ордеров.

## Проверено тестами (27/27, `ntlab test`)
| Файл | Тестов | Что покрывает |
|---|---|---|
| test_gateio | 13 | подпись (детерминизм/тело), client_id, live-disabled, разбор partial/rejected/filled/maker-taker, rate-limit backoff, paper комиссии/min/precision/partial |
| test_paper_service | 5 | открытие шорта на свежем листинге, **идемпотентность после рестарта (нет дублей)**, persist+reconcile, статус для API, smoke многотиковый |
| test_reconcile | 5 | in-sync, неизвестный ордер, известный ордер, биржа недоступна, синхронизация времени |
| test_adaptive | 4 | адаптивный цикл (из инкремента 1) |

## Доказательная paper-сделка (replay 0G из озера)
`ntlab paper-logs` / replay: монета 0G, шорт на дне 3 @ 3.917 → откуп на баре 35 @ 1.602
(падение 59%, прибыльный шорт — тезис S11). Объёмы входа/выхода совпадают (51.06 units).

## Сравнение S11 (`ntlab compare-s11`, повторяемо)
S11 в OctoBot НИКОГДА не было (там S8/S4) → «OctoBot S11 vs Nautilus S11» невозможно буквально.
Сверка «один код»: эталон-движок vs paper-сигнал — **сигналы 100% (2222/2222), тайминг входов/
выходов 100% (241/241), сайзинг идентичен**. Разница только в МОДЕЛИ исполнения (движок — close-fill
+ пер-монетный кост; paper — обход стакана Gate.io + taker), не в сигнале. Отдельно: OctoBot S4 vs
Nautilus S4 — 100% совпадение (nautilus_spike/donchian_nautilus.py).

## OctoBot — реальная роль (исправлено)
10 инстансов работают, decommission НЕ запускался.
**OctoBot НЕ валидирует S11** — S11 в OctoBot никогда не было (там S4/S8). Реальная функция OctoBot:
сохранённый рабочий контур S4/S8, регрессионное сравнение общей инфраструктуры, возможность отката.

## Что подготовлено, но не боевое
- `GateioExecution` боевой путь — за `live_enabled=True` + ключами (не заводились).
- Полная интеграция в Nautilus `TradingNode(environment='sandbox')` с зарегистрированным
  Gate.io LiveDataClient — следующий шаг; сейчас paper-сервис использует прямой Gate.io data +
  PaperExecution (тот же сигнал-код, что пойдёт в TradingNode).

## Условия перед отключением OctoBot (ОБЪЕКТИВНЫЕ, не зависящие от невозможного сравнения S11)
1. Nautilus runtime (TradingNode) S11 отработал значимый период и наблюдал ≥1 реальный forward-сигнал.
2. Reconciliation после нескольких рестартов стабильно in-sync.
3. Инфраструктурный регресс: ключевые метрики/пайплайн нового контура не хуже старого.
4. Явное ручное решение владельца.
НЕ требуется «сравнение OctoBot S11» — его не существует. Скрипт decommission_octobot.sh защищён.