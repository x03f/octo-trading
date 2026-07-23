#!/bin/bash
# Провижининг живого БУМАЖНОГО инстанса OctoBot: своя стратегия + свой портфель + свой порт.
#
# Торговля ТОЛЬКО симулятор (trader.enabled=false). API-ключи не нужны и не используются.
#
# Использование:
#   provision_instance.sh <имя> <порт> <эвалюатор> <набор_монет> [период] [spot|future] [плечо] [ТФ] [размер_ордера]
#
#   эвалюатор     SqueezeBreakoutEvaluator | DonchianBreakoutEvaluator | SmokeTestEvaluator
#   набор_монет   имя набора из portfolios.json (majors, wide, niche, niche_aggr, ...)
#   размер_ордера DSL OctoBot: "5%" = 5% баланса счёта, "a%" = от доступного. См. ниже.
#
# ─── ГРАБЛИ, ЗАШИТЫЕ В ЭТОТ СКРИПТ (не переставлять бездумно) ────────────────────
# 1. ПЛЕЧО живёт в specific_config/DailyTradingMode.json, а НЕ в корне profile.json.
#    Читается как user-input торгового режима (user_select_leverage). В корне профиля
#    его не читает никто — инстанс молча поедет на x1.
# 2. РАЗМЕР ПОЗИЦИИ на фьючерсах ограничивается ТОЛЬКО buy_order_amount/sell_order_amount.
#    Ключ max_currency_percent на фьючерсах игнорируется самим OctoBot:
#    daily_trading.py::_get_max_amount_from_max_ratio → `or self.exchange_manager.is_future`
#    (там же авторский комментарий "# TODO ratios in futures trading").
#    Без этих ключей рыночный ордер берёт ВЕСЬ плечевой запас: проверено — $10k счёта
#    открыли $1.86 млн условного объёма и счёт умер за минуту.
# 3. СТРАТЕГИЯ-РЕЛЕ обязательно RelayStrategyEvaluator, НЕ BlankStrategyEvaluator.
#    Blank публикует ноту на уровень таймфрейма, а DailyTradingMode читает уровень символа →
#    сигнал не доходит, сделок нет вообще.
# 4. Тентаклы надо УСТАНАВЛИВАТЬ в реестр каждого инстанса, файлов в tentacles/ мало.
# 5. Профиль адресуется по profile.id, профиль default удалять нельзя.
# 6. После обновления кода тентакла — перезапускать ВСЕ инстансы: Python не перечитывает модуль.
set -e

NAME=$1; PORT=$2; EVAL=$3; PF=$4; PERIOD=${5:-20}; MARKET=${6:-spot}; LEV=${7:-3}; TF=${8:-1h}; AMOUNT=${9:-}
BASE=/opt/octobot/inst-$NAME
SRC=/opt/octobot/backtest
LAB=/opt/octobot/strategy-lab

if [ -z "$NAME" ] || [ -z "$PORT" ] || [ -z "$EVAL" ] || [ -z "$PF" ]; then
  echo "нужно: <имя> <порт> <эвалюатор> <набор_монет> [период] [spot|future] [плечо] [ТФ] [размер_ордера]" >&2
  exit 2
fi

# Размер ордера по умолчанию: чем выше плечо, тем меньше доля счёта на одну позицию.
# Это ЕДИНСТВЕННАЯ работающая защита на фьючерсах (см. грабли №2).
if [ -z "$AMOUNT" ]; then
  if   [ "$MARKET" != "future" ]; then AMOUNT="15%"
  elif [ "$LEV" -ge 50 ];         then AMOUNT="0.5%"
  elif [ "$LEV" -ge 10 ];         then AMOUNT="2%"
  else                                 AMOUNT="5%"
  fi
fi

