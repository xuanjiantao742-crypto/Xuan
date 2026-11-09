# -*- coding: utf-8 -*-
"""Validation-segment evaluation of the fixed candidate list + final selection (PREREG section 5).

C7 candidates are refit on the whole dev segment (2020-01-01..2024-12-31) with the same
hyper-parameters; that refit version is what gets evaluated on val and, if chosen, frozen."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import trials as TR  # noqa: E402
import evalib as E  # noqa: E402

OUT = os.path.join(H.HERE, "out")
cands = json.load(open(os.path.join(H.HERE, "candidates.json")))
R = H.Research()
results = []
for c in cands["details"]:
    tid, p = c["trial_id"], c["params"]
    if p["family"] == "C7":
        model = R.fit_logit(p["features"], p["alpha"], p["f"], (H.DEV0, H.DEV1))
        mpath = os.path.join(H.MODELS, "trial_%04d_full.json" % tid)
        with open(mpath, "w") as f:
            json.dump(model, f, indent=1)
        rule = {"family": "C7", "model": model}
    elif p["family"] == "COMBO":
        if "C7" in (p["a"]["family"], p["b"]["family"]):
            raise SystemExit("COMBO with C7 among candidates: needs refit (not expected here)")
        rule = {"family": "COMBO", "op": p["op"], "a": p["a"], "b": p["b"]}
    else:
        rule = p
    r = R.evaluate(rule, "val")
    R.log.update_val(tid, r)
    rr = {k: v for k, v in r.items()}
    results.append({"trial_id": tid, "category": c["category"], "rule": rule, "val": rr})
    print("cand %4d %-6s val n=%6d cl/m=%7.1f wr=%.4f dwr=%.4f u/m=%8.2f minM=%s | dev wr=%.4f u/m=%.2f" % (
        tid, c["category"], r["n"], r["clusters_per_month"], r["win_rate"], r["delay"]["win_rate"],
        r["units_per_month"], r["min_month_clusters"], c["dev_win_rate"], c["dev_units_per_month"]), flush=True)

qual = [x for x in results if x["val"]["win_rate"] > E.BREAKEVEN and x["val"]["clusters_per_month"] >= 150]
pool = qual if qual else results
best = sorted(pool, key=lambda x: (-x["val"]["units_per_month"], -x["val"]["win_rate"], x["trial_id"]))[0]
sel = {"written_utc": TR.now_utc(), "qualifying_trial_ids": [x["trial_id"] for x in qual],
       "selected_trial_id": best["trial_id"], "run_holdout": bool(qual),
       "selected_rule": best["rule"], "selected_val": best["val"]}
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "val_results.json"), "w") as f:
    json.dump(results, f, indent=1, default=float)
with open(os.path.join(OUT, "selection.json"), "w") as f:
    json.dump(sel, f, indent=1, default=float)
print("qualifying:", sel["qualifying_trial_ids"])
print("SELECTED:", best["trial_id"], "run_holdout =", sel["run_holdout"])
