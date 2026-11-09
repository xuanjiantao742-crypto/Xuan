#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_signals.py -- direction signals for the Binance BTCUSDT 30-minute event contract.

    python generate_signals.py --data-dir DIR --start 2025-11-01T00:00:00Z --end 2025-12-01T00:00:00Z --out signals.csv

* Reads only DIR (as written by fetch_data.py) and system.json next to this file.
  No network access, no random numbers; the output is fully deterministic.
* The signal at minute T only uses klines whose open time is <= T - 1 minute.  Every rolling
  quantity is an exact integer window sum or an exact window extreme over a fixed-length window
  that must lie completely inside the loaded data, and rows with open_time >= --end are ignored.
  Hence the signal at T is identical whether DIR stops right before T or continues long after,
  and identical for any --start (given the fixed warm-up that fetch_data.py downloads).
* Output: CSV with header `signal_time_utc,direction`, sorted by T, at most one row per minute,
  direction is Higher or Lower.  ALL signals are written (before the 5-open-orders cap).
  With no signals only the header is written; exit code 0.

(During research this file lives at research/siglib.py; it is copied unchanged to
frozen/generate_signals.py when the system is frozen.)
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

import numpy as np

MIN_MS = 60_000
DAY_MIN = 1440
WEEK_MIN = 10080
PRICE_SCALE = 10 ** 8      # index / futures / premium values -> int64 in units of 1e-8
VOL_SCALE = 10 ** 3        # futures volumes (3 decimals) -> int64
BASIS_SCALE = 10 ** 7      # basis b(t) rounded to 1e-7
I64_MIN = np.iinfo(np.int64).min
I64_MAX = np.iinfo(np.int64).max
MIN_FRAC = 0.8             # minimum fraction of valid values inside a window


