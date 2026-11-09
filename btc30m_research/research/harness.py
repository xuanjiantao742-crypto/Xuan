# -*- coding: utf-8 -*-
"""Research harness: loads the research data once, evaluates rules on the dev segment, logs trials."""
import json
import os
import sys
import time
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import siglib as S  # noqa: E402
import evalib as E  # noqa: E402
import trials as TR  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "research")
TRIALS = os.path.join(ROOT, "trials.csv")
MODELS = os.path.join(HERE, "models")

DEV0, DEV1 = S.parse_ts("2020-01-01T00:00:00Z"), S.parse_ts("2025-01-01T00:00:00Z")
VAL0, VAL1 = S.parse_ts("2025-01-01T00:00:00Z"), S.parse_ts("2026-01-01T00:00:00Z")
C7_FIT_INNER = (S.parse_ts("2020-01-01T00:00:00Z"), S.parse_ts("2023-01-01T00:00:00Z"))
C7_EVAL_INNER = (S.parse_ts("2023-01-01T00:00:00Z"), S.parse_ts("2025-01-01T00:00:00Z"))
C7_EVAL_DAYS = 731

FS_PRICE = ["z:1", "z:5", "z:15", "z:60", "z:240", "z:1440", "m:60", "m:1440", "pos:240|0.5", "vratio:60|1"]
FS_ALL = FS_PRICE + ["hday:60", "zb:15", "zp:240", "fund", "imb:5", "imb:30"]


class Research:
    def __init__(self, data_dir=DATA):
        t0 = time.time()
        g0, g1 = S.parse_ts("2020-01-01T00:00:00Z"), S.parse_ts("2026-01-01T00:00:00Z")
        self.md = S.MarketData(data_dir, g0, g1, ["index_1m", "fut_1m", "prem_1m"])
        self.grid = self.md.grid
        self.F = S.Features(self.md)
        self.out = E.Outcomes(self.md)
        self.log = TR.TrialLog(TRIALS)
        print("data loaded in %.1fs, grid n=%d" % (time.time() - t0, self.grid.n), flush=True)

    # ------------------------------------------------------------------ helpers
    def dirs(self, rule):
        return S.rule_directions(self.F, rule)

    def dev_quantile(self, key, q):
        x = self.F.get(key)
        i0, i1 = self.grid.idx(DEV0), self.grid.idx(DEV1)
        a = np.abs(x[i0:i1])
        a = a[np.isfinite(a)]
        return float(np.quantile(a, q))

    def evaluate(self, rule, seg="dev", seg_range=None, seg_days=None, detail=False):
        d = self.dirs(rule)
        return E.evaluate(d, self.out, self.grid, seg, seg_range=seg_range, seg_days=seg_days, detail=detail)

    # ------------------------------------------------------------------ C7 logistic model
    def fit_logit(self, feats, alpha, f, fit_range):
        cols = S.logit_matrix(self.F, feats)
        i0, i1 = self.grid.idx(fit_range[0]), self.grid.idx(fit_range[1])
        ok = np.ones(i1 - i0, bool)
        for x in cols:
            ok &= np.isfinite(x[i0:i1])
        ok &= np.isfinite(self.F.get("last")[i0:i1])
        y_ok = self.out.ok[i0:i1] & (self.out.winH[i0:i1] | self.out.winL[i0:i1])
        sel = ok & y_ok
        X = np.column_stack([x[i0:i1][sel] for x in cols])
        y = self.out.winH[i0:i1][sel].astype(np.float64)
        mu = X.mean(axis=0)
        sd = X.std(axis=0)
        sd[sd == 0] = 1.0
        Xs = np.clip((X - mu) / sd, -5.0, 5.0)
        n, k = Xs.shape
        A = np.column_stack([np.ones(n), Xs])
        w = np.zeros(k + 1)
        pen = np.full(k + 1, alpha)
        pen[0] = 0.0
        for it in range(50):
            z = A @ w
            p = 1.0 / (1.0 + np.exp(-z))
            g = A.T @ (p - y) / n + pen * w
            W = p * (1 - p)
            H = (A.T * W) @ A / n + np.diag(pen)
            step = np.linalg.solve(H, g)
            w = w - step
            if np.max(np.abs(step)) < 1e-10:
                break
        model = {"features": feats, "mu": [float(v) for v in mu], "sd": [float(v) for v in sd],
                 "w": [float(v) for v in w[1:]], "b": float(w[0]), "alpha": alpha, "f": f,
                 "fit_range": [S.ms_to_iso(fit_range[0]), S.ms_to_iso(fit_range[1])],
                 "n_fit": int(n), "iterations": it + 1}
        # thresholds from the deterministic score used at signal time
        s, okall = S.logit_score(self.F, model)
        ss = s[i0:i1][ok]
        model["thr_hi"] = float(np.quantile(ss, 1 - f))
        model["thr_lo"] = float(np.quantile(ss, f))
        return model

    # ------------------------------------------------------------------ trial runner
    def run(self, rule, round_, category, label=None):
        tid = self.log.next_id()
        row = {"trial_id": tid, "round": round_, "category": category, "family": rule["family"]}
        t0 = time.time()
        try:
            if rule["family"] == "C7":
                spec = rule
                model = self.fit_logit(spec["features"], spec["alpha"], spec["f"], C7_FIT_INNER)
                os.makedirs(MODELS, exist_ok=True)
                mpath = os.path.join(MODELS, "trial_%04d_inner.json" % tid)
                with open(mpath, "w") as fh:
                    json.dump(model, fh, indent=1)
                full_rule = {"family": "C7", "model": model}
                r = self.evaluate(full_rule, "dev", seg_range=C7_EVAL_INNER, seg_days=C7_EVAL_DAYS)
                years = ["2023", "2024"]
                row["eval_window"] = "2023-01-01..2024-12-31 (fit 2020-01-01..2022-12-31)"
                row["params"] = TR.params_json({"family": "C7", "features": spec["features"],
                                                "alpha": spec["alpha"], "f": spec["f"],
                                                "model_file": os.path.relpath(mpath, ROOT)})
            else:
                r = self.evaluate(rule, "dev")
                years = TR.DEV_YEARS
                row["eval_window"] = "2020-01-01..2024-12-31"
                row["params"] = TR.params_json(rule)
            R, e1 = TR.dev_score(r, years)
            row.update(TR.flat_metrics("dev_", r))
            for y in TR.DEV_YEARS:
                row["dev_units_" + y] = r["by_year"].get(y, {}).get("units")
            row.update({"status": "ok", "R": R, "E1": int(e1)})
            self.log.append(row)
            print("trial %4d %-5s %-60s n=%7d cl/m=%7.1f wr=%.4f dwr=%.4f u/m=%8.2f R=%8.2f E1=%d (%.1fs)" % (
                tid, rule["family"], (label or row["params"])[:60], r["n"], r["clusters_per_month"],
                r["win_rate"], r["delay"]["win_rate"], r["units_per_month"], R, e1, time.time() - t0), flush=True)
            return tid, r
        except Exception as e:
            row.update({"status": "failed", "error": repr(e)[:300], "params": TR.params_json(rule)
                        if rule.get("family") != "C7" else json.dumps({k: rule[k] for k in rule if k != "model"})})
            if "eval_window" not in row:
                row["eval_window"] = ""
            self.log.append(row)
            traceback.print_exc()
            print("trial %d FAILED: %r" % (tid, e), flush=True)
            return tid, None
