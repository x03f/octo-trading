"""Непрерывный PAPER-сервис S11 «Новичок». ОДИН код сигнала (s11_signal) — как в backtest/live.

Что делает: следит за набором спот-пар Gate.io, тянет ЖИВЫЕ дневные свечи, гоняет онлайн-сигнал S11,
исполняет переходы позиции через PaperExecution (симуляция на живых данных, НЕ биржа). Сохраняет
состояние; после рестарта восстанавливается БЕЗ дублирующих ордеров (действие только на ИЗМЕНЕНИЕ
позиции + дедуп client_order_id). Структурные логи. Статус в файл для API/дашборда.

⚠️ Реальные ордера невозможны: исполнение — PaperExecution.SIMULATION=True. Боевой путь
(GateioExecution) активируется только явным LIVE-переключателем и ключами — здесь не используется.

Режимы:
  live   — тянет свечи с Gate.io, тикает по расписанию (S11 — дневная, тик раз в час достаточно).
  replay — прогон по историческому окну листинга из озера (для доказательной paper-сделки и soak).
"""
import json, time, logging
from pathlib import Path
import numpy as np

from ..adapters.gateio.data import GateioData
from ..adapters.gateio.paper import PaperExecution
from ..adapters.gateio.signing import client_order_id
from ..strategies.s11_signal import s11_run, S11Params

STATE = Path("/opt/octobot/nautilus-lab/var/paper_s11_state.json")
STATUS = Path("/opt/octobot/nautilus-lab/web/data/paper_s11_status.json")
LOG = Path("/opt/octobot/nautilus-lab/var/paper_s11.log")

log = logging.getLogger("paper.s11")


def _setup_logging():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(LOG)
    h.setFormatter(logging.Formatter('{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":%(message)s}'))
    log.addHandler(h); log.setLevel(logging.INFO)


