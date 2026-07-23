"""Reconciliation: сверка внутреннего состояния с биржей после рестарта.

Для БОЕВОГО пути (GateioExecution): после рестарта тянем с биржи балансы, открытые ордера и
последние исполнения, сравниваем с локальным состоянием, находим расхождения (ордера, о которых
платформа не знает; позиции, разошедшиеся с биржей) и формируем список действий на выравнивание.
Никаких мутирующих действий сам не делает — только диагностирует (безопасно).

Тестируется на mock-execution без сети/ключей.
"""


def reconcile(execution, local_state, pairs):
    """execution — объект с методами balances()/open_orders()/my_trades(pair).
    local_state — {"positions": {...}, "known_order_ids": [...]}.
    Возвращает отчёт о расхождениях + рекомендованные действия (без исполнения)."""
    report = {"exchange_reachable": True, "discrepancies": [], "actions": [],
              "exchange_balances": {}, "local_positions": dict(local_state.get("positions", {}))}
    try:
        report["exchange_balances"] = execution.balances()
    except Exception as e:
        report["exchange_reachable"] = False
        report["discrepancies"].append(f"биржа недоступна: {str(e)[:80]}")
        return report

    known = set(local_state.get("known_order_ids", []))
    for pair in pairs:
        try:
            open_orders = execution.open_orders(pair)
        except Exception as e:
            report["discrepancies"].append(f"{pair}: не удалось получить ордера: {str(e)[:60]}")
            continue
        for o in open_orders:
            if o["id"] not in known:
                # ордер есть на бирже, платформа о нём не знает → потенциальная рассинхронизация
                report["discrepancies"].append(f"{pair}: неизвестный открытый ордер {o['id']} ({o['side']} {o['left']})")
                report["actions"].append({"type": "adopt_or_cancel", "pair": pair, "order_id": o["id"],
                                          "reason": "ордер на бирже вне локального состояния"})
        # проверка позиции против исполнений (для спота позиция = баланс базовой валюты)
        base = pair.split("_")[0]
        exch_base = report["exchange_balances"].get(base, {}).get("available", 0) + \
                    report["exchange_balances"].get(base, {}).get("locked", 0)
        local_pos = local_state.get("positions", {}).get(pair, 0)
        # спот: шорт невозможен на балансе; для paper позиция виртуальна. Тут — только флаг несоответствия.
        if local_pos != 0 and abs(exch_base) < 1e-9 and local_pos > 0:
            report["discrepancies"].append(f"{pair}: локально позиция {local_pos}, на бирже базового актива нет")
            report["actions"].append({"type": "resync_position", "pair": pair,
                                      "local": local_pos, "exchange_base": exch_base})

    report["in_sync"] = len(report["discrepancies"]) == 0
    return report
