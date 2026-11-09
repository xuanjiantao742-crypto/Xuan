# -*- coding: utf-8 -*-
"""Round 2 (PREREG section 4): local refinement around the top-10 dev seeds (by R, clusters/month >= 150,
C7 excluded).  One numeric parameter changed at a time: thresholds x{0.8,0.9,1.1,1.25}, windows
x{0.67,0.8,1.25,1.5} (rounded to whole minutes / days, de-duplicated)."""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import trials as TR  # noqa: E402

WINDOW = {"L", "D", "W", "M"}
THRESH = {"k", "q", "th", "m", "c"}
WMULT = [0.67, 0.8, 1.25, 1.5]
TMULT = [0.8, 0.9, 1.1, 1.25]

R = H.Research()
df = pd.read_csv(H.TRIALS)
df = df[(df.status == "ok") & (df.category != "C7") & (df.dev_clusters_per_month >= 150)]
seeds = df.sort_values(["R", "trial_id"], ascending=[False, True]).head(10)
print("seeds:", seeds.trial_id.tolist(), flush=True)
done = set(pd.read_csv(H.TRIALS).params.tolist())
planned = []
for _, s in seeds.iterrows():
    rule = json.loads(s.params)
    per_seed = 0
    for key in sorted(rule):
        if key in WINDOW:
            vals = sorted({max(1, int(round(rule[key] * m))) for m in WMULT} - {rule[key]})
        elif key in THRESH:
            vals = sorted({round(rule[key] * m, 10) for m in TMULT} - {rule[key]})
        else:
            continue
        for v in vals:
            nr = dict(rule)
            nr[key] = v
            if nr["family"] == "C5a" and key in ("q", "L"):
                nr["thr"] = R.dev_quantile("imb:%d" % nr["L"], nr["q"])
            p = TR.params_json(nr)
            if p in done or per_seed >= 30:
                continue
            done.add(p)
            planned.append((s.category, nr, int(s.trial_id)))
            per_seed += 1
print("round-2 trials planned:", len(planned), flush=True)
assert len(planned) <= 300
for cat, rule, seed in planned:
    R.run(rule, 2, cat, label="seed %d %s" % (seed, TR.params_json(rule)))
print("round 2 done", flush=True)
