# -*- coding: utf-8 -*-
"""Score signal CSV files (frozen output) per segment and build results.json.

    python score_segments.py --conclusion "..." --candidates research/candidates.json \
        --checks research/out/checks.json [--holdout-json research/out/holdout_result.json] --out results.json
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import siglib as S  # noqa: E402
import evalib as E  # noqa: E402

SEG_KEYS = ["n", "n_clusters", "wins", "win_rate", "wilson_low", "wilson_high", "clusters_per_month",
            "min_month_clusters", "signals_per_month", "units_per_month", "max_losing_streak",
            "max_drawdown_units"]


def load_signals(path):
    """Read and validate a signals CSV.  Returns (times_ms int64, dirs int8)."""
    ts, ds = [], []
    with open(path) as f:
        header = f.readline().strip()
        if header != "signal_time_utc,direction":
            raise ValueError("bad header in %s: %r" % (path, header))
        for line in f:
            t, d = line.strip().split(",")
            if len(t) != 20 or not t.endswith(":00Z"):
                raise ValueError("bad time %r" % t)
            if d not in ("Higher", "Lower"):
                raise ValueError("bad direction %r" % d)
            ts.append(S.parse_ts(t))
            ds.append(1 if d == "Higher" else -1)
    ts = np.asarray(ts, np.int64)
    if len(ts) and (np.any(np.diff(ts) <= 0) or np.any(ts % S.MIN_MS)):
        raise ValueError("times not strictly increasing whole minutes in %s" % path)
    return ts, np.asarray(ds, np.int8)


def dirs_on_grid(grid, ts, ds):
    d = np.zeros(grid.n, np.int8)
    i = grid.idx(ts)
    keep = (i >= 0) & (i < grid.n)
    d[i[keep]] = ds[keep]
    return d


def score(sig_path, data_dir, seg, detail=False):
    s0, s1 = (S.parse_ts(x) for x in E.SEGMENTS[seg])
    g0 = S.floor_day(s0) - S.DAY_MIN * S.MIN_MS
    g1 = s1 + S.DAY_MIN * S.MIN_MS
    md = S.MarketData(data_dir, g0, g1, ["index_1m"])
    out = E.Outcomes(md)
    ts, ds = load_signals(sig_path)
    r = E.evaluate(dirs_on_grid(md.grid, ts, ds), out, md.grid, seg, detail=detail)
    return r, md, out


def seg_view(r):
    v = {k: r[k] for k in SEG_KEYS}
    v["delay"] = {"n": r["delay"]["n"], "win_rate": r["delay"]["win_rate"],
                  "units_per_month": r["delay"]["units_per_month"]}
    v["payout_080"] = {"units_per_month": r["payout_080"]["units_per_month"]}
    return v


def clean(x):
    if isinstance(x, float) and x != x:
        return None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conclusion", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--checks", required=True)
    ap.add_argument("--holdout-json", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "results.json"))
    args = ap.parse_args()

    with open(os.path.join(ROOT, "trials.csv"), newline="") as f:
        n_trials = sum(1 for _ in csv.DictReader(f))
    cands = json.load(open(args.candidates))
    checks = json.load(open(args.checks))
    research = os.path.join(ROOT, "data", "research")
    dev, _, _ = score(os.path.join(ROOT, "signals_dev.csv"), research, "dev")
    val, _, _ = score(os.path.join(ROOT, "signals_val.csv"), research, "val")
    hold = json.load(open(args.holdout_json)) if args.holdout_json else None

    by_year = {}
    for r in (dev, val) + ((hold["result"],) if hold else ()):
        for y, v in r["by_year"].items():
            by_year[y] = {"n": v["n"], "win_rate": v["win_rate"], "units": v["units"]}
    p = E.binom_sf_ge(val["wins"], val["n"], E.BREAKEVEN) if val["n"] else 1.0
    max_ts = max(int(x.split(",")[0]) for x in
                 open(sorted(__import__("glob").glob(os.path.join(research, "index_1m", "????-??.csv")))[-1])
                 .read().splitlines()[1:])
    res = {
        "conclusion": args.conclusion,
        "n_trials": n_trials,
        "n_candidates": len(cands["candidates"]),
        "research_data_max_ts": S.ms_to_iso(max_ts),
        "segments": {"dev": seg_view(dev), "val": seg_view(val), "holdout": seg_view(hold["result"]) if hold else None},
        "by_year": dict(sorted(by_year.items())),
        "val_p_bonferroni": min(1.0, p * n_trials),
        "truncation_ok": bool(checks["truncation_ok"]),
        "shuffle_win_rate": (checks["shuffle"]["val"] or {}).get("mean_win_rate"),
        "extra": {
            "frozen_trial_id": cands.get("selected_trial_id"),
            "val_p_raw": p,
            "dropped_signals": {"dev": dev["dropped"], "val": val["dropped"],
                                "holdout": hold["result"]["dropped"] if hold else None},
            "delay_dropped": {"dev": dev["delay"]["dropped"], "val": val["delay"]["dropped"],
                              "holdout": hold["result"]["delay"]["dropped"] if hold else None},
            "raw_signals_before_cap": {"dev": dev["n_raw_signals"], "val": val["n_raw_signals"],
                                       "holdout": hold["result"]["n_raw_signals"] if hold else None},
            "shuffle": checks["shuffle"],
            "start_invariance": checks["start_invariance"],
            "n_truncation_points": checks["n_truncation_points"],
            "shuffle_note": "shuffle_win_rate = mean over 200 shuffles in the validation segment; per-segment values in extra.shuffle",
        },
    }
    if hold and "shuffle" in hold:
        res["extra"]["shuffle_holdout"] = hold["shuffle"]
    with open(args.out, "w") as f:
        json.dump(clean(res), f, indent=1, ensure_ascii=False)
    print(json.dumps(clean(res["segments"]), indent=1)[:3000])


if __name__ == "__main__":
    main()
