# -*- coding: utf-8 -*-
"""Step 5e: score the holdout segment ONCE and append the result to FREEZE.txt.

Refuses to run if research/out/holdout_result.json already exists.
    python score_holdout.py --data-dir data/holdout
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import evalib as E  # noqa: E402
from score_segments import score, clean  # noqa: E402

OUT = os.path.join(HERE, "out", "holdout_result.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    if os.path.exists(OUT):
        sys.exit("holdout already scored once (%s exists) -- refusing to score again" % OUT)
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hold, md, out = score(os.path.join(ROOT, "signals_holdout.csv"), args.data_dir, "holdout", detail=True)
    shuf_m, shuf_s = E.shuffle_control(hold, out, md.grid, "holdout", reps=200, seed=20261109)
    research = os.path.join(ROOT, "data", "research")
    dev, _, _ = score(os.path.join(ROOT, "signals_dev.csv"), research, "dev")
    val, _, _ = score(os.path.join(ROOT, "signals_val.csv"), research, "val")
    for r in (hold,):
        for k in ("_acc", "_dir", "_win"):
            r.pop(k, None)
    years = {}
    for r in (dev, val):
        for y, v in r["by_year"].items():
            years[y] = v
    c1 = hold["win_rate"] >= 0.57 and hold["wilson_low"] > E.BREAKEVEN
    c2 = hold["clusters_per_month"] >= 150 and (hold["min_month_clusters"] is not None and hold["min_month_clusters"] >= 50)
    c3 = hold["units_per_month"] >= 12
    c4 = (dev["units"] > 0 and val["units"] > 0 and hold["units"] > 0
          and all(years[y]["units"] >= 0 for y in ["2020", "2021", "2022", "2023", "2024", "2025"]))
    c5 = hold["delay"]["win_rate"] > E.BREAKEVEN
    criteria = {"1_winrate_ge_57_and_wilson_low_gt_breakeven": bool(c1),
                "2_clusters_per_month_ge_150_and_min_full_month_ge_50": bool(c2),
                "3_units_per_month_ge_12": bool(c3),
                "4_dev_val_holdout_profitable_and_2020_2025_no_losing_year": bool(c4),
                "5_delay_winrate_gt_breakeven": bool(c5)}
    res = {"scored_at_utc": started, "result": hold,
           "shuffle": {"reps": 200, "mean_win_rate": shuf_m, "sd_win_rate": shuf_s},
           "criteria": criteria, "passed_all": bool(all(criteria.values())),
           "dev_units": dev["units"], "val_units": val["units"],
           "by_year_2020_2025_units": {y: years[y]["units"] for y in sorted(years)}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(clean(res), f, indent=1)
    h = hold
    lines = [
        "",
        "== 5e holdout scored ONCE at %s ==" % started,
        "holdout (T in [2026-01-01, 2026-08-25T23:30)): accepted+scored n=%d dropped=%d clusters=%d wins=%d" % (
            h["n"], h["dropped"], h["n_clusters"], h["wins"]),
        "win_rate=%.6f wilson95(n=clusters)=[%.6f, %.6f] clusters/month=%.2f min_full_month_clusters=%s" % (
            h["win_rate"], h["wilson_low"], h["wilson_high"], h["clusters_per_month"], h["min_month_clusters"]),
        "signals/month=%.2f units/month=%.4f units=%.2f max_losing_streak=%d max_drawdown_units=%.2f" % (
            h["signals_per_month"], h["units_per_month"], h["units"], h["max_losing_streak"], h["max_drawdown_units"]),
        "delay: n=%d win_rate=%.6f units/month=%.4f ; payout 0.80 units/month=%.4f ; shuffle mean win_rate=%.6f" % (
            h["delay"]["n"], h["delay"]["win_rate"], h["delay"]["units_per_month"], h["payout_080"]["units_per_month"],
            shuf_m),
        "criteria: " + json.dumps(criteria),
        "passed_all=%s" % all(criteria.values()),
    ]
    with open(os.path.join(ROOT, "FREEZE.txt"), "a") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
