# Эксплуатация Nautilus Trading Lab — единые команды

**Решение по развёртыванию (P1): полностью НАТИВНО (systemd + venv), без Docker.**
См. `ADR-001-deployment.md`. На сервере Docker отсутствует; альтернативной инфраструктуры
(контейнеры/compose/Redis) нет — удалять нечего. Единый способ управления — CLI `ntlab`.

## Почему нативно (сравнение под этот сервер)
| Критерий | Docker | Гибрид | **Нативно (выбрано)** |
|---|---|---|---|
| Есть на сервере | нет | — | да (systemd, PostgreSQL 17, venv) |
| Live trading (латентность) | оверхед сети/NAT | смешанный | прямой сокет, минимум прослоек |
| Research (CPU/полномочия) | лимиты cgroup | — | полный доступ к CPU/диску |
| PostgreSQL | отдельный контейнер | внешний | нативный `postgresql@17-main` |
| Redis | нужен контейнер | — | **не требуется** (msgbus в процессе Nautilus) |
| Frontend | отдельный образ | — | self-contained (FastAPI + inline SVG) |
| Data lake | volume-mount | — | прямой путь `/opt/octobot/strategy-lab/data` |
| Recovery | orchestrator | сложно | `systemctl restart` + `ntlab recover` |

## Единые команды (CLI `ntlab`)
| Действие | Команда |
|---|---|
| **Установка** (enable+start всех сервисов) | `ntlab install` |
| **Запуск** | `ntlab up` (API) · `ntlab paper-up` · `ntlab nautilus-restart` |
| **Обновление** (git pull + deps + restart + tests) | `ntlab update` |
| **Остановка** | `ntlab down` · `ntlab stop-all` |
| **Диагностика** (сервисы/health/эндпойнты/регрессия/диск) | `ntlab diagnose` |
| **Восстановление** после сбоя | `ntlab recover` |
| Тесты (все / по категориям) | `ntlab test` · `ntlab test-categories` |
| Аудит озера | `ntlab data-audit` |
| Эксперимент / leaderboard | `ntlab experiment S8` · `ntlab leaderboard` |
| Приватный сьют Gate.io (после ключей) | `ntlab gateio-spot-suite` |
| Вывод OctoBot (после regression GO) | `ntlab decommission-octobot --i-understand` |

## Сервисы (systemd)
- `ntlab-api` — FastAPI + дашборд (:5020, за Caddy+Authelia).
- `ntlab-nautilus` — Nautilus TradingNode (SANDBOX), S11.
- `ntlab-paper` — custom paper harness (независимый oracle).
- `ntlab-forward.timer` — Nautilus-native форвард-снимок каждые 5 мин.

## Восстановление после сбоя (disaster recovery)
1. `ntlab recover` — перечитывает units, рестартит сервисы, обновляет форвард-снимок, диагностирует.
2. Состояние переживает рестарт: реестр экспериментов (DuckDB), портфели (JSON), champion/challenger
   (JSONL), память консультаций (JSONL), форвард-история (JSONL). Покрыто тестами `restart-recovery`.
3. Откат OctoBot-решения: архив `/opt/octobot/octobot-archive-YYYYMMDD.tar.gz` + git-тег
   `octobot-last-working`.

## Данные и ключи
- Секреты — только через env/secrets, в git не коммитятся (`.gitignore`, scrub-before-push).
- Live-ордера заблокированы многофакторно (`ntlab/nautilus/safety.py`): runtime=live +
  `NTLAB_LIVE_ENABLED=true` + файл-подтверждение. Emergency stop — сброс любого фактора.
