"""Sanity checks on the downloaded research data (counts, monotonic times, funding interval)."""
import sys, os, glob, json
import numpy as np
d = sys.argv[1]
for name in ["index_1m", "fut_1m", "prem_1m"]:
    files = sorted(glob.glob(os.path.join(d, name, "????-??.csv")))
    tot = 0; bad = 0; tmin = None; tmax = None
    for f in files:
        a = np.loadtxt(f, delimiter=",", skiprows=1, ndmin=2)
        t = a[:, 0].astype(np.int64)
        if np.any(np.diff(t) <= 0): bad += 1
        tot += len(t); tmin = t[0] if tmin is None else tmin; tmax = t[-1]
        if name != "prem_1m" and np.any(a[:, 4] <= 0): print("nonpositive close", f)
    print(name, "files", len(files), "rows", tot, "nonmonotonic files", bad,
          "first", np.datetime64(int(tmin), "ms"), "last", np.datetime64(int(tmax), "ms"))
# funding intervals
files = sorted(glob.glob(os.path.join(d, "funding", "????-??.csv")))
rows = np.concatenate([np.loadtxt(f, delimiter=",", skiprows=1, ndmin=2) for f in files])
iv = np.unique(rows[:, 1]); dt_h = np.diff(rows[:, 0]) / 3.6e6
print("funding rows", len(rows), "interval_hours values", iv, "spacing hours min/max", dt_h.min().round(3), dt_h.max().round(3))
print("spacing != 8h count", int(np.sum(np.abs(dt_h - 8) > 0.01)))