echo "=== провижининг $NAME :$PORT — $EVAL / набор $PF / $MARKET x$LEV / ТФ $TF / ордер $AMOUNT ==="
rm -rf "$BASE"; mkdir -p "$BASE"
cp -r "$SRC/user" "$BASE/user"
rm -rf "$BASE/user/data" "$BASE/user/BrowsingDataProvider_data.json"   # не наследуем чужую историю сделок
ln -sfn /opt/octobot/bot/tentacles "$BASE/tentacles"
cp -r "$SRC/user/profiles/donchian_breakout" "$BASE/user/profiles/strategy_profile"   # default НЕ трогаем
rm -rf "$BASE/logs" "$BASE/backtesting"; mkdir -p "$BASE/logs"

/opt/octobot/bot/venv/bin/python - "$BASE" "$PORT" "$EVAL" "$PF" "$PERIOD" "$MARKET" "$LEV" "$TF" "$AMOUNT" "$LAB" <<'PY'
import json, sys
base, port, ev, pf, period = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
market, lev, tf, amount, lab = sys.argv[6], int(sys.argv[7]), sys.argv[8], sys.argv[9], sys.argv[10]

# наборы монет — во внешнем файле, чтобы менять состав без правки скрипта
portfolios = json.load(open(f"{lab}/octobot/portfolios.json"))
if pf not in portfolios:
    raise SystemExit(f"набор монет '{pf}' не найден. Есть: {', '.join(portfolios)}")
pairs = [f"{c}/USDT" for c in portfolios[pf]]
if market == "future":
    pairs = [f"{s}:USDT" for s in pairs]   # у Binance-перпов формат BTC/USDT:USDT

# порт веб-интерфейса (пароль не нужен — снаружи закрыто Authelia)
cfg = f"{base}/user/config.json"; c = json.load(open(cfg))
c.setdefault("services", {}).setdefault("web", {})["port"] = port
c["profile"] = "strategy_profile"
json.dump(c, open(cfg, "w"), indent=2)

prof = f"{base}/user/profiles/strategy_profile"
p = json.load(open(f"{prof}/profile.json"))
conf = p.get("config", p)
conf["crypto-currencies"] = {"Portfolio": {"enabled": True, "pairs": pairs}}
conf["trader"] = {"enabled": False, "load-trade-history": False}            # РЕАЛЬНАЯ торговля ВЫКЛ
conf["trader-simulator"] = {"enabled": True, "fees": {"maker": 0.02, "taker": 0.046},
                            "starting-portfolio": {"USDT": 10000}}          # комиссии Gate VIP2 перп
conf["exchanges"] = {"binance": {"enabled": True, "exchange-type": market}}
conf.pop("leverage", None)          # грабли №1: здесь его читать некому, чтобы не вводило в заблуждение
p.setdefault("profile", {})["name"] = f"{ev.replace('Evaluator','')} / {pf} / {market} x{lev}"
p["profile"]["id"] = "strategy_profile"     # профиль адресуется по id, а не по имени папки
json.dump(p, open(f"{prof}/profile.json", "w"), indent=2)

# ── активация тентаклов ────────────────────────────────────────────────────────
TA_ALL = ("SqueezeBreakoutEvaluator", "DonchianBreakoutEvaluator", "SmokeTestEvaluator")
tc = f"{prof}/tentacles_config.json"; d = json.load(open(tc))
def walk(o):
    if isinstance(o, dict):
        for k in list(o):
            if k in TA_ALL:                     o[k] = (k == ev)
            if k == "RelayStrategyEvaluator":   o[k] = True     # наше реле (грабли №3)
            if k == "BlankStrategyEvaluator":   o[k] = False    # штатное с DailyTradingMode НЕ работает
            if k == "SimpleStrategyEvaluator":  o[k] = False
            walk(o[k])
    elif isinstance(o, list):
        [walk(x) for x in o]
walk(d)
# Обход выше правит только УЖЕ существующие ключи. Свежеустановленного тентакла в профиле,
# скопированном из песочницы, может не быть вовсе — тогда он молча останется выключенным.
# Поэтому выбранный эвалюатор и реле включаем явно.
act = d.setdefault("tentacle_activation", {}).setdefault("Evaluator", {})
for k in TA_ALL:
    act[k] = (k == ev)
