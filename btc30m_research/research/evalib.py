# -*- coding: utf-8 -*-
"""Backtest / scoring engine (task section 2/3/6 rules).

All statistics are computed on ACCEPTED signals (5-open-orders cap applied first, per segment,
starting from 0 open orders).  Signals whose open or settlement kline does not exist are removed
from the statistics after the cap and counted in `dropped`.
"""
import bisect
import calendar
import datetime as dt
import math

import numpy as np

from siglib import MIN_MS, shift

PAYOUT = 0.85
BREAKEVEN = 1.0 / 1.85
Z95 = 1.959963984540054

SEGMENTS = {
    "dev": ("2020-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    "val": ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    "holdout": ("2026-01-01T00:00:00Z", "2026-08-26T00:00:00Z"),
}
SEG_DAYS = {"dev": 1827, "val": 365, "holdout": 237}


def iso_ms(s):
    from siglib import parse_ts
    return parse_ts(s)


class Outcomes:
    """Per grid index i (signal time T): normal and delayed outcomes."""

    def __init__(self, md):
        P, v = md.index_1m_close, md.index_1m_valid
        n = len(P)
        o, ov = shift(P, 1), shift(v, 1, False)                     # close of kline T-1
        s = np.zeros(n, np.int64); sv = np.zeros(n, bool)
        s[:n - 29], sv[:n - 29] = P[29:], v[29:]                    # close of kline T+29
        self.ok = ov & sv
        self.winH = self.ok & (s > o)
        self.winL = self.ok & (s < o)
        s2 = np.zeros(n, np.int64); sv2 = np.zeros(n, bool)
        s2[:n - 30], sv2[:n - 30] = P[30:], v[30:]                  # close of kline T+30
        self.ok_d = v & sv2                                         # open = close of kline T
        self.winH_d = self.ok_d & (s2 > P)
        self.winL_d = self.ok_d & (s2 < P)


def cap5(idx):
    """Greedy 5-open-orders cap.  idx: sorted minute indices.  Returns accepted indices."""
    t = idx.tolist()
    n = len(t)
    acc = []
    j = 0
    while j < n:
        x = t[j]
        if len(acc) >= 5 and acc[-5] > x - 30:
            j = bisect.bisect_left(t, acc[-5] + 30, j)
            continue
        acc.append(x)
        j += 1
    return np.asarray(acc, dtype=np.int64)


def cluster_starts(times, dirs):
    """Same-direction signals within 30 minutes of the cluster's first signal form one cluster."""
    last = {1: None, -1: None}
    starts = []
    for t, d in zip(times.tolist(), dirs.tolist()):
        s = last[d]
        if s is None or t - s >= 30:
            last[d] = t
            starts.append(t)
    return np.asarray(starts, dtype=np.int64)


def wilson(p, n, z=Z95):
    if n <= 0:
        return (float("nan"), float("nan"))
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / den, (c + h) / den)


