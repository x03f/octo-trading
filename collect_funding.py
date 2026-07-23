"""Сборщик истории ставок funding для перп-контрактов (strategy-lab, задача #9).

Зачем: без фандинга фьючерсные бэктесты систематически врут (лонг платит / шорт получает
на границе 00:00/08:00/16:00 UTC). Разблокирует S2 «Базис» (carry на фандинге) и
funding-tilt в S1 «Флюгер».

Вселенная: монеты, УЖЕ лежащие в озере OHLCV, у которых есть USDT-M перп на Binance.
Формат: parquet на монету, колонки (funding_time, funding_rate). Резюмируемый: готовые пропускает.
Запуск: /opt/octobot/bot/venv/bin/python collect_funding.py
"""
import os, time, json
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import ccxt

LAKE = "/opt/octobot/strategy-lab/data"
FUND = f"{LAKE}/funding"
OHLCV_1D = f"{LAKE}/ohlcv/1d"
YEARS = 2


def lake_universe():
    """Монеты, которые уже есть в озере (по 1d-файлам)."""
    suf = "USDT.parquet"
    return sorted(f[:-len(suf)] for f in os.listdir(OHLCV_1D) if f.endswith(suf))


def fetch_funding(ex, symbol, since_ms):
    """История ставок фандинга, постранично (limit 1000). Дедуп по времени."""
    rows, cursor = [], since_ms
    while True:
        batch = ex.fetch_funding_rate_history(symbol, since=cursor, limit=1000)
        if not batch:
            break
        rows += batch
        nxt = batch[-1]["timestamp"] + 1
        if nxt <= cursor or len(batch) < 1000:
            break
        cursor = nxt
        time.sleep(ex.rateLimit / 1000.0)
    seen, out = set(), []
    for r in rows:
        ts = r["timestamp"]
        if ts is not None and ts not in seen:
            seen.add(ts)
            out.append((ts, float(r["fundingRate"])))
    out.sort(key=lambda x: x[0])
    return out


def write_parquet(path, rows):
    a = np.array(rows, dtype="float64")
    tbl = pa.table({"funding_time": a[:, 0].astype("int64"), "funding_rate": a[:, 1]})
    pq.write_table(tbl, path, compression="zstd")


def main():
    os.makedirs(FUND, exist_ok=True)
    uni = lake_universe()
    print(f"вселенная озера: {len(uni)} монет", flush=True)

    ex = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 30000})
    markets = ex.load_markets()
    # перп USDT-M: символ вида BTC/USDT:USDT, тип swap, активен
    have_perp = []
    for base in uni:
        sym = f"{base}/USDT:USDT"
        m = markets.get(sym)
        if m and m.get("swap") and m.get("active", True):
            have_perp.append((base, sym))
    no_perp = [b for b in uni if not any(b == x[0] for x in have_perp)]
    print(f"с перпом на Binance: {len(have_perp)} | без перпа: {len(no_perp)} "
          f"({', '.join(no_perp[:12])}...)", flush=True)

    since = int(time.time() * 1000) - YEARS * 365 * 24 * 3600 * 1000
    manifest = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "years": YEARS, "exchange": "binanceusdm", "settlement_hours_utc": [0, 8, 16],
                "with_perp": len(have_perp), "coverage": {}}
    done, total_pts, t0 = 0, 0, time.time()
    for i, (base, sym) in enumerate(have_perp):
        path = f"{FUND}/{base}USDT.parquet"
        if os.path.exists(path):                          # резюмируемость
            done += 1
            continue
        try:
            rows = fetch_funding(ex, sym, since)
            if rows:
                write_parquet(path, rows)
                total_pts += len(rows)
                manifest["coverage"][base] = {"points": len(rows), "from": rows[0][0], "to": rows[-1][0]}
        except Exception as e:
            print(f"  [!] {sym}: {type(e).__name__}: {str(e)[:70]}", flush=True)
        done += 1
        el = time.time() - t0
        eta = (el / max(done, 1)) * (len(have_perp) - done) / 60
        print(f"[{i+1}/{len(have_perp)}] {base}: {manifest['coverage'].get(base, {}).get('points', 0)} точек "
              f"| всего {total_pts:,} | ETA ~{eta:.0f} мин", flush=True)
        json.dump(manifest, open(f"{LAKE}/funding_manifest.json", "w"), indent=1)
    print(f"\n=== ГОТОВО: {len(manifest['coverage'])} монет с фандингом | {total_pts:,} точек | "
          f"{(time.time()-t0)/60:.0f} мин ===", flush=True)


if __name__ == "__main__":
    main()
