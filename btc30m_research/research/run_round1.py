# -*- coding: utf-8 -*-
"""Run B0 (trial 1) or the full pre-registered round-1 grid on the dev segment."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import grids  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--only-b0", action="store_true")
args = ap.parse_args()

R = H.Research()
done = {(r["params"]) for r in R.log.rows()}
if args.only_b0:
    if R.log.next_id() == 1:
        R.run(grids.B0, 0, "C1", label="B0 baseline sign(r_30)")
    sys.exit(0)

trials = grids.round1(R, H.FS_PRICE, H.FS_ALL)
print("round-1 trials:", len(trials), flush=True)
for cat, rule in trials:
    R.run(rule, 1, cat)
print("round 1 done", flush=True)
