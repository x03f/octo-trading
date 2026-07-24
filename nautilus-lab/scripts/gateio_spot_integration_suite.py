#!/usr/bin/env python3
"""P2: приватный интеграционный сьют Gate.io SPOT. АВТОЗАПУСК после появления ключей.

Без ключей (settings.gateio_ready=False) — все приватные шаги SKIPPED (документируют, что выполнится).
С ключами — безопасный полный поток: sync_time → balances → instrument(precision/min) → валидация
ордера → разместить МИКРО-лимит далеко от рынка → найти по client_id (идемпотентность) → отменить →
my_trades → reconcile → emergency_stop. Реальные средства не расходуются (ордер не исполняется и
сразу отменяется), но требует ЯВНОГО live_enabled + подтверждения (иначе mutating-шаги SKIPPED).
"""
import sys, json, time
sys.path.insert(0, "/opt/octobot/strategy-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.core.config import settings

RESULTS = "/opt/octobot/nautilus-lab/web/data/gateio_spot_suite.json"
PAIR = "BTC_USDT"


def main():
    res = []
    def add(name, status, detail=""):
        res.append({"name": name, "status": status, "detail": detail})

    keys = settings.gateio_ready
    live = getattr(settings, "gateio_live_enabled", False)

    # публичные шаги (без ключей) — выполняются всегда
    try:
        from ntlab.adapters.gateio.data import GateioData
        g = GateioData(); ping = g.ping(); g.close()
        add("public_ping", "PASS" if ping.get("ok") else "FAIL", str(ping)[:80])
    except Exception as e:
        add("public_ping", "FAIL", str(e)[:80])

    if not keys:
        for step in ["sync_time", "balances", "instrument_spec", "validate_order",
                     "place_micro_limit", "idempotency_check", "cancel_order", "my_trades",
                     "reconcile", "emergency_stop"]:
            add(step, "SKIPPED", "нет ключей Gate.io — приватный шаг отложен до ввода")
        _write(res, keys, live); return summary(res)

    # приватные шаги (есть ключи)
    from ntlab.adapters.gateio.execution import GateioExecution, OrderValidationError
    from ntlab.adapters.gateio.reconcile import reconcile
    ex = GateioExecution(settings.GATEIO_API_KEY, settings.GATEIO_API_SECRET, live_enabled=live)
    try:
        ex.sync_time(); add("sync_time", "PASS", f"offset {ex._time_offset_ms}ms")
        bal = ex.balances(); add("balances", "PASS", f"{len(bal)} валют")
        spec = ex.instrument(PAIR)
        add("instrument_spec", "PASS", f"min_amt={spec['min_base_amount']} min_notional={spec['min_quote_amount']} prec={spec['amount_precision']}")
        # валидация: заведомо маленький ордер должен отклониться
        try:
            ex.validate_order(spec, "buy", 1e-9, 1.0); add("validate_order", "FAIL", "не отклонил слишком малый ордер")
        except OrderValidationError:
            add("validate_order", "PASS", "слишком малый ордер корректно отклонён")
        if not live:
            for step in ["place_micro_limit", "idempotency_check", "cancel_order", "emergency_stop"]:
                add(step, "SKIPPED", "live_enabled=False — мутирующие шаги отложены")
        else:
            # микро-лимит далеко от рынка (не исполнится), сразу отменяем
            cid = f"t-suite-{int(time.time())}"
            o = ex.place_order_safe(PAIR, "buy", spec["min_base_amount"], price=1000.0, text=cid, spec=spec)
            add("place_micro_limit", "PASS", f"id={o.get('id')}")
            o2 = ex.place_order_safe(PAIR, "buy", spec["min_base_amount"], price=1000.0, text=cid, spec=spec)
            add("idempotency_check", "PASS" if o2.get("idempotent") else "FAIL", "повтор с тем же client_id не создал дубль")
            ex.cancel_order(o["id"], PAIR); add("cancel_order", "PASS", "ордер отменён")
            es = ex.emergency_stop(PAIR); add("emergency_stop", "PASS", f"отменено {len(es['cancelled'])}, live выключен")
        my = ex.my_trades(PAIR, limit=5); add("my_trades", "PASS", f"{len(my)} исполнений")
        rep = reconcile(ex, {"positions": {}, "known_order_ids": []}, [PAIR])
        add("reconcile", "PASS" if rep.get("exchange_reachable") else "FAIL", f"in_sync={rep.get('in_sync')}")
    finally:
        ex.close()
    _write(res, keys, live); return summary(res)


def summary(res):
    c = {"passed": sum(r["status"] == "PASS" for r in res),
         "failed": sum(r["status"] == "FAIL" for r in res),
         "skipped": sum(r["status"] == "SKIPPED" for r in res)}
    print(f"GATE.IO SPOT SUITE: {c['passed']} PASS / {c['failed']} FAIL / {c['skipped']} SKIPPED")
    for r in res:
        print(f"  [{r['status']:>7}] {r['name']:<20} {r['detail'][:70]}")
    return 0 if c["failed"] == 0 else 2


def _write(res, keys, live):
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "keys_present": keys, "live_enabled": live, "pair": PAIR,
               "summary": {"passed": sum(r["status"] == "PASS" for r in res),
                           "failed": sum(r["status"] == "FAIL" for r in res),
                           "skipped": sum(r["status"] == "SKIPPED" for r in res)},
               "results": res}, open(RESULTS, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
