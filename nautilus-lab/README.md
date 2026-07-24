# Nautilus Trading Lab

Крипто-трейдинг-лаба на NautilusTrader. Миграция с OctoBot. Нативное развёртывание (systemd + venv,
без Docker — см. `docs/ADR-001-deployment.md`).

## Статус: инкремент 1 (рабочее ядро)
Это ЧЕСТНЫЙ статус, не маркетинг. Полная спецификация — многонедельная; здесь — работающий фундамент.

### ✅ Работает и проверено
- **Backend + дашборд** — FastAPI на `127.0.0.1:5020` (systemd `ntlab-api`, Restart=always).
  9 API-эндпоинтов, дашборд с разделами Overview/Strategies/Backtests/Portfolio/Adaptive/DataLake/System.
- **Аудит озера** — `ntlab data-audit`: 316 монет × 5 ТФ, 73.7M свечей, 4 проблемных ряда (пропуски),
  отчёт качества + известные искажения (survivorship/look-ahead/спред) в `web/data/lake_quality.json`.
- **Gate.io public data adapter** — `ntlab/adapters/gateio/data.py`: инструменты, свечи, сделки, стакан.
  Работает БЕЗ ключей (`ntlab gateio-ping`).
- **Nautilus бэктест** — `nautilus_spike/multi_backtest.py`: S4 Donchian по наборам монет в ОДНОМ
  процессе (majors/niche/aggr). Сигнал сверен с numpy-движком 1:1 (100%).
- **Adaptive AI Strategy (ядро)** — схема (Pydantic) + единый LLM-интерфейс (Claude/OpenAI) +
  детерминированный советник без ключей + автовалидация рекомендаций через лабу + память + событийные
  триггеры. Тест `ntlab adaptive-test`: цикл наблюдение→диагностика→решение→память (4/4).
- **Каталог стратегий** — честные статусы из трёхчастного теста. S11 «Новичок» — единственный кандидат.

### 🔵 Спроектировано, не развёрнуто (следующие инкременты)
- **Gate.io execution adapter** (private: balances/orders/fills/reconciliation) — за ключами, план в
  `docs/MIGRATION-PLAN.md` (фазы A/B/C). Сейчас — только data-половина.
- **Непрерывный Nautilus runtime (TradingNode)** — заменит OctoBot forward-тест. `run_paper.py` (TradingNode
  environment='sandbox' + SandboxExecutionClient на живых данных Gate.io). Пока форвард идёт на OctoBot.
- **Удаление OctoBot** — `scripts/decommission_octobot.sh` ГОТОВ, но ЗАЩИЩЁН: не запускать, пока Nautilus runtime не заменит форвард (OctoBot хранит S4/S8 и даёт откат; S11 он НЕ валидирует). Осознанный запуск: `--i-understand`.
- **Полный Next.js/shadcn фронт** — сейчас прагматичный SPA (реальные данные, тёмная тема). Миграция
  на Next.js — отдельный фронт-инкремент.
- **PostgreSQL-реестр экспериментов** — сейчас файловый (DuckDB); PG-схема — когда объём вырастет.

## Запуск
```bash
ntlab up                 # поднять API + дашборд
ntlab status             # состояние + health
ntlab data-audit         # аудит озера
ntlab backtest niche     # Nautilus-бэктест по набору
ntlab gateio-ping        # проверка Gate.io public API
ntlab adaptive-test      # тест адаптивного цикла (без ключей)
```
Дашборд: `http://127.0.0.1:5020` (за Caddy+Authelia, как остальные панели сервера).

## Ключи (secrets, только через env — systemd EnvironmentFile 600)
```
GATEIO_API_KEY=...        # для live; без него — paper-only
GATEIO_API_SECRET=...
NTLAB_LLM_PROVIDER=anthropic|openai
ANTHROPIC_API_KEY=...  ИЛИ  OPENAI_API_KEY=...
```
Без ключей платформа полностью работает в backtest/paper: данные Gate.io публичные, Adaptive AI —
на детерминированном советнике.

## Структура
```
ntlab/core       конфиг, секреты
ntlab/data       аудит + загрузка озера
ntlab/strategies каталог + Nautilus-стратегии
ntlab/adapters/gateio  data (public) + execution (scaffold)
ntlab/adaptive   Adaptive AI: schema, advisor, validator, loop, память
ntlab/api        FastAPI backend
web              дашборд (SPA)
scripts          ntlab CLI, decommission
docs             ADR-001 (Docker=нет), MIGRATION-PLAN (исследование)
tests            тесты
```

## Единый код стратегии в 3 режимах (штатная модель Nautilus)
Стратегия пишется один раз (`Strategy` + `StrategyConfig`), подключается через `ImportableStrategyConfig`.
Меняется только обёртка: `BacktestNode` (backtest) / `TradingNode(environment='sandbox')` (paper,
`SandboxExecutionClient`) / `TradingNode(environment='live')` (live, наш Gate.io exec-client).
Код стратегии между режимами НЕ трогается. Детали — `docs/MIGRATION-PLAN.md`.
