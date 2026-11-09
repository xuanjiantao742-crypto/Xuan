# -*- coding: utf-8 -*-
"""Check that a frozen signals CSV equals the research rule's signals, row by row."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H, siglib as S

def load_csv(path):
    ts, ds = [], []
    with open(path) as f:
        assert f.readline().strip() == "signal_time_utc,direction"
        for line in f:
            t, d = line.strip().split(",")
            ts.append(S.parse_ts(t)); ds.append(1 if d == "Higher" else -1)
    return np.array(ts, np.int64), np.array(ds, np.int8)

if __name__ == "__main__":
    system = json.load(open(sys.argv[1]))
    R = H.Research()
    d = R.dirs(system["rule"])
    for path, a, b in [(sys.argv[2], H.DEV0, H.DEV1), (sys.argv[3], H.VAL0, H.VAL1)]:
        ts, ds = load_csv(path)
        i0, i1 = R.grid.idx(a), R.grid.idx(b)
        sel = np.nonzero(d[i0:i1])[0] + i0
        rt, rd = R.grid.ts(sel), d[sel]
        same = len(ts) == len(rt) and np.array_equal(ts, rt) and np.array_equal(ds, rd)
        print(os.path.basename(path), "frozen rows", len(ts), "research rows", len(rt), "IDENTICAL" if same else "DIFFERENT")
