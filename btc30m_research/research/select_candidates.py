# -*- coding: utf-8 -*-
"""PREREG section 5: choose the candidate list from dev results only, write research/candidates.json."""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import trials as TR  # noqa: E402

df = pd.read_csv(H.TRIALS)
df = df[df.status == "ok"].copy()
df = df.sort_values(["R", "trial_id"], ascending=[False, True])
e1 = df[df.E1 == 1]
picked, per_cat = [], {}
for row in e1.itertuples():
    if len(picked) >= 10:
        break
    if per_cat.get(row.category, 0) >= 3:
        continue
    picked.append(int(row.trial_id))
    per_cat[row.category] = per_cat.get(row.category, 0) + 1
source = {t: "E1" for t in picked}
if len(picked) < 5:
    e2 = df[(df.dev_clusters_per_month >= 150) & (~df.trial_id.isin(picked))]
    for row in e2.itertuples():
        if len(picked) >= 5:
            break
        if per_cat.get(row.category, 0) >= 3:
            continue
        picked.append(int(row.trial_id))
        per_cat[row.category] = per_cat.get(row.category, 0) + 1
        source[int(row.trial_id)] = "E2"
if 1 not in picked:
    picked.append(1)
    source[1] = "B0 (pre-registered)"
info = []
for t in picked:
    r = df[df.trial_id == t].iloc[0]
    info.append({"trial_id": t, "source": source[t], "category": r.category, "params": json.loads(r.params),
                 "dev_R": r.R, "dev_win_rate": r.dev_win_rate, "dev_delay_win_rate": r.dev_delay_win_rate,
                 "dev_clusters_per_month": r.dev_clusters_per_month, "dev_units_per_month": r.dev_units_per_month,
                 "eval_window": r.eval_window})
out = {"written_utc": TR.now_utc(), "n_trials_at_selection": int(len(pd.read_csv(H.TRIALS))),
       "n_E1": int(len(e1)), "rule": "PREREG section 5 (top-10 E1 by R, <=3 per category, COMBO own category; + B0)",
       "candidates": picked, "details": info}
path = os.path.join(H.HERE, "candidates.json")
if os.path.exists(path):
    sys.exit("candidates.json already exists -- refusing to overwrite")
with open(path, "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
for x in info:
    print(x["trial_id"], x["source"], x["category"], round(x["dev_R"], 2), round(x["dev_win_rate"], 4),
          round(x["dev_clusters_per_month"], 1), json.dumps(x["params"])[:110])