def binom_sf_ge(k, n, p0):
    """P(X >= k), X ~ Bin(n, p0), computed in log space."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    lp, lq = math.log(p0), math.log1p(-p0)
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k, n + 1)]
    m = max(terms)
    return min(1.0, math.exp(m) * sum(math.exp(x - m) for x in terms))


def month_keys(ts_ms):
    d = ts_ms.astype("datetime64[ms]").astype("datetime64[M]")
    return d.astype(np.int64)  # months since 1970-01


def complete_months(seg_start_ms, seg_end_ms):
    """Month keys (months since 1970-01) fully inside [start, end)."""
    a = np.datetime64(int(seg_start_ms), "ms").astype("datetime64[M]")
    b = np.datetime64(int(seg_end_ms), "ms").astype("datetime64[M]")
    out = []
    m = a
    while m <= b:
        m0 = m.astype("datetime64[ms]").astype(np.int64)
        m1 = (m + 1).astype("datetime64[ms]").astype(np.int64)
        if m0 >= seg_start_ms and m1 <= seg_end_ms:
            out.append(int(m.astype(np.int64)))
        m = m + 1
    return out


def evaluate(dirs, out, grid, seg, seg_range=None, seg_days=None, detail=False):
    """Score a direction array (int8 per grid index) on one segment."""
    s0, s1 = seg_range if seg_range else (iso_ms(SEGMENTS[seg][0]), iso_ms(SEGMENTS[seg][1]))
    days = seg_days if seg_days else SEG_DAYS[seg]
    months = days / 30.4375
    i0, i1 = max(0, grid.idx(s0)), min(grid.n, grid.idx(s1))
    idx = np.nonzero(dirs[i0:i1])[0] + i0
    n_raw = len(idx)
    acc = cap5(idx)
    d_acc = dirs[acc].astype(np.int64)
    ok = out.ok[acc]
    dropped = int((~ok).sum())
    a = acc[ok]
    d = d_acc[ok]
    win = np.where(d > 0, out.winH[a], out.winL[a])
    n = len(a)
    wins = int(win.sum())
    wr = wins / n if n else float("nan")
    pnl = np.where(win, PAYOUT, -1.0)
    units = float(pnl.sum())
    # clusters
    cs = cluster_starts(a, d)
    ncl = len(cs)
    cs_ms = grid.ts(cs)
    mk = month_keys(cs_ms) if ncl else np.zeros(0, np.int64)
    cm = complete_months(s0, s1)
    per_month = {m: 0 for m in cm}
    for m in mk.tolist():
        if m in per_month:
            per_month[m] += 1
    min_month = min(per_month.values()) if per_month else None
    wl, wh = wilson(wr, ncl) if n else (float("nan"), float("nan"))
    # streak / drawdown in T order
    streak = best = 0
    for w in win.tolist():
        streak = 0 if w else streak + 1
        best = max(best, streak)
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    mdd = float(np.max(peak - cum)) if n else 0.0
    # delay test on the same accepted set
    okd = out.ok_d[acc]
    ad, dd_ = acc[okd], d_acc[okd]
    wind = np.where(dd_ > 0, out.winH_d[ad], out.winL_d[ad])
    nd = len(ad)
    winsd = int(wind.sum())
    unitsd = float(np.where(wind, PAYOUT, -1.0).sum())
    # by year
    yrs = grid.ts(a).astype("datetime64[ms]").astype("datetime64[Y]").astype(np.int64) + 1970
    by_year = {}
    for y in np.unique(yrs).tolist():
        m_ = yrs == y
        ny, wy = int(m_.sum()), int(win[m_].sum())
        by_year[str(y)] = {"n": ny, "win_rate": wy / ny if ny else None, "units": float(pnl[m_].sum())}
    res = {
        "n": n, "n_raw_signals": n_raw, "n_accepted": len(acc), "dropped": dropped,
        "n_clusters": ncl, "wins": wins, "win_rate": wr, "wilson_low": wl, "wilson_high": wh,
        "clusters_per_month": ncl / months, "min_month_clusters": min_month,
        "signals_per_month": n / months, "units_per_month": units / months, "units": units,
        "max_losing_streak": best, "max_drawdown_units": mdd,
        "delay": {"n": nd, "dropped": int((~okd).sum()), "win_rate": winsd / nd if nd else float("nan"),
                  "units_per_month": unitsd / months},
        "payout_080": {"units_per_month": float(np.where(win, 0.80, -1.0).sum()) / months},
        "by_year": by_year,
    }
    if detail:
        res["_acc"] = a
        res["_dir"] = d
        res["_win"] = win
    return res


def shuffle_control(res_detail, out, grid, seg, reps=200, seed=12345, seg_range=None):
    """Keep directions, move each accepted signal to a random other minute of the same segment."""
    s0, s1 = seg_range if seg_range else (iso_ms(SEGMENTS[seg][0]), iso_ms(SEGMENTS[seg][1]))
    i0, i1 = max(0, grid.idx(s0)), min(grid.n, grid.idx(s1))
    pool = np.arange(i0, i1)
    pool = pool[out.ok[pool]]
    d = res_detail["_dir"]
    rng = np.random.default_rng(seed)
    wrs = []
    for _ in range(reps):
        t = rng.choice(pool, size=len(d), replace=False)
        w = np.where(d > 0, out.winH[t], out.winL[t])
        wrs.append(w.mean())
    return float(np.mean(wrs)), float(np.std(wrs))
