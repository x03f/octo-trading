# strategy-lab бэктест-движок (pure numpy)

Собственный честный бэктестер. Почему свой, а не OctoBot: для market-neutral и портфельных нот нужен
контроль над отсутствием look-ahead, костами и атрибуцией — капризный OctoBot-харнесс это не даёт
(см. BACKTEST-METHODOLOGY). Зависимости: только `numpy` + `pyarrow` (никакого pandas/scipy — не трогаем
runtime-venv OctoBot). Всё, что нужно (ADF, метрики, индикаторы), реализовано вручную.

## Гарантия честности (главное)
- **Без look-ahead:** вес `weights[t,i]` формируется на ЗАКРЫТИИ бара t из данных ≤ t и держится (t, t+1).
  Каналы Donchian сдвинуты на 1 бар; β/коинтеграция пар — на трейлинг-окне до t; аллокация ансамбля — из
  доходностей ног строго до t.
- **Косты всегда включены** (Gate taker 6bps + slip 5bps), берутся с оборота относительно дрейфа весов.
- **Независимые бенчмарки** (BTC buy-hold, EW-корзина) считаются своим движком, не чужой метрикой.

## Файлы
| Файл | Роль |
|---|---|
| `data.py` | загрузка parquet-озера → `Panel` (выровненные [T×N], NaN=не листился); `PPY` баров/год |
| `metrics.py` | CAGR/vol/Sharpe/Sortino/maxDD/Calmar из кривой эквити; `fmt()` |
| `costs.py` | `CostModel(fee_bps, slip_bps)`; пресеты GATE_TAKER/MAKER/ZERO |
| `backtester.py` | `run_portfolio(panel, weights, cost, funding, ppy)` — ядро без look-ahead |
| `benchmark.py` | `buy_hold_single`, `buy_hold_equal_weight` |
| `strategy.py` | базовый `Strategy` + индикаторы (rolling_*, ema, atr, adx, rsi, true_range, shift) |
| `strategies/turtle.py` | **S4 «Черепаха»** — Donchian/Turtle time-series breakout |
| `strategies/gridmr.py` | **S5 «Маятник»** — regime-gated mean-reversion (флаг use_gate для A/B) |
| `strategies/pairs.py` | **S3 «Спред»** — stat-arb пары (OLS β + hand-rolled ADF, walk-forward) |
| `strategies/fluger.py` | **S1 «Флюгер»** — режим-адаптив тренд↔MR + BTC-risk-scalar (funding=стаб) |
| `strategies/carry.py` | **S2 «Базис»** — delta-neutral funding carry (ждёт funding; есть synthetic_funding) |
| `strategies/ensemble.py` | **S6 «Оркестр»** — risk-parity + kill-switch ансамбль нот |

## Запуск
```bash
cd /opt/octobot/strategy-lab
sudo -u octobot /opt/octobot/bot/venv/bin/python run.py <name> [tf]   # одна нота: turtle|S5|pairs|fluger…
sudo -u octobot /opt/octobot/bot/venv/bin/python run_all.py [tf]      # весь портфель + бенчмарки + ансамбль
sudo -u octobot /opt/octobot/bot/venv/bin/python selftest.py          # smoke-тест движка
```
Результаты → `results/<name>_<tf>.json` + `.equity.npy`. Итоги первого прогона → `../RESULTS-SUITE.md`.

## Ещё НЕ сделано (следующие инженерные шаги)
- **walk-forward / OOS обёртка** (train/test split) — без неё числам верить нельзя.
- Прогон на 4h/1h (данные в озере) + на полном озере (топ-100+).
- Сенситивность параметров (плато, не пик).
- S2/S1: реальная funding-нога после сбора перп+funding (задача #9).
- Атрибуция P&L по нотам/активам; половина спреда S3 — переосмыслить (интрадей или отказ).
