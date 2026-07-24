"""Жизненный цикл конфигураций Adaptive AI: champion/challenger, shadow→canary, rollback.

Принцип: LLM предлагает → автовалидация бэктестом → challenger в shadow/paper canary →
при подтверждении promote в champion; при деградации — автоматический rollback к последней стабильной.
Реестр версий с источником изменения, результатами валидации, статусом.
"""
import json, time
from pathlib import Path

REG = Path("/opt/octobot/nautilus-lab/var/adaptive_versions.jsonl")
STATE = Path("/opt/octobot/nautilus-lab/web/data/adaptive_lifecycle.json")

STAGES = ["shadow", "paper_canary", "live_canary", "champion"]


class ConfigVersion:
    def __init__(self, version, params, source, ts=None, stage="shadow"):
        self.version = version
        self.params = params
        self.source = source            # llm|deterministic|manual|classical
        self.ts = ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.stage = stage
        self.validation = None
        self.result = None              # фактический результат в стадии
        self.retired_reason = None

    def as_dict(self):
        return {k: getattr(self, k) for k in
                ("version", "params", "source", "ts", "stage", "validation", "result", "retired_reason")}


class LifecycleManager:
    """Champion/challenger + стадии + rollback. Реестр версий в JSONL."""
    def __init__(self):
        REG.parent.mkdir(parents=True, exist_ok=True)
        self.versions = self._load()
        self.champion = self._current_champion()

    def _load(self):
        if not REG.exists():
            return []
        return [json.loads(l) for l in REG.read_text().strip().splitlines() if l.strip()]

    def _append(self, v: dict):
        with open(REG, "a") as f:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
        self.versions.append(v)

    def _current_champion(self):
        champs = [v for v in self.versions if v.get("stage") == "champion" and not v.get("retired_reason")]
        return champs[-1] if champs else None

    def set_baseline(self, params, source="manual"):
        """Установить первый champion (стабильная базовая конфигурация)."""
        v = ConfigVersion(f"v{len(self.versions)+1}", params, source, stage="champion").as_dict()
        self._append(v)
        self.champion = v
        self._write_state()
        return v

    def propose_challenger(self, params, source, validation):
        """Новая версия-претендент. Входит в SHADOW. Валидация обязательна."""
        v = ConfigVersion(f"v{len(self.versions)+1}", params, source, stage="shadow").as_dict()
        v["validation"] = validation
        self._append(v)
        self._write_state()
        return v

    def promote(self, version, to_stage, result=None):
        """Продвинуть версию по стадиям. Только вперёд, при положительном результате."""
        idx = STAGES.index(to_stage)
        for v in self.versions:
            if v["version"] == version:
                cur_idx = STAGES.index(v["stage"])
                if idx != cur_idx + 1 and to_stage != "champion":
                    raise ValueError(f"нельзя перепрыгнуть стадию {v['stage']}->{to_stage}")
                v["stage"] = to_stage
                v["result"] = result
                self._append(dict(v))
                if to_stage == "champion":
                    if self.champion:
                        self._retire(self.champion["version"], "superseded")
                    self.champion = v
                self._write_state()
                return v
        raise KeyError(version)

    def _retire(self, version, reason):
        for v in self.versions:
            if v["version"] == version:
                v["retired_reason"] = reason

    def rollback(self):
        """Автоматический откат к последней СТАБИЛЬНОЙ (предыдущий РАЗЛИЧНЫЙ champion)."""
        cur_ver = self.champion["version"] if self.champion else None
        # различные версии, побывавшие champion, кроме текущей (в порядке появления)
        seen, champ_versions = set(), []
        for v in self.versions:
            if v.get("stage") == "champion" and v["version"] != cur_ver and v["version"] not in seen:
                seen.add(v["version"]); champ_versions.append(v)
        if not champ_versions:
            return None
        prev = champ_versions[-1]
        restored = ConfigVersion(f"v{len(self.versions)+1}", prev["params"], "rollback", stage="champion").as_dict()
        restored["retired_reason"] = None
        if self.champion:
            self._retire(self.champion["version"], "rolled_back")
        self._append(restored)
        self.champion = restored
        self._write_state()
        return restored

    def _write_state(self):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        challengers = [v for v in self.versions if v["stage"] in ("shadow", "paper_canary", "live_canary")
                       and not v.get("retired_reason")]
        json.dump({
            "champion": self.champion, "challengers": challengers[-5:],
            "total_versions": len(self.versions),
            "stages": STAGES,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, open(STATE, "w"), ensure_ascii=False, indent=1)


def classical_adaptation(stats, params):
    """Классическая (не-LLM) алго-адаптация параметров — baseline для сравнения с LLM.
    Правило: при росте волатильности увеличиваем окна (консервативнее), при падении — уменьшаем."""
    new = dict(params)
    vol = stats.volatility or 0.0
    ref = (stats.regime_signals or {}).get("vol_ref", vol) or vol
    if vol > ref * 1.3 and "chan_n" in new:
        new["chan_n"] = int(new["chan_n"] * 1.2)
    elif vol < ref * 0.7 and "chan_n" in new:
        new["chan_n"] = max(5, int(new["chan_n"] * 0.8))
    return new
