#!/usr/bin/env python3
"""P4: массовый прогон экспериментов (batch) по списку стратегий → реестр DuckDB.
Каждый: настоящий walk-forward + трёхчастный + Monte Carlo + trade-статистика + полный артефакт."""
import sys
sys.path.insert(0, "/opt/octobot/strategy-lab")
sys.path.insert(0, "/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.lab.experiment import run_experiment
from ntlab.lab import registry

STRATS = sys.argv[1:] or ["S8", "S4", "S5", "S1", "S9", "S3"]
print(f"BATCH: {len(STRATS)} стратегий → реестр")
for k in STRATS:
    try:
        r = run_experiment(k)
        wf = r.get("walk_forward", {})
        print(f"  {k:4} ret {r['total_return']*100:+6.1f}% Sh {r['sharpe'] or 0:+.2f} "
              f"TEST {r['test_sharpe'] or 0:+.2f} WF-OOS {r['wf_sharpe'] or 0:+.2f} "
              f"trades {r['n_trades']} PF {r['profit_factor']} fees {r['est_fees_frac']} -> {r['verdict']}", flush=True)
    except Exception as e:
        print(f"  {k}: ошибка {str(e)[:80]}", flush=True)
print(f"реестр: {registry.count()} экспериментов")
