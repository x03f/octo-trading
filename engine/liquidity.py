"""Паспорт ликвидности и пер-монетная модель костов (Шаг 0).

Зачем: плоские косты (одна цифра bps на всех) занижают реальную стоимость входа на
неликвиде в 3-5 раз. Без пер-монетной модели любой бэктест по нишевым монетам недостоверен.

Что считает по каждой монете за окно W дней:
  · med_dv        — медианный дневной долларовый оборот (ёмкость)
  · cs_bps        — эффективный спред Corwin-Schultz из OHLC (стоимость пересечения книги)
  · amihud        — ценовое воздействие на $1 оборота (Amihud illiquidity)
  · zero/low/flat — доля мёртвых/замороженных баров (staleness по Lesmond)
  · rt_cost_bps   — ИТОГОВАЯ круговая стоимость сделки = биржевая комиссия + спред

Формализация валидированного прототипа liq_full.py (агентское исследование 23.07.2026).
Метод Corwin-Schultz и null-калибровка (NULL_K) взяты 1:1, арифметика проверена независимо.
"""
import math
import numpy as np
from .data import list_universe, load

DAY_MS = 86_400_000
SQ2 = 3.0 - 2.0 * math.sqrt(2.0)
NULL_K = 0.372            # CS_null_bps = NULL_K * sigma_bps (аналитическая поправка на vol-bias)
FLAT_MAX = 0.10           # >10% замороженных баров → оценка спреда невалидна


def _cs(h, l):
    """Corwin-Schultz spread. Возвращает (mean_bps с занулением отриц., доля отриц., n)."""
    h = np.asarray(h, float); l = np.asarray(l, float)
    ok = np.isfinite(h) & np.isfinite(l) & (h > 0) & (l > 0)
    h = np.where(ok, h, np.nan); l = np.where(ok, l, np.nan)
    hl2 = np.log(h / l) ** 2
    beta = hl2[:-1] + hl2[1:]
    gamma = np.log(np.fmax(h[:-1], h[1:]) / np.fmin(l[:-1], l[1:])) ** 2
    with np.errstate(invalid="ignore"):
        a = (np.sqrt(2 * beta) - np.sqrt(beta)) / SQ2 - np.sqrt(gamma / SQ2)
        S = 2 * (np.exp(a) - 1) / (1 + np.exp(a))
    S = S[np.isfinite(S)]
    if len(S) < 20:
        return np.nan, np.nan, len(S)
    return float(np.where(S < 0, 0, S).mean() * 1e4), float((S < 0).mean()), len(S)


def passport(coins=None, window_days=180, fee_rt_bps=15.0):
    """Паспорт ликвидности по монетам. fee_rt_bps — круговая биржевая комиссия (спот Gate VIP2 такер).

    Спред берём с 5m (bias-corrected excess CS), где книга не заморожена; иначе с 1d.
    rt_cost_bps = биржевая комиссия + оценка спреда (одно пересечение книги на круг).
    """
    coins = coins or list_universe("1d")
    maxts = max(int(load(c, "1d")["timestamp"][-1]) for c in coins)
    cut = maxts - (window_days - 1) * DAY_MS
    u5 = set(list_universe("5m"))
    out = {}
    for c in coins:
        d = load(c, "1d"); m = d["timestamp"] >= cut
        cl, h, l, v = d["close"][m], d["high"][m], d["low"][m], d["volume"][m]
        dv = cl * v
        ok = np.isfinite(dv) & np.isfinite(cl) & (cl > 0)
        r = {"coin": c, "n_days": int(ok.sum())}
        if ok.sum() < 30:
            r.update(enough=False, med_dv=None, rt_cost_bps=None)
            out[c] = r; continue
        dvv, clv = dv[ok], cl[ok]
        med_dv = float(np.median(dvv))
        ret = np.abs(np.diff(clv) / clv[:-1]); dvn = dvv[1:]
        g = np.isfinite(ret) & (dvn > 0)
        amihud = float(np.mean(ret[g] / dvn[g])) if g.sum() >= 20 else None
        cs1d, _, _ = _cs(h[ok], l[ok])
        ann_vol = float(np.std(np.diff(np.log(clv))) * math.sqrt(365) * 100)
        r.update(enough=bool(ok.sum() >= window_days * 0.83), med_dv=med_dv,
                 zero_frac=float((dvv <= 0).mean()),
                 low_frac=float((dvv < 0.10 * med_dv).mean()),
                 amihud=amihud, cs1d_bps=cs1d, ann_vol_pct=ann_vol)

        # 5m-блок: bias-corrected спред + непрерывность книги
        spread = cs1d
        if c in u5:
            d5 = load(c, "5m"); m5 = d5["timestamp"] >= cut
            cl5, h5, l5, v5 = d5["close"][m5], d5["high"][m5], d5["low"][m5], d5["volume"][m5]
            ok5 = np.isfinite(cl5) & (cl5 > 0) & np.isfinite(h5) & np.isfinite(l5)
            if ok5.sum() >= 5000:
                clv5, hv5, lv5, vv5 = cl5[ok5], h5[ok5], l5[ok5], v5[ok5]
                sig5 = float(np.std(np.diff(np.log(clv5))) * 1e4)
                obs5, _, _ = _cs(hv5, lv5)
                flat = float((hv5 == lv5).mean())
                excess = obs5 - NULL_K * sig5 if np.isfinite(obs5) else None
                r.update(flat_frac=flat, cs5_excess_bps=excess, sigma5_bps=sig5)
                if flat < FLAT_MAX and excess is not None and np.isfinite(excess):
                    spread = max(excess, 0.0)      # валидная 5m-оценка приоритетнее 1d
        r["spread_bps"] = None if spread is None or not np.isfinite(spread) else float(max(spread, 0.0))
        r["rt_cost_bps"] = None if r["spread_bps"] is None else float(fee_rt_bps + r["spread_bps"])
        out[c] = r
    return out


def terciles(pp, key="med_dv"):
    """Разбить монеты на терцили по ликвидности (по обороту). Возвращает (top, mid, bot) — списки монет."""
    valid = [r for r in pp.values() if r.get(key)]
    valid.sort(key=lambda r: -r[key])
    n = len(valid); t = n // 3
    return ([r["coin"] for r in valid[:t]],
            [r["coin"] for r in valid[t:2 * t]],
            [r["coin"] for r in valid[2 * t:]])


def cost_model(pp, floor_bps=15.0):
    """Пер-монетная круговая стоимость сделки (bps). Отсутствующие → floor (плоский спот-кост)."""
    return {c: (r.get("rt_cost_bps") or floor_bps) for c, r in pp.items()}
