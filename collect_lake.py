"""Сборщик озера данных для бэктестов (strategy-lab).
Вселенная: топ-100 по капе ∪ топ-100 по объёму ∪ trending (CoinGecko) → маппинг на Binance USDT-пары.
ТФ: 5m/15m/1h/4h/1d, 2 года. Формат: parquet (zstd). Резюмируемый: готовые файлы пропускает.
Запуск: /opt/octobot/bot/venv/bin/python collect_lake.py
"""
import os, sys, time, json, urllib.request
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import ccxt

LAKE = "/opt/octobot/strategy-lab/data"
OHLCV = f"{LAKE}/ohlcv"
TFS = ["5m", "15m", "1h", "4h", "1d"]
YEARS = 2
STABLE_WRAP = {"USDT","USDC","DAI","TUSD","FDUSD","USDE","BUSD","USDD","PYUSD","USDS","GUSD",
               "FRAX","LUSD","USD1","WBTC","WETH","STETH","WSTETH","WEETH","WBETH","CBBTC",
               "RETH","WBNB","WHYPE","BSC-USD","XAUT","PAXG"}


def cg(path):
    req = urllib.request.Request("https://api.coingecko.com/api/v3" + path,
                                 headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def build_universe():
    syms = []
    try:
        # топ-250 по капитализации ∪ топ-250 по объёму (прокси медиапопулярности) ∪ trending
        for order in ("market_cap_desc", "volume_desc"):
            for page in (1, 2):
                data = cg(f"/coins/markets?vs_currency=usd&order={order}&per_page=250&page={page}")
                syms += [c["symbol"].upper() for c in data]
                time.sleep(2.5)
        tr = cg("/search/trending")
        syms += [c["item"]["symbol"].upper() for c in tr.get("coins", [])]
    except Exception as e:
        print(f"[cg] предупреждение: {type(e).__name__}: {e}", flush=True)
    uni, seen = [], set()
    for s in syms:
        if s in STABLE_WRAP or s in seen:
            continue
        seen.add(s); uni.append(s)
    return uni


def fetch_ohlcv(ex, symbol, tf, since_ms):
    rows, cursor = [], since_ms
    tf_ms = ex.parse_timeframe(tf) * 1000
    while True:
        batch = ex.fetch_ohlcv(symbol, tf, since=cursor, limit=1000)
        if not batch:
            break
        rows += batch
        nxt = batch[-1][0] + tf_ms
        if nxt <= cursor or len(batch) < 1000:
            break
        cursor = nxt
        time.sleep(ex.rateLimit / 1000.0)
    # дедуп по ts
    seen, out = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0]); out.append(r)
    out.sort(key=lambda r: r[0])
    return out


def write_parquet(path, rows):
    a = np.array(rows, dtype="float64")
    tbl = pa.table({
        "timestamp": a[:, 0].astype("int64"),
        "open": a[:, 1], "high": a[:, 2], "low": a[:, 3],
        "close": a[:, 4], "volume": a[:, 5],
    })
    pq.write_table(tbl, path, compression="zstd")


def main():
    os.makedirs(OHLCV, exist_ok=True)
    for tf in TFS:
        os.makedirs(f"{OHLCV}/{tf}", exist_ok=True)
    print("строю вселенную (CoinGecko)...", flush=True)
    uni = build_universe()
    print(f"вселенная: {len(uni)} тикеров", flush=True)

    ex = ccxt.binance({"enableRateLimit": True, "timeout": 30000})
    markets = ex.load_markets()
    pairs = [(s, f"{s}/USDT") for s in uni if f"{s}/USDT" in markets and markets[f"{s}/USDT"].get("active", True)]
    skipped = [s for s in uni if f"{s}/USDT" not in markets]
    print(f"на Binance: {len(pairs)} пар | нет на Binance: {len(skipped)} ({', '.join(skipped[:15])}...)", flush=True)

    since = int(time.time() * 1000) - YEARS * 365 * 24 * 3600 * 1000
    manifest = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "years": YEARS, "timeframes": TFS, "exchange": "binance",
                "universe_size": len(pairs), "coverage": {}}
    total_candles, total_bytes, done, t0 = 0, 0, 0, time.time()
    n_jobs = len(pairs) * len(TFS)
    for i, (base, symbol) in enumerate(pairs):
        cov = {}
        for tf in TFS:
            path = f"{OHLCV}/{tf}/{base}USDT.parquet"
            if os.path.exists(path):                       # резюмируемость
                done += 1; continue
            try:
                rows = fetch_ohlcv(ex, symbol, tf, since)
                if rows:
                    write_parquet(path, rows)
                    sz = os.path.getsize(path)
                    total_candles += len(rows); total_bytes += sz
                    cov[tf] = {"candles": len(rows), "from": rows[0][0], "to": rows[-1][0]}
            except Exception as e:
                print(f"  [!] {symbol} {tf}: {type(e).__name__}: {str(e)[:60]}", flush=True)
            done += 1
        if cov:
            manifest["coverage"][base] = cov
        el = time.time() - t0
        eta = (el / max(done, 1)) * (n_jobs - done) / 60
        print(f"[{i+1}/{len(pairs)}] {base}: {sum(c['candles'] for c in cov.values()) if cov else 0} свечей "
              f"| всего {total_bytes/1e6:.0f} МБ | ETA ~{eta:.0f} мин", flush=True)
        json.dump(manifest, open(f"{LAKE}/manifest.json", "w"), indent=1)
    print(f"\n=== ГОТОВО: {len(pairs)} пар × {len(TFS)} ТФ | {total_candles:,} свечей | "
          f"{total_bytes/1e9:.2f} ГБ | {(time.time()-t0)/60:.0f} мин ===", flush=True)


if __name__ == "__main__":
    main()
