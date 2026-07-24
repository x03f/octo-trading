"""Мульти-портфели paper на живых данных Gate.io. Несколько портфелей, реальные комиссии, slippage.

Каждый портфель: id, стартовый баланс, стратегия, инструменты, состояние, восстановление после
рестарта. Перевод research->paper. ОСНОВНОЕ исполнение — Nautilus (run_nautilus_portfolio: Strategy →
order lifecycle → SimulatedExchange → Nautilus Portfolio). Custom PaperExecution — только тестовый
oracle (ntlab-paper + unit). Реальные ордера невозможны без ключей и явного live-preset.
"""
import json, time
from pathlib import Path
from ..nautilus.paper_engine import run_isolated

STORE = Path("/opt/octobot/nautilus-lab/var/portfolios")
STATUS = Path("/opt/octobot/nautilus-lab/web/data/portfolios.json")
STORE.mkdir(parents=True, exist_ok=True)


class Portfolio:
    """Paper-портфель. ОСНОВНОЙ контур исполнения — Nautilus (run_nautilus_portfolio). Прогон ленивый
    и кэшируется (self.result). Поддерживает pause/resume и восстановление после рестарта."""
    def __init__(self, pid, name, start_balance, strategy, instruments, mode="paper"):
        self.pid = pid; self.name = name; self.start_balance = float(start_balance)
        self.strategy = strategy; self.instruments = instruments; self.mode = mode
        self.created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.paused = False
        self.result = None            # кэш Nautilus-прогона (equity/fills/positions/pnl)

    def path(self):
        return STORE / f"{self.pid}.json"

    def run(self):
        """Прогнать портфель через Nautilus (BacktestEngine). Не запускается на паузе."""
        if self.paused:
            return {"skipped": "paused"}
        self.result = run_isolated(self.strategy, self.instruments, self.start_balance)
        self.save()
        return self.result

    def pause(self):
        self.paused = True; self.save(); return {"pid": self.pid, "paused": True}

    def resume(self):
        self.paused = False; self.save(); return {"pid": self.pid, "paused": False}

    def save(self):
        json.dump({"pid": self.pid, "name": self.name, "start_balance": self.start_balance,
                   "strategy": self.strategy, "instruments": self.instruments, "mode": self.mode,
                   "created": self.created, "paused": self.paused, "result": self.result},
                  open(self.path(), "w"), ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, pid):
        d = json.load(open(STORE / f"{pid}.json"))
        p = cls(d["pid"], d["name"], d["start_balance"], d["strategy"], d["instruments"], d.get("mode", "paper"))
        p.created = d["created"]; p.paused = d.get("paused", False); p.result = d.get("result")
        return p

    def equity(self):
        return self.result["equity"] if self.result else self.start_balance

    def status(self):
        r = self.result or {}
        eq = self.equity()
        return {"pid": self.pid, "name": self.name, "mode": self.mode, "strategy": self.strategy,
                "instruments": self.instruments, "start_balance": self.start_balance,
                "equity": round(eq, 2), "pnl_pct": round((eq / self.start_balance - 1) * 100, 2) if self.start_balance else 0,
                "paused": self.paused, "engine": "nautilus-backtest", "is_nautilus": True,
                "fills": r.get("fills", 0), "positions": r.get("positions", 0),
                "n_instruments": r.get("n_instruments", len(self.instruments)),
                "ran": self.result is not None, "created": self.created, "simulation": True,
                "lifecycle": r.get("lifecycle", "Strategy → order lifecycle → SimulatedExchange → Nautilus Portfolio")}


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

    def run(self, pid):
        p = self.portfolios.get(pid)
        if not p:
            raise KeyError(pid)
        r = p.run(); self._write_status(); return r

    def pause(self, pid):
        p = self.portfolios.get(pid)
        if not p: raise KeyError(pid)
        r = p.pause(); self._write_status(); return r

    def resume(self, pid):
        p = self.portfolios.get(pid)
        if not p: raise KeyError(pid)
        r = p.resume(); self._write_status(); return r

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