class S11PaperService:
    def __init__(self, watchlist=None, start_balance=10000.0, risk_usdt_per_pos=200.0, data=None):
        self.watch = watchlist or []
        self.risk = risk_usdt_per_pos
        self.data = data or GateioData()
        self.exec = PaperExecution(starting_balances={"USDT": start_balance}, data=self.data)
        self.params = S11Params()
        self.state = {"positions": {}, "qty": {}, "submitted": [], "equity_history": [],
                      "start_balance": start_balance, "ticks": 0, "started": None}
        self._load()

    # ---- состояние: восстановление без дублей ----
    def _load(self):
        if STATE.exists():
            try:
                self.state = json.load(open(STATE))
                # восстановить виртуальные балансы/позиции симулятора из состояния
                self.exec.balances = self.state.get("balances", self.exec.balances)
                log.info(json.dumps(f"восстановлено состояние: {len(self.state['positions'])} позиций, "
                                    f"{self.state['ticks']} тиков", ensure_ascii=False))
            except Exception as e:
                log.info(json.dumps(f"состояние не прочитано: {e}", ensure_ascii=False))

    def _save(self):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        self.state["balances"] = dict(self.exec.balances)
        json.dump(self.state, open(STATE, "w"), ensure_ascii=False)

    def _daily(self, pair, days_back=400):
        """Живые дневные свечи Gate.io. Возвращает (highs, lows, closes, listing_age_days) или None.
        listing_age_days — сколько дней монета торгуется (по самой ранней свече)."""
        frm = int(time.time()) - days_back * 86400
        c = self.data.candles(pair, "1d", frm=frm)
        if len(c) < 5:
            return None
        age_days = (time.time() * 1000 - c[0]["ts"]) / 86_400_000
        return (np.array([x["high"] for x in c]), np.array([x["low"] for x in c]),
                np.array([x["close"] for x in c]), age_days)

    def is_fresh_listing(self, pair):
        """Genuine ли новый листинг: монета торгуется не дольше окна входа S11 + буфер."""
        d = self._daily(pair)
        if d is None:
            return False, None
        age = d[3]
        return (age <= self.params.end_day + 10), age

    def tick(self, ts=None):
        """Одна итерация: пересчёт S11 по каждой паре, исполнение ИЗМЕНЕНИЙ позиции."""
        ts = ts or int(time.time() * 1000)
        acted = []
        for pair in self.watch:
            try:
                d = self._daily(pair)
                if d is None:
                    continue
                H, L, C, age = d
                # S11 действует ТОЛЬКО на свежих листингах; устоявшиеся монеты пропускаем
                cur = self.state["positions"].get(pair, 0.0)
                if age > self.params.end_day + 30 and cur == 0.0:
                    continue
                target, info, _ = s11_run(H, L, C, first_idx=0, shortable_from_idx=0, params=self.params)
                if target != cur:
                    acted.append(self._transition(pair, cur, target, C[-1], ts))
            except Exception as e:
                log.info(json.dumps(f"{pair} ошибка тика: {str(e)[:80]}", ensure_ascii=False))
        self.state["ticks"] += 1
        eq = self.exec.equity_usdt()
        self.state["equity_history"].append({"ts": ts, "equity": round(eq, 2)})
        self.state["equity_history"] = self.state["equity_history"][-500:]
        self._save(); self._status()
        return {"acted": [a for a in acted if a], "equity": round(eq, 2), "tick": self.state["ticks"]}

    def _transition(self, pair, cur, target, price, ts):
        """Исполнить смену позиции. Дедуп: не повторять уже отправленный переход в этот день."""
        day = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
        cid = client_order_id(f"s11-{pair}-{day}")
        dedup_key = f"{pair}:{cur}->{target}:{day}"
        if dedup_key in self.state["submitted"]:
            return None                              # уже отправляли этот переход сегодня — идемпотентно
        # S11 — шорт-онли: target -1 = открыть шорт (sell), target 0 = закрыть (buy back ТОТ ЖЕ объём)
        if target < cur:                                  # открытие шорта
            amount = round(self.risk / price, 6)
            self.state.setdefault("qty", {})[pair] = amount
            side = "sell"
        else:                                             # закрытие: откупаем ровно открытый объём
            amount = self.state.get("qty", {}).get(pair, round(self.risk / price, 6))
            self.state.setdefault("qty", {})[pair] = 0.0
            side = "buy"
        r = self.exec.submit_market(pair, side, amount, client_id=cid, ts=ts)
        self.state["positions"][pair] = target
        self.state["submitted"].append(dedup_key)
        self.state["submitted"] = self.state["submitted"][-2000:]
        log.info(json.dumps({"event": "transition", "pair": pair, "from": cur, "to": target,
                             "side": side, "status": r["status"], "filled": r.get("filled"),
                             "cid": cid}, ensure_ascii=False))
        return {"pair": pair, "from": cur, "to": target, "side": side, "status": r["status"]}

    def _status(self):
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        eqh = self.state["equity_history"]
        eq = eqh[-1]["equity"] if eqh else self.state["start_balance"]
        peak = max((e["equity"] for e in eqh), default=eq)
        dd = (eq / peak - 1) if peak else 0
        json.dump({
            "simulation": True, "strategy": "S11", "engine": "nautilus-lab paper",
            "watchlist": len(self.watch), "ticks": self.state["ticks"],
            "open_positions": {k: v for k, v in self.state["positions"].items() if v != 0},
            "equity": eq, "start_balance": self.state["start_balance"],
            "pnl_pct": round((eq / self.state["start_balance"] - 1) * 100, 2),
            "max_drawdown_pct": round(dd * 100, 2),
            "fills": len(self.exec.fills), "orders": len(self.exec.orders),
            "started": self.state.get("started"), "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, open(STATUS, "w"), ensure_ascii=False, indent=1)

    def replay_coin(self, highs, lows, closes, pair="REPLAY_USDT", first_idx=0):
        """REPLAY окна листинга из озера через тот же paper-путь → доказательная paper-сделка.
        Прогоняет S11 по историческим барам, исполняя каждый переход позиции. Явно помечено replay."""
        _setup_logging()
        p = self.params
        _, _, positions = s11_run(highs, lows, closes, first_idx=first_idx, shortable_from_idx=0, params=p)
        prev = 0.0
        held = 0.0
        trades = []
        for t in range(len(positions)):
            tgt = positions[t]
            if tgt != prev:
                price = float(closes[t])
                if tgt < prev:                            # открытие шорта
                    amount = round(self.risk / price, 6); held = amount; side = "sell"
                else:                                     # закрытие: откупаем открытый объём
                    amount = held or round(self.risk / price, 6); held = 0.0; side = "buy"
                # для replay стакан живой недоступен по историческому инструменту → фикс-заполнение по close
                fee = amount * price * self.exec.taker_fee
                self.exec.fills.append(type("F", (), {"as_dict": lambda s: {
                    "order_id": f"replay-{t}", "symbol": pair, "side": side, "price": price,
                    "amount": amount, "fee": fee, "role": "taker", "ts": t, "partial": False}})())
                trades.append({"bar": t, "side": side, "price": price, "amount": amount, "fee": round(fee, 4),
                               "from": prev, "to": tgt})
                prev = tgt
        log.info(json.dumps({"event": "replay", "pair": pair, "trades": len(trades)}, ensure_ascii=False))
        return trades

    def run(self, interval_s=3600):
        """Непрерывный цикл (для systemd). S11 — дневная, тик раз в час."""
        _setup_logging()
        if not self.state.get("started"):
            self.state["started"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        log.info(json.dumps(f"S11 paper-сервис запущен, watchlist={len(self.watch)}", ensure_ascii=False))
        while True:
            try:
                r = self.tick()
                log.info(json.dumps({"event": "tick", "n": r["tick"], "equity": r["equity"],
                                     "acted": len(r["acted"])}, ensure_ascii=False))
            except Exception as e:
                log.info(json.dumps(f"тик упал: {str(e)[:120]}", ensure_ascii=False))
            time.sleep(interval_s)
