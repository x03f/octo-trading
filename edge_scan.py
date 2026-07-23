"""ЗАМЕР КРАЯ (event study) — есть ли краткосрочный разворот, и больше ли он комиссий.

НЕ стратегия. Отвечает на один вопрос: если монета аномально просела ОТНОСИТЕЛЬНО корзины
за последние L баров, сколько в среднем даёт возврат на следующих H барах (в базисных пунктах)?
Сравниваем с круговыми костами Gate VIP2. Если край < 2× костов — идею закрываем, не строим.

Честность: сигнал на баре t считается ТОЛЬКО из данных ≤t; форвард меряется строго ПОСЛЕ t.
Рыночное движение вычитается (медиана по срезу) → меряем чистый кросс-секционный эффект.
Запуск: python edge_scan.py [tf]
"""
import sys, os, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore")
import numpy as np
import pyarrow.parquet as pq

LAKE = "/opt/octobot/strategy-lab/data/ohlcv"

# Gate VIP2, круговые косты в базисных пунктах (1 бп = 0.01%)
COSTS = {
    "перп maker→maker": 2 * 0.020 * 100,   # 4.0 бп
    "перп maker→taker": (0.020 + 0.046) * 100,  # 6.6 бп
    "перп taker→taker": 2 * 0.046 * 100,   # 9.2 бп
    "спот maker→maker": 2 * 0.075 * 100,   # 15.0 бп
}


def load_close_matrix(tf):
    """Только колонка close (экономим память): → (ts, coins, close[T,N] float32)."""
    d = f"{LAKE}/{tf}"
    suf = "USDT.parquet"
    coins = sorted(f[:-len(suf)] for f in os.listdir(d) if f.endswith(suf))
    series = {}
    for c in coins:
        t = pq.read_table(f"{d}/{c}{suf}", columns=["timestamp", "close"])
        ts = t.column("timestamp").to_numpy(zero_copy_only=False)
        cl = t.column("close").to_numpy(zero_copy_only=False)
        o = np.argsort(ts)
        series[c] = (ts[o], cl[o])
    allts = np.unique(np.concatenate([s[0] for s in series.values()]))
    T, N = len(allts), len(coins)
    C = np.full((T, N), np.nan, dtype=np.float32)
    for j, c in enumerate(coins):
        ts, cl = series[c]
        C[np.searchsorted(allts, ts), j] = cl
    return allts, coins, C


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    t0 = time.time()
    ts, coins, C = load_close_matrix(tf)
    T, N = C.shape
    bar_min = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}[tf]
    print(f"== ЗАМЕР КРАЯ | tf={tf} | {N} монет × {T} баров | загрузка {time.time()-t0:.0f}с ==")

    # доходности и вычитание рынка (медиана по срезу = устойчиво к выбросам)
    R = np.full((T, N), np.nan, dtype=np.float32)
    np.divide(C[1:], C[:-1], out=R[1:], where=(C[:-1] > 0))
    R[1:] -= 1.0
    mkt = np.nanmedian(R, axis=1).astype(np.float32)
    X = R - mkt[:, None]                      # избыточная доходность к корзине

    fin = np.isfinite(X)
    Xf = np.where(fin, X, 0.0).astype(np.float32)
    Cx = np.cumsum(Xf, axis=0, dtype=np.float64)      # накопленный избыток
    Vf = np.cumsum(fin, axis=0, dtype=np.int32)       # счётчик валидных баров

    del R, X, C
    LOOKBACKS = [1, 2, 4, 8]     # баров назад: сила провала
    HORIZONS = [1, 2, 4, 8, 16]  # баров вперёд: где меряем возврат
    QUANT = 0.05                 # 5% самых просевших (и 5% самых выросших)

    print(f"  1 бар = {bar_min} мин | отбор: {int(QUANT*100)}% крайних по срезу")
    print("  ПОРОГИ костов (круговые): " + ", ".join(f"{k} {v:.1f}бп" for k, v in COSTS.items()), flush=True)

    # форвард-матрицы считаем ОДИН раз (зависят только от H)
    Fs = {}
    for H in HORIZONS:
        F = np.full((T, N), np.nan, dtype=np.float32)
        F[:-H] = (Cx[H:] - Cx[:-H]).astype(np.float32)
        ok = np.zeros((T, N), bool)
        ok[:-H] = (Vf[H:] - Vf[:-H]) == H
        F[~ok] = np.nan
        Fs[H] = F
    print(f"  форвард-матрицы готовы ({time.time()-t0:.0f}с)", flush=True)

    for L in LOOKBACKS:
        S = np.full((T, N), np.nan, dtype=np.float32)
        S[L:] = (Cx[L:] - Cx[:-L]).astype(np.float32)
        okS = np.zeros((T, N), bool)
        okS[L:] = (Vf[L:] - Vf[:-L]) == L
        S[~okS] = np.nan
        lo = np.nanquantile(S, QUANT, axis=1)          # пороги — ОДИН раз на L
        hi = np.nanquantile(S, 1 - QUANT, axis=1)
        sel_lo = S <= lo[:, None]
        sel_hi = S >= hi[:, None]

        print(f"\n  --- сигнал: провал за последние {L} бар(ов) = {L*bar_min} мин ---")
        print("    гориз.  " + "".join(f"{h*bar_min:>7}м" for h in HORIZONS), flush=True)
        rl, rw, rn = [], [], []
        for H in HORIZONS:
            F = Fs[H]
            finF = np.isfinite(F)
            a = F[sel_lo & finF]
            b = F[sel_hi & finF]
            ma = float(np.mean(a)) * 1e4 if a.size else np.nan
            mb = float(np.mean(b)) * 1e4 if b.size else np.nan
            rl.append(ma); rw.append(mb)
            rn.append(ma - mb - 2 * COSTS["перп maker→maker"])   # две ноги
        print("    лузеры→" + "".join(f"{v:+7.1f}" for v in rl) + "  бп")
        print("    винеры→" + "".join(f"{v:+7.1f}" for v in rw) + "  бп")
        print("    ЛШ-нетто" + "".join(f"{v:+7.1f}" for v in rn) + "  бп (после костов)", flush=True)

    print(f"\n  готово за {time.time()-t0:.0f}с")
    print("  ЧТЕНИЕ: положительное «лузеры→» = просевшие отскакивают (разворот).")
    print("  Строить стратегию имеет смысл, только если ВАЛОВЫЙ край ≥ 2× костов (≥8бп на ногу).")


if __name__ == "__main__":
    main()
