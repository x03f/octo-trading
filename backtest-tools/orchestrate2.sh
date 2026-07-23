#!/bin/bash
# ЧИСТЫЙ прогон всех стратегий починенным драйвером (ждёт finished). Последовательно.
DF=$(cat /tmp/octobot_datafile)
SCR=/tmp/claude-0/-root/c9f9131d-947c-4a05-9c52-4d9271c36225/scratchpad
OUT=$SCR/results_clean.jsonl
: > "$OUT"
CFG=/opt/octobot/backtest/user/config.json
PROFILES="simple_dca smart_dca grid_trading trailing_grid_trading staggered_orders_trading daily_trading dip_analyser index_trading donchian_breakout"

for prof in $PROFILES; do
  echo ">>> $prof : профиль + рестарт ($(date +%H:%M))"
  sudo -u octobot /opt/octobot/bot/venv/bin/python -c "import json;d=json.load(open('$CFG'));d['profile']='$prof';json.dump(d,open('$CFG','w'),indent=2)"
  systemctl restart octobot-backtest
  ready=0
  for i in $(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:5002/backtesting && { ready=1; break; }; sleep 3; done
  if [ "$ready" != 1 ]; then echo "{\"profile\":\"$prof\",\"result\":{\"error\":\"not ready\"}}" >> "$OUT"; continue; fi
  sleep 4
  res=$(cd "$SCR" && timeout 1500 node bt_run2.mjs "$DF" "clean_$prof" 2>/dev/null | tail -1)
  [ -z "$res" ] && res='{"error":"no output"}'
  echo "{\"profile\":\"$prof\",\"result\":$res}" >> "$OUT"
  echo "    $prof -> $res"
done
echo "=== ГОТОВО $(date +%H:%M) ==="
cat "$OUT"
