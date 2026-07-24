# CLAUDE.md — Nautilus Trading Lab

## Цель проекта (актуальная)
**Законченная торговая платформа на NautilusTrader.** Не набор инкрементов — цельный продукт:
research-лаба, озеро данных, backtest, paper на живых данных Gate.io, live-preset, Adaptive AI,
дашборд, наблюдаемость. OctoBot — **временный** legacy-контур, подлежащий удалению после переноса
полезного и regression-подтверждения (НЕ бессрочный контроль).

## Рабочие правила (для этой задачи)
- Работать до завершения ВСЕЙ спецификации, не останавливаться после отдельного инкремента/отчёта.
- Отсутствие ключей блокирует ТОЛЬКО фактические private/live-тесты. Всё остальное (архитектура,
  адаптеры, лаба, стратегии, дашборд, тесты, доки) — реализовывать через mock/replay/sandbox/paper.
- Промежуточные коммиты — да; после коммита продолжать следующую часть.
- Не выдавать удачный одиночный backtest за экономическую эффективность. Для каждого результата —
  капитал, размеры позиций, комиссии, slippage, число сделок, drawdown, benchmark, OOS.
- Честность превыше галочек: явно отделять доказанное от подготовленного.

## Развёртывание (ADR-001): НАТИВНО, без Docker
Docker не используется (на сервере нет, весь сервер нативный). systemd + venv + нативный PostgreSQL 17.
Единый CLI `ntlab`. venv: `/opt/octobot/nautilus-venv`. Продукт: `/opt/octobot/nautilus-lab`
(симлинк → `strategy-lab/nautilus-lab`, git-репо octo-trading).

## Границы (строго)
- Трогать ТОЛЬКО `octobot-*`/`ntlab-*`/`/opt/octobot`. Чужие проекты (folio, nmh, shnalytics,
  shnurok-*, graphify) — не задевать.
- Реальные ордера/ключи — не заводить. Live заблокирован многофакторно (safety.py).
- OctoBot не сносить, пока новая система не подтверждена regression-тестами (есть архив+git-тег).

## Ключевые команды
`ntlab up|down|status|test|data-audit|backtest|nautilus-status|lifecycle-proof|contours|futures-testnet-suite`
Дашборд: http://127.0.0.1:5020 (за Authelia). Сервисы: ntlab-api ntlab-paper ntlab-nautilus.

## Что доказано / не доказано — источник правды
`ntlab/core/status.py` + `/api/contours`. S11: runtime operational, execution validated, forward pending.
Экономический край НЕ доказан ни у одной стратегии (честный трёхчастный тест).
