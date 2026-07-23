#!/bin/bash
# Провижининг живого бумажного инстанса OctoBot: своя стратегия + свой портфель + свой порт.
# Использование: provision_instance.sh <имя> <порт> <SqueezeBreakoutEvaluator|DonchianBreakoutEvaluator> <majors|wide> [период]
# Торговля ТОЛЬКО симулятор (trader.enabled=false) — API-ключи не нужны и не используются.
set -e
NAME=$1; PORT=$2; EVAL=$3; PF=$4; PERIOD=${5:-20}; MARKET=${6:-spot}; LEV=${7:-3}; TF=${8:-1h}; PCTCOIN=${9:-20}
BASE=/opt/octobot/inst-$NAME
SRC=/opt/octobot/backtest

echo "=== провижининг $NAME на порту $PORT: $EVAL / портфель $PF ==="
rm -rf "$BASE"; mkdir -p "$BASE"
cp -r "$SRC/user" "$BASE/user"
rm -rf "$BASE/user/data" "$BASE/user/BrowsingDataProvider_data.json"   # не наследуем чужую историю сделок
ln -sfn /opt/octobot/bot/tentacles "$BASE/tentacles"
cp -r "$SRC/user/profiles/donchian_breakout" "$BASE/user/profiles/strategy_profile"   # профиль default НЕ трогаем — OctoBot его требует
rm -rf "$BASE/logs" "$BASE/backtesting"; mkdir -p "$BASE/logs"

/opt/octobot/bot/venv/bin/python - "$BASE" "$PORT" "$EVAL" "$PF" "$PERIOD" "$MARKET" "$LEV" "$TF" "$PCTCOIN" <<'PY'
import json, sys
base, port, ev, pf, period = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
market, lev = sys.argv[6], int(sys.argv[7])
tf, pctcoin = sys.argv[8], int(sys.argv[9])
MAJORS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT",
          "DOGE/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT"]
WIDE   = MAJORS + ["TRX/USDT","LTC/USDT","BCH/USDT","XLM/USDT","HBAR/USDT",
                   "SUI/USDT","NEAR/USDT","UNI/USDT","APT/USDT","ATOM/USDT"]
pairs = MAJORS if pf == "majors" else WIDE
if market == "future":
    pairs = [f"{s}:USDT" for s in pairs]   # у Binance-перпов формат BTC/USDT:USDT

# порт веб-интерфейса + без пароля (за Authelia/локально)
cfg = f"{base}/user/config.json"; c = json.load(open(cfg))
c.setdefault("services", {}).setdefault("web", {})
c["services"]["web"]["port"] = port
c["profile"] = "strategy_profile"
json.dump(c, open(cfg, "w"), indent=2)

prof = f"{base}/user/profiles/strategy_profile"
p = json.load(open(f"{prof}/profile.json"))
conf = p.get("config", p)
conf["crypto-currencies"] = {"Portfolio": {"enabled": True, "pairs": pairs}}
conf["trader"] = {"enabled": False, "load-trade-history": False}          # РЕАЛЬНАЯ торговля ВЫКЛ
conf["trader-simulator"] = {"enabled": True, "fees": {"maker": 0.02, "taker": 0.046},
                            "starting-portfolio": {"USDT": 10000}}        # комиссии Gate VIP2 перп
# спот или фьючерсы. Плечо: потолок биржи х10, но РАБОЧЕЕ значение по RISK-FRAMEWORK ≤3x —
# на х10 ликвидация приходит на обычном движении, это осознанное инженерное ограничение.
conf["exchanges"] = {"binance": {"enabled": True, "exchange-type": market}}
if market == "future":
    conf["leverage"] = lev
p.setdefault("profile", {})["name"] = f"{ev.replace('Evaluator','')} / {pf} / {market}"
p["profile"]["id"] = "strategy_profile"   # ВАЖНО: профиль адресуется по id, а не по имени папки
json.dump(p, open(f"{prof}/profile.json", "w"), indent=2)

# активация: нужный TA-эвалюатор + passthrough-стратегия + DailyTradingMode
tc = f"{prof}/tentacles_config.json"; d = json.load(open(tc))
def walk(o):
    if isinstance(o, dict):
        for k in list(o):
            if k in ("SqueezeBreakoutEvaluator", "DonchianBreakoutEvaluator"):
                o[k] = (k == ev)
            if k == "BlankStrategyEvaluator": o[k] = True
            if k == "SimpleStrategyEvaluator": o[k] = False
            walk(o[k])
    elif isinstance(o, list):
        [walk(x) for x in o]
walk(d); json.dump(d, open(tc, "w"), indent=4)

json.dump({"required_time_frames": [tf], "required_candles_count": 300},
          open(f"{prof}/specific_config/BlankStrategyEvaluator.json", "w"), indent=4)
if ev == "SqueezeBreakoutEvaluator":
    # под высокое плечо — короче окна: сигнал должен приходить быстрее, чем цена дойдёт до ликвидации
    sq = {"required_candles_count": 300}
    if lev >= 50:   sq.update({"vol_n": 10, "hist_n": 40, "pct": 0.30, "chan_n": 8,  "exit_n": 4})
    elif lev >= 10: sq.update({"vol_n": 14, "hist_n": 60, "pct": 0.28, "chan_n": 12, "exit_n": 6})
    json.dump(sq, open(f"{prof}/specific_config/SqueezeBreakoutEvaluator.json", "w"), indent=4)
if ev == "DonchianBreakoutEvaluator":
    json.dump({"period": period}, open(f"{prof}/specific_config/DonchianBreakoutEvaluator.json", "w"), indent=4)
m = json.load(open(f"{prof}/specific_config/DailyTradingMode.json"))
m.update({"required_strategies": ["BlankStrategyEvaluator"], "required_strategies_min_count": 1,
          "buy_with_maximum_size_orders": False, "sell_with_maximum_size_orders": False,
          "use_stop_orders": True, "max_currency_percent": pctcoin})   # доля капитала на монету
json.dump(m, open(f"{prof}/specific_config/DailyTradingMode.json", "w"), indent=4)
print(f"  профиль: {len(pairs)} пар, эвалюатор {ev}, порт {port}")
PY

chown -R octobot:octobot "$BASE"
# регистрируем тентаклы в реестре этого инстанса
for T in squeeze_evaluator custom_breakout_evaluator; do
  (cd "$BASE" && sudo -u octobot /opt/octobot/bot/venv/bin/OctoBot tentacles \
     -sti /opt/octobot/strategy-lab/tentacle_src/$T "Evaluator/TA" -d "$BASE" >/dev/null 2>&1) || true
done

cat > /etc/systemd/system/octobot-$NAME.service <<EOF
[Unit]
Description=OctoBot paper instance $NAME ($EVAL / $PF) 127.0.0.1:$PORT
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
systemctl enable --now octobot-$NAME >/dev/null 2>&1
echo "  сервис octobot-$NAME запущен"
