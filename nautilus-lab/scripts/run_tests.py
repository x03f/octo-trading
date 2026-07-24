#!/usr/bin/env python3
"""P10: прогон тест-сюиты ПО КАТЕГОРИЯМ с явными ярлыками. Возвращает сводку и код возврата.
Категории соответствуют требованиям ТЗ: адаптеры/исполнение, Nautilus-рантайм, адаптивный AI,
данные/каталог, воспроизводимость, битые данные, производительность, E2E, smoke дашборда."""
import subprocess, sys, os

ROOT = "/opt/octobot/strategy-lab/nautilus-lab"
CATEGORIES = {
    "gateio-adapter":   ["test_gateio.py", "test_gateio_orders.py", "test_reconcile.py", "test_websocket.py", "test_futures.py"],
    "nautilus-runtime": ["test_nautilus.py"],
    "paper-execution":  ["test_paper_service.py", "test_portfolios.py"],
    "adaptive-ai":      ["test_adaptive.py", "test_adaptive_lifecycle.py"],
    "data-catalog":     ["test_catalog.py"],
    "reproducibility":  ["test_reproducibility.py"],
    "corrupted-data":   ["test_corrupted_data.py"],
    "performance":      ["test_performance.py"],
    "e2e-lifecycle":    ["test_e2e_lifecycle.py"],
    "dashboard-smoke":  ["test_dashboard_smoke.py"],
}


def main():
    env = dict(os.environ, PYTHONPATH=f"{ROOT}:/opt/octobot/strategy-lab")
    py = "/opt/octobot/nautilus-venv/bin/python"
    only = sys.argv[1] if len(sys.argv) > 1 else None
    total_pass = total_fail = 0
    print(f"{'КАТЕГОРИЯ':<20} {'РЕЗУЛЬТАТ':>12}")
    print("-" * 34)
    for cat, files in CATEGORIES.items():
        if only and only != cat:
            continue
        paths = [f"{ROOT}/tests/{f}" for f in files]
        r = subprocess.run([py, "-m", "pytest", *paths, "-q", "--no-header"],
                           capture_output=True, text=True, env=env, cwd=ROOT)
        line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        p = f = 0
        import re
        mp = re.search(r"(\d+) passed", line); mf = re.search(r"(\d+) failed", line)
        if mp: p = int(mp.group(1))
        if mf: f = int(mf.group(1))
        total_pass += p; total_fail += f
        mark = "✓" if f == 0 else "✗"
        print(f"{cat:<20} {mark} {p:>3} pass {f} fail")
    print("-" * 34)
    print(f"{'ИТОГО':<20} {total_pass} passed, {total_fail} failed")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
