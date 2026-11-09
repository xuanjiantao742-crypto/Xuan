# -*- coding: utf-8 -*-
"""Step 5d: check ONLY format, time range and count of signals_holdout.csv (no outcomes are looked at)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_segments import load_signals  # noqa: E402
import siglib as S  # noqa: E402

path = sys.argv[1]
ts, ds = load_signals(path)  # validates header, whole minutes, strictly increasing, Higher/Lower
lo, hi = S.parse_ts("2026-01-01T00:00:00Z"), S.parse_ts("2026-08-25T23:30:00Z")
assert len(ts) == 0 or (ts.min() >= lo and ts.max() < hi), "signal outside [2026-01-01, 2026-08-25T23:30)"
print("format OK; rows=%d; first=%s; last=%s; Higher=%d Lower=%d" % (
    len(ts), S.ms_to_iso(int(ts.min())) if len(ts) else "-", S.ms_to_iso(int(ts.max())) if len(ts) else "-",
    int((ds > 0).sum()), int((ds < 0).sum())))
