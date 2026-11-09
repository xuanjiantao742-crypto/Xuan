# -*- coding: utf-8 -*-
"""Unit tests: exactness of rolling helpers and start/truncation invariance of features/rules."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siglib as S  # noqa: E402


def test_helpers():
    rng = np.random.default_rng(0)
    # values chosen so that every window sum fits in int64 but the running cumsum wraps around
    x = rng.integers(3 * 10 ** 14, 9 * 10 ** 14, size=20000, dtype=np.int64)
    assert int(x.astype(object).sum()) > 2 ** 63
    for a, b in [(1440, 1), (5, 1), (61, 2), (300, 7)]:
        s, inside = S.window_sum(x, a, b)
        for i in rng.integers(0, len(x), 300):
            if i - a >= 0:
                ref = sum(int(v) for v in x[i - a:i - b + 1])
                assert inside[i] and int(s[i]) == ref, (a, b, i)
            else:
                assert not inside[i]
    for w in [1, 2, 7, 60, 1441]:
        for kind, fn in [("max", np.max), ("min", np.min)]:
            e = S.rolling_extreme_end(x, w, kind)
            for j in rng.integers(w - 1, len(x), 300):
                assert e[j] == fn(x[j - w + 1:j + 1]), (w, kind, j)
    y = rng.integers(0, 2, size=50000).astype(np.int64)
    for step, D in [(1440, 20), (1440, 3), (100, 7)]:
        c, inside = S.chain_sum(y, step, D)
        for i in rng.integers(0, len(y), 300):
            if i - step * D - 1 >= 0:
                ref = sum(int(y[i - step * j]) for j in range(1, D + 1))
                assert inside[i] and int(c[i]) == ref
            else:
                assert not inside[i]
    print("helpers OK")


ALL_RULES = [
    {"family": "C1", "L": 30, "k": 0.0, "d": 1},
    {"family": "C1", "L": 15, "k": 1.0, "d": -1},
    {"family": "C2a", "L": 60, "d": 1},
    {"family": "C2b", "L": 240, "k": 1.0, "d": 1},
    {"family": "C2c", "L": 240, "q": 0.1, "d": -1},
    {"family": "C3a", "D": 60, "th": 0.2, "d": 1},
    {"family": "C3b", "W": 26, "th": 0.25, "d": 1},
    {"family": "C4a", "L": 15, "k": 2.0, "d": 1},
    {"family": "C4b", "L": 240, "k": 2.0, "d": 1},
    {"family": "C4c", "M": 60, "th": 0.0001, "d": 1},
    {"family": "C4d", "th": 0.0001, "d": 1},
    {"family": "C5a", "L": 5, "thr": 0.3, "d": 1},
    {"family": "C5b", "L": 15, "m": 2.0, "d": -1},
    {"family": "C6a", "L": 15, "k": 1.0, "regime": "high", "d": -1},
    {"family": "C6b", "c": 0.8, "k": 1.0, "d": 1},
]


def truncated_copy(data_dir, out_dir, cut_ms):
    """Copy of data_dir without any row whose open_time >= cut (earlier months symlinked)."""
    import glob
    cut_month = S.ms_to_iso(cut_ms)[:7]
    for src in ["index_1m", "fut_1m", "prem_1m"]:
        os.makedirs(os.path.join(out_dir, src), exist_ok=True)
        for f in sorted(glob.glob(os.path.join(data_dir, src, "????-??.csv"))):
            m = os.path.basename(f)[:7]
            dst = os.path.join(out_dir, src, os.path.basename(f))
            if m < cut_month:
                os.symlink(os.path.abspath(f), dst)
            elif m == cut_month:
                with open(f) as fi, open(dst, "w") as fo:
                    fo.write(fi.readline())
                    for line in fi:
                        if int(line.split(",", 1)[0]) < cut_ms:
                            fo.write(line)


def test_invariance(data_dir, tmp_dir):
    """Signals for T in [t0, t1) must not depend on --start (given warm-up) nor on data >= T."""
    import shutil
    t0 = S.parse_ts("2024-03-01T00:00:00Z")
    t1 = S.parse_ts("2024-03-08T00:00:00Z")
    cut = S.parse_ts("2024-03-05T13:37:00Z")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    truncated_copy(data_dir, tmp_dir, cut)
    for rule in ALL_RULES:
        warm = 370 if rule["family"] == "C3b" else 260
        sysA = {"rule": rule, "warmup_days": warm}
        a = S.generate(data_dir, t0, t1, sysA)                    # normal
        b = S.generate(data_dir, t0 - 9 * 86400000, t1, sysA)     # earlier start
        b = [x for x in b if x[0] >= t0]
        c = S.generate(tmp_dir, t0, t1, sysA)                      # only klines with open_time < cut exist
        assert a == b, ("start dependence", rule)
        a_cut = [x for x in a if x[0] <= cut]
        c_cut = [x for x in c if x[0] <= cut]
        assert a_cut == c_cut, ("truncation dependence", rule, len(a_cut), len(c_cut))
        assert all(x[0] <= cut for x in c), "signal after the data end"
        print("invariance OK", rule["family"], len(a), "signals in window;", len(c_cut), "<= cut")
    shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    test_helpers()
    if len(sys.argv) > 2:
        test_invariance(sys.argv[1], sys.argv[2])
