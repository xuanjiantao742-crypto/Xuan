# -*- coding: utf-8 -*-
"""Diagnostic only (does not change frozen/): refit trial 375 without the 29 dev samples whose label
settles in 2025 (T >= 2024-12-31T23:31) and compare coefficients and the set of val signals.
No val outcomes are used."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H, siglib as S
R = H.Research()
sysj = json.load(open(os.path.join(H.ROOT, "frozen", "system.json")))
m0 = sysj["rule"]["model"]
m1 = R.fit_logit(m0["features"], m0["alpha"], m0["f"], (H.DEV0, S.parse_ts("2024-12-31T23:31:00Z")))
dw = max(abs(a - b) for a, b in zip(m0["w"] + [m0["b"], m0["thr_hi"], m0["thr_lo"]], m1["w"] + [m1["b"], m1["thr_hi"], m1["thr_lo"]]))
d0 = R.dirs({"family": "C7", "model": m0}); d1 = R.dirs({"family": "C7", "model": m1})
i0, i1 = R.grid.idx(H.VAL0), R.grid.idx(H.VAL1)
diff = int(np.sum(d0[i0:i1] != d1[i0:i1])); tot = int(np.sum(d0[i0:i1] != 0))
res = {"n_fit_frozen": m0["n_fit"], "n_fit_no_leak": m1["n_fit"], "max_abs_param_diff": dw,
       "val_minutes_with_different_signal": diff, "val_signals_frozen": tot}
print(res)
json.dump(res, open(os.path.join(H.HERE, "out", "diag_label_leak.json"), "w"), indent=1)