act["RelayStrategyEvaluator"] = True
act["BlankStrategyEvaluator"] = False
json.dump(d, open(tc, "w"), indent=4)

sc = f"{prof}/specific_config"
json.dump({"required_time_frames": [tf], "required_candles_count": 300},
          open(f"{sc}/RelayStrategyEvaluator.json", "w"), indent=4)

if ev == "SqueezeBreakoutEvaluator":
    # под высокое плечо окна короче: сигнал должен успевать раньше, чем цена дойдёт до ликвидации
    sq = {"required_candles_count": 300}
    if   lev >= 50: sq.update({"vol_n": 10, "hist_n": 40, "pct": 0.30, "chan_n": 8,  "exit_n": 4})
    elif lev >= 10: sq.update({"vol_n": 14, "hist_n": 60, "pct": 0.28, "chan_n": 12, "exit_n": 6})
    json.dump(sq, open(f"{sc}/SqueezeBreakoutEvaluator.json", "w"), indent=4)
elif ev == "DonchianBreakoutEvaluator":
    json.dump({"period": period, "required_candles_count": 300},
              open(f"{sc}/DonchianBreakoutEvaluator.json", "w"), indent=4)
elif ev == "SmokeTestEvaluator":
    json.dump({"required_candles_count": 60}, open(f"{sc}/SmokeTestEvaluator.json", "w"), indent=4)

# ── торговый режим ─────────────────────────────────────────────────────────────
m = json.load(open(f"{sc}/DailyTradingMode.json"))
m.update({
    "required_strategies": ["RelayStrategyEvaluator"],
    "required_strategies_min_count": 1,
    "buy_with_maximum_size_orders": False,
    "sell_with_maximum_size_orders": False,
    "use_stop_orders": True,
    "max_currency_percent": 20,        # работает на СПОТЕ; на фьючерсах OctoBot его игнорирует
    "buy_order_amount": amount,        # грабли №2: единственный реальный лимит размера на фьючерсах
    "sell_order_amount": amount,
})
if market == "future":
    m["leverage"] = lev                # грабли №1: плечо читается ИМЕННО отсюда
json.dump(m, open(f"{sc}/DailyTradingMode.json", "w"), indent=4)
print(f"  профиль: {len(pairs)} пар, {ev}, ордер {amount}" + (f", плечо x{lev}" if market == "future" else ""))
PY

chown -R octobot:octobot "$BASE"

# регистрируем тентаклы в реестре ЭТОГО инстанса (реестр у каждого свой)
for T in squeeze_evaluator custom_breakout_evaluator smoketest_evaluator; do
  (cd "$BASE" && sudo -u octobot /opt/octobot/bot/venv/bin/OctoBot tentacles \
     -sti "$LAB/tentacle_src/$T" "Evaluator/TA" -d "$BASE" >/dev/null 2>&1) || true
done
(cd "$BASE" && sudo -u octobot /opt/octobot/bot/venv/bin/OctoBot tentacles \
   -sti "$LAB/tentacle_src/relay_strategy_evaluator" "Evaluator/Strategies" -d "$BASE" >/dev/null 2>&1) || true
chown -R octobot:octobot "$BASE"

cat > /etc/systemd/system/octobot-$NAME.service <<EOF
[Unit]
Description=OctoBot paper instance $NAME ($EVAL / $PF / $MARKET x$LEV) 127.0.0.1:$PORT
After=network.target
[Service]
Type=simple
User=octobot
WorkingDirectory=$BASE
ExecStart=/opt/octobot/bot/venv/bin/OctoBot -s
Restart=on-failure
RestartSec=15
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable octobot-$NAME >/dev/null 2>&1
# ВАЖНО именно restart, а не `enable --now`: на уже работающем сервисе `--now` ничего не делает,
# и при ПЕРЕ-провижининге процесс молча продолжает крутить старый конфиг и старый код тентакла.
systemctl restart octobot-$NAME
echo "  сервис octobot-$NAME перезапущен"
