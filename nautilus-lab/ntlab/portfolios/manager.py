"""Мульти-портфели paper на живых данных Gate.io. Несколько портфелей, реальные комиссии, slippage.

Каждый портфель: id, стартовый баланс, стратегия, инструменты, состояние, восстановление после
рестарта. Перевод research->paper. Исполнение — PaperExecution (симуляция на живом стакане Gate.io).
Реальные ордера невозможны без ключей и явного live-preset.
"""
import json, time
from pathlib import Path
from ..adapters.gateio.paper import PaperExecution

STORE = Path("/opt/octobot/nautilus-lab/var/portfolios")
STATUS = Path("/opt/octobot/nautilus-lab/web/data/portfolios.json")
STORE.mkdir(parents=True, exist_ok=True)


class Portfolio:
    def __init__(self, pid, name, start_balance, strategy, instruments, mode="paper"):
        self.pid = pid; self.name = name; self.start_balance = start_balance
        self.strategy = strategy; self.instruments = instruments; self.mode = mode
        self.created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.exec = PaperExecution(starting_balances={"USDT": start_balance})
        self.orders = []
        self.state = {"positions": {}, "realized_pnl": 0.0}

    def path(self):
        return STORE / f"{self.pid}.json"

    def save(self):
        json.dump({"pid": self.pid, "name": self.name, "start_balance": self.start_balance,
                   "strategy": self.strategy, "instruments": self.instruments, "mode": self.mode,
                   "created": self.created, "balances": self.exec.balances,
                   "state": self.state, "n_orders": len(self.orders)},
                  open(self.path(), "w"), ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, pid):
        d = json.load(open(STORE / f"{pid}.json"))
        p = cls(d["pid"], d["name"], d["start_balance"], d["strategy"], d["instruments"], d.get("mode", "paper"))
        p.created = d["created"]; p.exec.balances = d["balances"]; p.state = d["state"]
        return p

    def equity(self):
        return self.exec.equity_usdt()

    def status(self):
        eq = self.equity()
        return {"pid": self.pid, "name": self.name, "mode": self.mode, "strategy": self.strategy,
                "instruments": self.instruments, "start_balance": self.start_balance,
                "equity": round(eq, 2), "pnl_pct": round((eq / self.start_balance - 1) * 100, 2),
                "open_positions": {k: v for k, v in self.state.get("positions", {}).items() if v},
                "n_orders": len(self.orders), "created": self.created, "simulation": self.exec.SIMULATION}


class PortfolioManager:
    def __init__(self):
        self.portfolios = {}
        self._load_all()

    def _load_all(self):
        for f in STORE.glob("*.json"):
            try:
                p = Portfolio.load(f.stem); self.portfolios[p.pid] = p
            except Exception:
                pass

    def create(self, name, start_balance, strategy, instruments, mode="paper"):
        pid = f"pf-{int(time.time())}-{len(self.portfolios)+1}"
        p = Portfolio(pid, name, start_balance, strategy, instruments, mode)
        p.save(); self.portfolios[pid] = p; self._write_status()
        return p

    def from_research(self, run_id, name, start_balance=10000):
        from ..lab import registry
        for row in registry.leaderboard(limit=1000):
            if row["run_id"] == run_id:
                return self.create(name, start_balance, row["strategy"], ["BTC_USDT"], mode="paper")
        raise KeyError(f"эксперимент {run_id} не найден")

    def delete(self, pid):
        if pid in self.portfolios:
            (STORE / f"{pid}.json").unlink(missing_ok=True)
            del self.portfolios[pid]; self._write_status()

    def all_status(self):
        return [p.status() for p in self.portfolios.values()]

    def _write_status(self):
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"portfolios": self.all_status(), "count": len(self.portfolios),
                   "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                  open(STATUS, "w"), ensure_ascii=False, indent=1)


LIVE_PRESETS = {
    "spot_basic_100usdt": {"name": "Gate.io Spot базовый", "mode": "live", "start_balance": 100,
        "quote": "USDT", "strategy": "S11", "instruments": ["BTC_USDT"], "max_positions": 1,
        "risk_usdt_per_pos": 20, "ready": False,
        "guard": "требует GATEIO_API_KEY/SECRET + LIVE_CONFIRMED + runtime=live (safety.py). "
                 "Автоучёт min_notional Gate.io (3 USDT) и precision."},
    "adaptive_ai_10_100usdt": {"name": "Adaptive AI Strategy", "mode": "live", "start_balance": 50,
        "quote": "USDT", "strategy": "ADAPTIVE", "instruments": ["BTC_USDT"], "max_positions": 1,
        "risk_usdt_per_pos": 10, "ready": False,
        "guard": "отдельный портфель, свой журнал. LLM-советник + автовалидация. Live только после "
                 "shadow->paper_canary и ввода ключей."},
}
