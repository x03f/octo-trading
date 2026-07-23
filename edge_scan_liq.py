"""ЗАМЕР КРАЯ С ФИЛЬТРОМ ЛИКВИДНОСТИ — живёт ли отскок там, где его реально можно взять.

Ключевой вопрос: край +16бп на всех 316 монетах может целиком сидеть в неликвидных альтах,
где проскальзывание его съест. Здесь ограничиваем срез топ-N по обороту и смотрим, что остаётся.

Честность: ликвидность считается по ТРЕЙЛИНГ-окну (прошлые 24ч), не по всему периоду —
иначе это подглядывание в будущее («знаем, кто окажется ликвидным»).
Запуск: python edge_scan_liq.py [tf]
"""
import sys, os, time, warnings
sys.path.insert(0, "/opt/octobot/strategy-lab")
warnings.filterwarnings("ignore")
import numpy as np
import pyarrow.parquet as pq

LAKE = "/opt/octobot/strategy-lab/data/ohlcv"
RT_MAKER_BP = 2 * 0.020 * 100          # круговая мейкер-мейкер на ОДНУ ногу = 4.0 бп (Gate VIP2 перп)


def load_close_vol(tf):
    d = f"{LAKE}/{tf}"
    suf = "USDT.parquet"
    coins = sorted(f[:-len(suf)] for f in os.listdir(d) if f.endswith(suf))
    ser = {}
    for c in coins:
        t = pq.read_table(f"{d}/{c}{suf}", columns=["timestamp", "close", "volume"])
        ts = t.column("timestamp").to_numpy(zero_copy_only=False)
        o = np.argsort(ts)
        ser[c] = (ts[o], t.column("close").to_numpy(zero_copy_only=False)[o],
                  t.column("volume").to_numpy(zero_copy_only=False)[o])
    allts = np.unique(np.concatenate([s[0] for s in ser.values()]))
    T, N = len(allts), len(coins)
    C = np.full((T, N), np.nan, dtype=np.float32)
    V = np.full((T, N), np.nan, dtype=np.float32)
    for j, c in enumerate(coins):
        ts, cl, vo = ser[c]
        idx = np.searchsorted(allts, ts)
        C[idx, j] = cl
        V[idx, j] = vo
    return allts, coins, C, V


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    t0 = time.time()
    ts, coins, C, V = load_close_vol(tf)
    T, N = C.shape
    bar_min = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}[tf]
    print(f"== КРАЙ × ЛИКВИДНОСТЬ | tf={tf} | {N} монет × {T} баров | загрузка {time.time()-t0:.0f}с ==", flush=True)

    # избыточная доходность к корзине
    R = np.full((T, N), np.nan, dtype=np.float32)
    np.divide(C[1:], C[:-1], out=R[1:], where=(C[:-1] > 0))
    R[1:] -= 1.0
    X = R - np.nanmedian(R, axis=1).astype(np.float32)[:, None]
    fin = np.isfinite(X)
    Cx = np.cumsum(np.where(fin, X, 0.0).astype(np.float32), axis=0, dtype=np.float64)
    Vf = np.cumsum(fin, axis=0, dtype=np.int32)

    # трейлинг-ликвидность: средний долларовый оборот за прошлые 24ч
    W = max(4, int(24 * 60 / bar_min))
    DV = np.where(np.isfinite(C) & np.isfinite(V), C * V, 0.0).astype(np.float64)
    Cd = np.cumsum(DV, axis=0)
    TM = np.full((T, N), -np.inf, dtype=np.float64)
    TM[W:] = (Cd[W:] - Cd[:-W]) / W
    TM[~np.isfinite(C)] = -np.inf              # нелистящиеся не участвуют
    del R, X, DV, Cd, V, C
    print(f"  ликвидность посчитана, окно {W} баров = 24ч ({time.time()-t0:.0f}с)", flush=True)

    LOOKBACKS, HORIZONS, QUANT = [1, 2], [2, 4, 8, 16], 0.05
    Fs = {}
    for H in HORIZONS:
        F = np.full((T, N), np.nan, dtype=np.float32)
        F[:-H] = (Cx[H:] - Cx[:-H]).astype(np.float32)
        ok = np.zeros((T, N), bool)
        ok[:-H] = (Vf[H:] - Vf[:-H]) == H
        F[~ok] = np.nan
        Fs[H] = F
    print(f"  форвард готов ({time.time()-t0:.0f}с)", flush=True)

    for TOP in (50, 100, 200, N):
        tag = "ВСЕ" if TOP >= N else f"топ-{TOP}"
        if TOP < N:
            thr_liq = -np.partition(-TM, TOP - 1, axis=1)[:, TOP - 1]
            liquid = TM >= thr_liq[:, None]
        else:
            liquid = np.isfinite(TM)
        print(f"\n  ═══ ЛИКВИДНОСТЬ: {tag} по обороту ═══", flush=True)
        for L in LOOKBACKS:
            S = np.full((T, N), np.nan, dtype=np.float32)
            S[L:] = (Cx[L:] - Cx[:-L]).astype(np.float32)
            okS = np.zeros((T, N), bool)
            okS[L:] = (Vf[L:] - Vf[:-L]) == L
            S[~(okS & liquid)] = np.nan            # срез ТОЛЬКО из ликвидных
            lo = np.nanquantile(S, QUANT, axis=1)
            hi = np.nanquantile(S, 1 - QUANT, axis=1)
            sel_lo, sel_hi = S <= lo[:, None], S >= hi[:, None]
            gl, gw, nl = [], [], []
            for H in HORIZONS:
                F = Fs[H]
                fF = np.isfinite(F)
                a, b = F[sel_lo & fF], F[sel_hi & fF]
                ma = float(np.mean(a)) * 1e4 if a.size else np.nan
                mb = float(np.mean(b)) * 1e4 if b.size else np.nan
                gl.append(ma); gw.append(mb); nl.append(ma - RT_MAKER_BP)
            print(f"   L={L} ({L*bar_min}м)  гориз:" + "".join(f"{h*bar_min:>7}м" for h in HORIZONS))
            print("     лузеры(вал)" + "".join(f"{v:+7.1f}" for v in gl) + "  бп")
            print("     винеры(вал)" + "".join(f"{v:+7.1f}" for v in gw) + "  бп")
            print("     ЛОНГ-ОНЛИ нетто" + "".join(f"{v:+7.1f}" for v in nl) + "  бп ← решающая строка", flush=True)

    print(f"\n  готово за {time.time()-t0:.0f}с")
    print("  ЧИТАТЬ: если на топ-50/100 лонг-онли нетто уходит к нулю — край живёт в неликвиде и НЕ берётся.")


if __name__ == "__main__":
    main()
