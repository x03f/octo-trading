"""Реестр экспериментов (DuckDB). Каждый run: уникальный ID, версия кода/данных, метрики, вердикт.

Воспроизводимость: git_sha + data_manifest_sha + seed фиксируют эксперимент. Артефакты (equity,
метрики) — файлами рядом. Leaderboard — SQL-запрос к реестру.
"""
import os, json, time, hashlib, subprocess
from pathlib import Path
import duckdb

DB = Path("/opt/octobot/nautilus-lab/var/registry.duckdb")
ARTIFACTS = Path("/opt/octobot/nautilus-lab/var/experiments")
DB.parent.mkdir(parents=True, exist_ok=True)
ARTIFACTS.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
  run_id VARCHAR PRIMARY KEY, created VARCHAR, git_sha VARCHAR, data_sha VARCHAR,
  strategy VARCHAR, params VARCHAR, universe VARCHAR, tf VARCHAR, period VARCHAR,
  seed INTEGER, n_trades INTEGER, total_return DOUBLE, sharpe DOUBLE, sortino DOUBLE,
  calmar DOUBLE, max_dd DOUBLE, turnover DOUBLE, profit_factor DOUBLE, expectancy DOUBLE,
  valid_sharpe DOUBLE, test_sharpe DOUBLE, wf_sharpe DOUBLE, mc_sharpe_p05 DOUBLE,
  mc_sharpe_p95 DOUBLE, benchmark_return DOUBLE, verdict VARCHAR, artifact VARCHAR
);
"""


def _git_sha():
    try:
        return subprocess.run(["git", "-C", "/opt/octobot/strategy-lab", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "unknown"


def _data_sha():
    m = Path("/opt/octobot/strategy-lab/data/manifest.json")
    if m.exists():
        return hashlib.sha256(m.read_bytes()).hexdigest()[:12]
    return "no-manifest"


def _conn():
    c = duckdb.connect(str(DB))
    c.execute(SCHEMA)
    return c


def new_run_id(strategy):
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    h = hashlib.sha1(f"{strategy}{time.time_ns()}".encode()).hexdigest()[:6]
    return f"exp-{ts}-{strategy}-{h}"


def record(run: dict):
    """Записать эксперимент + сохранить артефакт (метрики+equity)."""
    run["git_sha"] = run.get("git_sha") or _git_sha()
    run["data_sha"] = run.get("data_sha") or _data_sha()
    art = ARTIFACTS / f"{run['run_id']}.json"
    json.dump(run, open(art, "w"), ensure_ascii=False, default=lambda x: None)
    run["artifact"] = str(art)
    cols = ["run_id", "created", "git_sha", "data_sha", "strategy", "params", "universe", "tf",
            "period", "seed", "n_trades", "total_return", "sharpe", "sortino", "calmar", "max_dd",
            "turnover", "profit_factor", "expectancy", "valid_sharpe", "test_sharpe", "wf_sharpe",
            "mc_sharpe_p05", "mc_sharpe_p95", "benchmark_return", "verdict", "artifact"]
    vals = [run.get(c) for c in cols]
    if isinstance(vals[cols.index("params")], (dict, list)):
        vals[cols.index("params")] = json.dumps(vals[cols.index("params")], ensure_ascii=False)
    c = _conn()
    c.execute(f"INSERT OR REPLACE INTO experiments ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})", vals)
    c.close()
    return run["run_id"]


def leaderboard(order="test_sharpe", limit=50):
    c = _conn()
    rows = c.execute(f"SELECT run_id,strategy,total_return,sharpe,test_sharpe,max_dd,n_trades,verdict,created "
                     f"FROM experiments ORDER BY {order} DESC NULLS LAST LIMIT {limit}").fetchall()
    cols = ["run_id", "strategy", "total_return", "sharpe", "test_sharpe", "max_dd", "n_trades", "verdict", "created"]
    c.close()
    return [dict(zip(cols, r)) for r in rows]


def count():
    c = _conn(); n = c.execute("SELECT count(*) FROM experiments").fetchone()[0]; c.close()
    return n
