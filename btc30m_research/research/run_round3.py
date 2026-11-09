# -*- coding: utf-8 -*-
"""Round 3 (PREREG section 4 + amendment 3): pairwise AND / OR combinations of the best trial of the
top-6 categories (rounds 1-2, clusters/month >= 150)."""
import itertools
import json
import os
import sys
import time
import traceback

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import trials as TR  # noqa: E402

R = H.Research()
df = pd.read_csv(H.TRIALS)
ok = df[(df.status == "ok") & (df.dev_clusters_per_month >= 150) & (df["round"] <= 2)]
best = ok.sort_values(["R", "trial_id"], ascending=[False, True]).groupby("category").head(1)
best = best.sort_values(["R", "trial_id"], ascending=[False, True]).head(6)
print("bases:", list(zip(best.category, best.trial_id)), flush=True)


def base_rule(row):
    p = json.loads(row.params)
    if p["family"] == "C7":
        model = json.load(open(os.path.join(H.ROOT, p["model_file"])))
        return {"family": "C7", "model": model}, p
    return p, p


bases = [(row.category, int(row.trial_id)) + base_rule(row) for row in best.itertuples()]
for (ca, ta, ra, pa), (cb, tb, rb, pb) in itertools.combinations(bases, 2):
    for op in ["AND", "OR"]:
        rule = {"family": "COMBO", "op": op, "a": ra, "b": rb}
        has_c7 = "C7" in (ra["family"], rb["family"])
        tid = R.log.next_id()
        row = {"trial_id": tid, "round": 3, "category": "COMBO", "family": "COMBO",
               "params": TR.params_json({"family": "COMBO", "op": op, "a": pa, "b": pb,
                                         "bases": [ta, tb]})}
        t0 = time.time()
        try:
            if has_c7:
                r = R.evaluate(rule, "dev", seg_range=H.C7_EVAL_INNER, seg_days=H.C7_EVAL_DAYS)
                years = ["2023", "2024"]
                row["eval_window"] = "2023-01-01..2024-12-31 (C7 part fit 2020-01-01..2022-12-31)"
            else:
                r = R.evaluate(rule, "dev")
                years = TR.DEV_YEARS
                row["eval_window"] = "2020-01-01..2024-12-31"
            Rs, e1 = TR.dev_score(r, years)
            row.update(TR.flat_metrics("dev_", r))
            for y in TR.DEV_YEARS:
                row["dev_units_" + y] = r["by_year"].get(y, {}).get("units")
            row.update({"status": "ok", "R": Rs, "E1": int(e1)})
            R.log.append(row)
            print("trial %4d COMBO %s #%d %s #%d n=%7d cl/m=%7.1f wr=%.4f dwr=%.4f u/m=%8.2f R=%8.2f E1=%d (%.1fs)" % (
                tid, op, ta, op, tb, r["n"], r["clusters_per_month"], r["win_rate"], r["delay"]["win_rate"],
                r["units_per_month"], Rs, e1, time.time() - t0), flush=True)
        except Exception as e:
            row.update({"status": "failed", "error": repr(e)[:300], "eval_window": ""})
            R.log.append(row)
            traceback.print_exc()
print("round 3 done", flush=True)