# ============================================================================ time helpers
def parse_ts(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(round(t.timestamp() * 1000))


def ms_to_iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def floor_day(ms):
    return ms - ms % (DAY_MIN * MIN_MS)


def ceil_min(ms):
    return -(-ms // MIN_MS) * MIN_MS


# ============================================================================ data loading
SOURCE_FIELDS = {
    "index_1m": ["close"],
    "fut_1m": ["close", "volume", "taker_buy_volume", "count"],
    "prem_1m": ["close"],
}


class Grid:
    """Minute grid [g0, g1).  Index i <-> timestamp g0 + i minutes.  g0 is 00:00 UTC."""

    def __init__(self, g0_ms, g1_ms):
        assert g0_ms % (DAY_MIN * MIN_MS) == 0
        self.g0 = g0_ms
        self.n = (g1_ms - g0_ms) // MIN_MS
        self.g1 = g0_ms + self.n * MIN_MS

    def idx(self, ms):
        return (ms - self.g0) // MIN_MS

    def ts(self, i):
        return self.g0 + np.asarray(i, dtype=np.int64) * MIN_MS


def _read_month_csvs(data_dir, name, lo_ms, hi_ms):
    """Read DIR/name/YYYY-MM.csv files overlapping [lo, hi).  Returns (times int64, values float64 2D, header)."""
    files = sorted(glob.glob(os.path.join(data_dir, name, "????-??.csv")))
    lo_m = ms_to_iso(lo_ms)[:7]
    hi_m = ms_to_iso(hi_ms - 1)[:7]
    times, vals, header = [], [], None
    for f in files:
        m = os.path.basename(f)[:7]
        if m < lo_m or m > hi_m:
            continue
        with open(f) as fh:
            h = fh.readline().strip().split(",")
        if header is None:
            header = h
        elif h != header:
            raise ValueError("inconsistent header in %s" % f)
        arr = np.loadtxt(f, delimiter=",", skiprows=1, dtype=np.float64, ndmin=2)
        if arr.size == 0:
            continue
        t = arr[:, 0].astype(np.int64)
        keep = (t >= lo_ms) & (t < hi_ms)
        times.append(t[keep])
        vals.append(arr[keep, 1:])
    if not times:
        return np.zeros(0, np.int64), np.zeros((0, 0)), header
    return np.concatenate(times), np.concatenate(vals), header


class MarketData:
    """Integer arrays on the minute grid.  Missing minutes have valid=False."""

    def __init__(self, data_dir, g0_ms, g1_ms, sources, max_ms=None):
        self.grid = Grid(g0_ms, g1_ms)
        n = self.grid.n
        hi = g1_ms if max_ms is None else min(g1_ms, max_ms)
        self.sources = list(sources)
        for name in sources:
            t, v, header = _read_month_csvs(data_dir, name, g0_ms, hi)
            if t.size == 0:
                raise RuntimeError("no data for source %s in %s" % (name, data_dir))
            if np.any(t % MIN_MS):
                raise RuntimeError("non-minute timestamps in %s" % name)
            i = self.grid.idx(t)
            if len(np.unique(i)) != len(i):
                raise RuntimeError("duplicate timestamps in %s" % name)
            cols = header[1:]
            valid = np.zeros(n, bool)
            valid[i] = True
            setattr(self, name + "_valid", valid)
            for fld in SOURCE_FIELDS[name]:
                c = cols.index(fld)
                scale = VOL_SCALE if fld in ("volume", "taker_buy_volume") else (1 if fld == "count" else PRICE_SCALE)
                arr = np.zeros(n, np.int64)
                arr[i] = np.rint(v[:, c] * scale).astype(np.int64)
                setattr(self, name + "_" + fld, arr)


# ============================================================================ exact rolling helpers
def excl_cumsum(x):
    """C[0]=0, C[j]=x[0]+...+x[j-1]; int64 (wrap-around arithmetic keeps window differences exact)."""
    c = np.zeros(len(x) + 1, dtype=np.int64)
    np.cumsum(x.astype(np.int64), out=c[1:])
    return c


def window_sum(x, a, b):
    """Exact sum of int64 x over indices [i-a, i-b] (a >= b >= 0) for every i.
    Returns (sum, inside) where inside is False when the window starts before the grid."""
    n = len(x)
    c = excl_cumsum(x)
    i = np.arange(n, dtype=np.int64)
    lo = i - a
    hi = i - b + 1
    inside = lo >= 0
    s = c[np.clip(hi, 0, n)] - c[np.clip(lo, 0, n)]
    return np.where(inside, s, 0), inside


def rolling_extreme_end(x, w, kind):
    """Exact max/min of int64 x over [j-w+1, j] for every j (van Herk / Gil-Werman)."""
    n = len(x)
    fill = I64_MIN if kind == "max" else I64_MAX
    op = np.maximum if kind == "max" else np.minimum
    pad = (-n) % w
    xp = np.concatenate([x, np.full(pad, fill, dtype=np.int64)]).reshape(-1, w)
    pre = op.accumulate(xp, axis=1).ravel()
    suf = op.accumulate(xp[:, ::-1], axis=1)[:, ::-1].ravel()
    out = np.full(n, fill, dtype=np.int64)
    if n >= w:
        j = np.arange(w - 1, n)
        out[w - 1:] = op(suf[j - w + 1], pre[j])
    return out


def shift(x, k, fill=0):
    """y[i] = x[i-k] (k >= 0)."""
    y = np.full(len(x), fill, dtype=x.dtype)
    if k == 0:
        y[:] = x
    elif k < len(x):
        y[k:] = x[:-k]
    return y


def chain_sum(x, step, D):
    """out[i] = sum_{j=1..D} x[i - step*j] exactly (int64); inside[i] = (i - step*D - 1 >= 0)."""
    n = len(x)
    pad = (-n) % step
    xp = np.concatenate([x.astype(np.int64), np.zeros(pad, np.int64)]).reshape(-1, step)
    c = np.zeros((xp.shape[0] + 1, step), np.int64)
    np.cumsum(xp, axis=0, out=c[1:])
    i = np.arange(n, dtype=np.int64)
    r, col = i // step, i % step
    inside = (i - step * D - 1) >= 0
    out = c[r, col] - c[np.clip(r - D, 0, None), col]
    return np.where(inside, out, 0), inside


# ============================================================================ features
class Features:
    """Lazily computed features; value at grid index i is the feature for signal time T = g0 + i."""

    def __init__(self, md):
        self.md = md
        self.n = md.grid.n
        self.cache = {}

    def get(self, key):
        if key not in self.cache:
            name, _, arg = key.partition(":")
            fn = getattr(self, "_f_" + name)
            self.cache[key] = fn(*[int(a) if a.lstrip("-").isdigit() else a for a in arg.split(",")]) if arg else fn()
        return self.cache[key]

    # ---- index price basics
    def _P(self):
        return self.md.index_1m_close, self.md.index_1m_valid

    def _f_last(self):
        """P(T-1) as float (NaN if missing)."""
        P, v = self._P()
        p1, v1 = shift(P, 1), shift(v, 1, False)
        return np.where(v1, p1.astype(np.float64), np.nan)

    def _f_r(self, L):
        P, v = self._P()
        a, va = shift(P, 1), shift(v, 1, False)
        b, vb = shift(P, 1 + L), shift(v, 1 + L, False)
        ok = va & vb
        with np.errstate(divide="ignore", invalid="ignore"):
            r = (a - b).astype(np.float64) / b.astype(np.float64)
        return np.where(ok, r, np.nan)

    def _f_sigma(self, W):
        """mean |P(t)-P(t-1)| over t in [T-W, T-1], divided by P(T-1)."""
        P, v = self._P()
        dP = np.abs(P - shift(P, 1))
        dv = v & shift(v, 1, False)
        dv[0] = False
        dP = np.where(dv, dP, 0)
        s, inside = window_sum(dP, W, 1)
        cnt, _ = window_sum(dv.astype(np.int64), W, 1)
        inside &= (np.arange(self.n) - W - 1) >= 0
        last = self.get("last")
        ok = inside & (cnt >= MIN_FRAC * W) & np.isfinite(last)
        with np.errstate(divide="ignore", invalid="ignore"):
            sig = (s.astype(np.float64) / cnt.astype(np.float64)) / last
        return np.where(ok & (sig > 0), sig, np.nan)

    def _f_z(self, L):
        r = self.get("r:%d" % L)
        sig = self.get("sigma:1440")
        return r / (sig * np.sqrt(np.float64(L)))

    def _f_ma(self, L):
        P, v = self._P()
        s, inside = window_sum(np.where(v, P, 0), L, 1)
        cnt, _ = window_sum(v.astype(np.int64), L, 1)
        ok = inside & (cnt >= MIN_FRAC * L)
        with np.errstate(divide="ignore", invalid="ignore"):
            ma = s.astype(np.float64) / cnt.astype(np.float64)
        return np.where(ok, ma, np.nan)

    def _f_m(self, L):
        last = self.get("last")
        ma = self.get("ma:%d" % L)
        sig = self.get("sigma:1440")
        return (last / ma - 1.0) / (sig * np.sqrt(np.float64(L)))

    def _extreme(self, a, b, kind):
        """exact max/min of P over [i-a, i-b]; NaN if window not inside grid / too few valid."""
        P, v = self._P()
        w = a - b + 1
        fill = I64_MIN if kind == "max" else I64_MAX
        ext = rolling_extreme_end(np.where(v, P, fill), w, kind)
        ext = shift(ext, b, fill)
        cnt, inside = window_sum(v.astype(np.int64), a, b)
        ok = inside & (cnt >= MIN_FRAC * w)
        return np.where(ok, ext.astype(np.float64), np.nan)

    def _f_donhi(self, L):
        return self._extreme(L + 1, 2, "max")

    def _f_donlo(self, L):
        return self._extreme(L + 1, 2, "min")

    def _f_pos(self, L):
        mx = self._extreme(L, 1, "max")
        mn = self._extreme(L, 1, "min")
        last = self.get("last")
        rng = mx - mn
        with np.errstate(divide="ignore", invalid="ignore"):
            pos = (last - mn) / rng
        return np.where(rng > 0, pos, np.nan)

    def _f_vratio(self, W):
        return self.get("sigma:%d" % W) / self.get("sigma:1440")

    # ---- seasonality
    def _outcomes(self):
        if "_outc" not in self.cache:
            P, v = self._P()
            n = self.n
            o_open, vo = shift(P, 1), shift(v, 1, False)            # P(t-1)
            o_set = np.zeros(n, np.int64)
            vs = np.zeros(n, bool)
            o_set[:n - 29] = P[29:]
            vs[:n - 29] = v[29:]                                     # P(t+29)
            ok = vo & vs
            up = ok & (o_set > o_open)
            dn = ok & (o_set < o_open)
            self.cache["_outc"] = (up, dn, ok)
        return self.cache["_outc"]

    def _seasonal(self, step, D):
        up, dn, ok = self._outcomes()
        U, inside = chain_sum(up, step, D)
        Dn, _ = chain_sum(dn, step, D)
        C, _ = chain_sum(ok, step, D)
        tot = U + Dn
        good = inside & (C >= MIN_FRAC * D) & (tot > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            h = (U - Dn).astype(np.float64) / tot.astype(np.float64)
        return np.where(good, h, np.nan)

    def _f_hday(self, D):
        return self._seasonal(DAY_MIN, D)

    def _f_hweek(self, W):
        return self._seasonal(WEEK_MIN, W)

    # ---- basis / premium / funding proxy
    def _basis_int(self):
        if "_bi" not in self.cache:
            P, v = self._P()
            F, fv = self.md.fut_1m_close, self.md.fut_1m_valid
            ok = v & fv
            with np.errstate(divide="ignore", invalid="ignore"):
                b = (F.astype(np.float64) / P.astype(np.float64) - 1.0) * BASIS_SCALE
            bi = np.where(ok, np.rint(np.where(ok, b, 0.0)), 0).astype(np.int64)
            self.cache["_bi"] = (bi, ok)
        return self.cache["_bi"]

    def _dev_z(self, x, xv, L):
        """(x(T-1) - mean x[T-L,T-1]) / mean |dx| over [T-1440,T-1]."""
        n = self.n
        last = shift(x, 1)
        lv = shift(xv, 1, False)
        s, inside = window_sum(np.where(xv, x, 0), L, 1)
        cnt, _ = window_sum(xv.astype(np.int64), L, 1)
        dx = np.abs(x - shift(x, 1))
        dv = xv & shift(xv, 1, False)
        dv[0] = False
        sa, inside2 = window_sum(np.where(dv, dx, 0), DAY_MIN, 1)
        ca, _ = window_sum(dv.astype(np.int64), DAY_MIN, 1)
        inside2 &= (np.arange(n) - DAY_MIN - 1) >= 0
        ok = lv & inside & inside2 & (cnt >= MIN_FRAC * L) & (ca >= MIN_FRAC * DAY_MIN) & (sa > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            dev = last.astype(np.float64) - s.astype(np.float64) / cnt.astype(np.float64)
            scale = sa.astype(np.float64) / ca.astype(np.float64)
            z = dev / scale
        return np.where(ok, z, np.nan)

    def _f_zb(self, L):
        bi, ok = self._basis_int()
        return self._dev_z(bi, ok, L)

    def _f_zp(self, L):
        return self._dev_z(self.md.prem_1m_close, self.md.prem_1m_valid, L)

    def _f_fund(self):
        """Funding-rate proxy from the 480-minute mean premium index (Binance formula shape)."""
        pr, pv = self.md.prem_1m_close, self.md.prem_1m_valid
        s, inside = window_sum(np.where(pv, pr, 0), 480, 1)
        cnt, _ = window_sum(pv.astype(np.int64), 480, 1)
        ok = inside & (cnt >= MIN_FRAC * 480)
        with np.errstate(divide="ignore", invalid="ignore"):
            fp = (s.astype(np.float64) / cnt.astype(np.float64)) / PRICE_SCALE
        f = np.full(self.n, 0.0001)
        f = np.where(fp < -0.0004, fp + 0.0005, f)
        f = np.where(fp > 0.0006, fp - 0.0005, f)
        return np.where(ok, f, np.nan)

    def _f_mtf(self):
        """minutes until the next funding time (00/08/16 UTC); 0 exactly at a funding time."""
        mod = (np.arange(self.n, dtype=np.int64)) % DAY_MIN % 480
        return ((480 - mod) % 480).astype(np.float64)

    # ---- volume / taker flow
    def _vol_sums(self, L):
        fv = self.md.fut_1m_valid
        V = np.where(fv, self.md.fut_1m_volume, 0)
        TB = np.where(fv, self.md.fut_1m_taker_buy_volume, 0)
        sv, inside = window_sum(V, L, 1)
        stb, _ = window_sum(TB, L, 1)
        cnt, _ = window_sum(fv.astype(np.int64), L, 1)
        ok = inside & (cnt >= MIN_FRAC * L)
        return sv, stb, ok

    def _f_imb(self, L):
        sv, stb, ok = self._vol_sums(L)
        ok = ok & (sv > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            imb = (2 * stb - sv).astype(np.float64) / sv.astype(np.float64)
        return np.where(ok, imb, np.nan)

    def _f_vr(self, L):
        sv, _, ok = self._vol_sums(L)
        sd, _, okd = self._vol_sums(DAY_MIN)
        ok = ok & okd & (sd > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            vr = (sv * DAY_MIN).astype(np.float64) / (sd * L).astype(np.float64)
        return np.where(ok, vr, np.nan)


# ============================================================================ rules
def _sgn(x):
    return np.where(x > 0, 1, np.where(x < 0, -1, 0)).astype(np.int8)


def _fire(cond, direction):
    cond = np.asarray(cond, bool)
    return np.where(cond, direction, 0).astype(np.int8)


def rule_directions(F, rule):
    """Direction per grid index: +1 Higher, -1 Lower, 0 no signal.  NaN features -> no signal.
    A signal at T additionally requires that the index kline T-1 (the open-price kline) exists."""
    raw = _rule_raw(F, rule)
    return np.where(np.isfinite(F.get("last")), raw, 0).astype(np.int8)


def _rule_raw(F, rule):
    fam = rule["family"]
    d = int(rule.get("d", 1))
    with np.errstate(invalid="ignore"):
        if fam == "C1":  # |z_L| > k  -> d*sign(z)   (k == 0: sign of r_L, every minute)
            L, k = int(rule["L"]), float(rule["k"])
            if k == 0:
                r = F.get("r:%d" % L)
                return _fire(np.isfinite(r) & (r != 0), d * _sgn(r))
            z = F.get("z:%d" % L)
            return _fire(np.abs(z) > k, d * _sgn(z))
        if fam == "C2a":  # Donchian breakout
            L = int(rule["L"])
            last, hi, lo = F.get("last"), F.get("donhi:%d" % L), F.get("donlo:%d" % L)
            up = np.isfinite(hi) & (last > hi)
            dn = np.isfinite(lo) & (last < lo)
            return (_fire(up, d) + _fire(dn, -d)).astype(np.int8)
        if fam == "C2b":
            L, k = int(rule["L"]), float(rule["k"])
            m = F.get("m:%d" % L)
            return _fire(np.abs(m) > k, d * _sgn(m))
        if fam == "C2c":
            L, q = int(rule["L"]), float(rule["q"])
            pos = F.get("pos:%d" % L)
            return (_fire(pos >= 1 - q, d) + _fire(pos <= q, -d)).astype(np.int8)
        if fam == "C3a":
            h = F.get("hday:%d" % int(rule["D"]))
            return _fire(np.abs(h) >= float(rule["th"]), d * _sgn(h))
        if fam == "C3b":
            h = F.get("hweek:%d" % int(rule["W"]))
            return _fire(np.abs(h) >= float(rule["th"]), d * _sgn(h))
        if fam == "C4a":
            z = F.get("zb:%d" % int(rule["L"]))
            return _fire(np.abs(z) > float(rule["k"]), d * _sgn(z))
        if fam == "C4b":
            z = F.get("zp:%d" % int(rule["L"]))
            return _fire(np.abs(z) > float(rule["k"]), d * _sgn(z))
        if fam == "C4c":
            f, mtf = F.get("fund"), F.get("mtf")
            cond = (mtf > 0) & (mtf <= float(rule["M"])) & (np.abs(f) > float(rule["th"]))
            return _fire(cond, -d * _sgn(f))
        if fam == "C4d":
            f = F.get("fund")
            return _fire(np.abs(f) > float(rule["th"]), -d * _sgn(f))
        if fam == "C5a":
            imb = F.get("imb:%d" % int(rule["L"]))
            return _fire(np.abs(imb) >= float(rule["thr"]), d * _sgn(imb))
        if fam == "C5b":
            L = int(rule["L"])
            vr, r = F.get("vr:%d" % L), F.get("r:%d" % L)
            return _fire((vr >= float(rule["m"])) & np.isfinite(r) & (r != 0), d * _sgn(r))
        if fam == "C6a":
            L, k = int(rule["L"]), float(rule["k"])
            z, vr = F.get("z:%d" % L), F.get("vratio:60")
            reg = (vr >= 1.5) if rule["regime"] == "high" else (vr <= 0.7)
            return _fire((np.abs(z) > k) & reg, d * _sgn(z))
        if fam == "C6b":
            z, vr = F.get("z:15"), F.get("vratio:240")
            return _fire((vr <= float(rule["c"])) & (np.abs(z) > float(rule["k"])), d * _sgn(z))
        if fam == "C7":
            return _fire_logit(F, rule)
        if fam == "COMBO":
            a = _rule_raw(F, rule["a"])
            b = _rule_raw(F, rule["b"])
            if rule["op"] == "AND":
                return np.where((a != 0) & (a == b), a, 0).astype(np.int8)
            # OR without conflict
            out = np.where(a != 0, a, b)
            return np.where((a != 0) & (b != 0) & (a != b), 0, out).astype(np.int8)
    raise ValueError("unknown rule family %r" % fam)


def logit_matrix(F, feats):
    """Raw feature columns for the logistic model (list of feature keys, optional '-c' offsets)."""
    cols = []
    for key in feats:
        name, _, off = key.partition("|")
        x = F.get(name)
        if off:
            x = x - float(off)
        cols.append(x)
    return cols


def logit_score(F, m):
    """Linear score b + sum_k w_k * clip((x_k - mu_k)/sd_k, -5, 5), summed in a fixed order."""
    cols = logit_matrix(F, m["features"])
    s = np.full(F.n, float(m["b"]))
    ok = np.ones(F.n, bool)
    for x, mu, sd, w in zip(cols, m["mu"], m["sd"], m["w"]):
        ok &= np.isfinite(x)
        xs = np.clip((np.where(np.isfinite(x), x, mu) - mu) / sd, -5.0, 5.0)
        s = s + w * xs
    return s, ok


def _fire_logit(F, rule):
    m = rule["model"]
    s, ok = logit_score(F, m)
    up = ok & (s > float(m["thr_hi"]))
    dn = ok & (s < float(m["thr_lo"]))
    return (_fire(up, 1) + _fire(dn, -1)).astype(np.int8)


def rule_sources(rule):
    fam = rule["family"]
    if fam == "COMBO":
        return sorted(set(rule_sources(rule["a"])) | set(rule_sources(rule["b"])))
    if fam in ("C4a",):
        return ["index_1m", "fut_1m"]
    if fam in ("C4b", "C4c", "C4d"):
        return ["index_1m", "prem_1m"]
    if fam in ("C5a", "C5b"):
        return ["index_1m", "fut_1m"]
    if fam == "C7":
        need = {"index_1m"}
        for key in rule["model"]["features"]:
            k = key.split(":")[0].split("|")[0]
            if k in ("zb",):
                need.add("fut_1m")
            if k in ("zp", "fund"):
                need.add("prem_1m")
            if k in ("imb", "vr"):
                need.add("fut_1m")
        return sorted(need)
    return ["index_1m"]


# ============================================================================ CLI
def generate(data_dir, start_ms, end_ms, system):
    """Return list of (T_ms, direction) for T in [start, end)."""
    rule = system["rule"]
    warm_ms = int(system["warmup_days"]) * DAY_MIN * MIN_MS
    srcs = rule_sources(rule)
    # The grid starts warmup_days before --start, but never before the first full UTC day of data
    # present in DIR (windows reaching before the earliest data are treated as incomplete -> no
    # signal), so the result does not depend on how far before the data start --start lies.
    g0 = max(floor_day(start_ms) - warm_ms, earliest_full_day(data_dir, srcs))
    if g0 >= end_ms:
        return []
    # grid [g0, ceil_min(end)); only rows with open_time < end are loaded
    md = MarketData(data_dir, g0, ceil_min(end_ms), srcs, max_ms=end_ms)
    F = Features(md)
    dirs = rule_directions(F, rule)
    i0 = md.grid.idx(ceil_min(start_ms))
    i1 = md.grid.idx(ceil_min(end_ms))
    sel = np.nonzero(dirs[i0:i1])[0] + i0
    times = md.grid.ts(sel)
    return list(zip(times.tolist(), dirs[sel].tolist()))


def earliest_full_day(data_dir, sources):
    """First 00:00 UTC at or after the earliest row present in DIR (max over the sources)."""
    day = DAY_MIN * MIN_MS
    out = 0
    for name in sources:
        files = sorted(glob.glob(os.path.join(data_dir, name, "????-??.csv")))
        first = None
        for f in files:
            with open(f) as fh:
                fh.readline()
                line = fh.readline()
            if line.strip():
                first = int(float(line.split(",", 1)[0]))
                break
        if first is None:
            raise RuntimeError("no data for source %s in %s" % (name, data_dir))
        out = max(out, -(-first // day) * day)
    return out


def write_signals(path, sigs):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        f.write("signal_time_utc,direction\n")
        for t, d in sigs:
            f.write("%s,%s\n" % (ms_to_iso(t), "Higher" if d > 0 else "Lower"))
    os.replace(tmp, path)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Generate BTCUSDT 30m event-contract signals")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--system", default=os.path.join(here, "system.json"))
    args = ap.parse_args(argv)
    start_ms, end_ms = parse_ts(args.start), parse_ts(args.end)
    if end_ms <= start_ms:
        print("--end must be after --start", file=sys.stderr)
        return 1
    with open(args.system) as f:
        system = json.load(f)
    sigs = generate(args.data_dir, start_ms, end_ms, system)
    write_signals(args.out, sigs)
    print("wrote %d signals to %s" % (len(sigs), args.out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
