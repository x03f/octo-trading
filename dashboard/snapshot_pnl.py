"""Автоснимок P&L форвард-контура: раз в час дёргает дашборд-API и дописывает строку в CSV.

Зачем: форвард-тест — единственный незагрязнённый отбором источник. Чтобы из него можно было
что-то заключить, нужна ВРЕМЕННА́Я история стоимости каждого инстанса, а не только «сейчас».
Снимок append-only, растёт сам, никакого внимания не требует.

Запуск разово: python snapshot_pnl.py    (обычно из systemd-таймера octobot-pnl-snapshot)
"""
import csv, json, os, time, urllib.request

API = "http://127.0.0.1:5010/api/data"
OUT = "/opt/octobot/strategy-lab/dashboard/pnl_history.csv"


def main():
    try:
        with urllib.request.urlopen(API, timeout=15) as r:
            d = json.load(r)
    except Exception as e:
        print(f"[snapshot] дашборд недоступен: {type(e).__name__}: {e}", flush=True)
        return
    ts = int(time.time())
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    rows = []
    for inst in d.get("instances", []):
        rows.append({
            "ts": ts, "iso": iso, "instance": inst["key"],
            "value": inst.get("value"), "trades": inst.get("trades"),
            "alive": inst.get("alive"),
        })
    new_file = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "iso", "instance", "value", "trades", "alive"])
        if new_file:
            w.writeheader()
        w.writerows(rows)
    tot = d.get("totals", {})
    print(f"[snapshot] {iso}: {len(rows)} инстансов, суммарно ${tot.get('value', 0):,.2f}, "
          f"сделок {tot.get('trades', 0)} → {OUT}", flush=True)


if __name__ == "__main__":
    main()
