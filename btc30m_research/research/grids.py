# -*- coding: utf-8 -*-
"""Trial grids exactly as pre-registered in PREREG.md section 3."""

B0 = {"family": "C1", "L": 30, "k": 0.0, "d": 1}


def round1(R, FS_PRICE, FS_ALL):
    T = []
    D2 = [1, -1]
    for L in [1, 2, 3, 5, 10, 15, 30, 60, 120, 240, 480, 1440]:
        for k in [0.5, 1.0, 1.5, 2.0, 3.0]:
            for d in D2:
                T.append(("C1", {"family": "C1", "L": L, "k": k, "d": d}))
    for L in [15, 30, 60, 120, 240, 480, 1440]:
        for d in D2:
            T.append(("C2", {"family": "C2a", "L": L, "d": d}))
    for L in [30, 60, 120, 240, 480, 1440]:
        for k in [0.5, 1.0, 2.0]:
            for d in D2:
                T.append(("C2", {"family": "C2b", "L": L, "k": k, "d": d}))
    for L in [60, 240, 1440]:
        for q in [0.05, 0.10, 0.20]:
            for d in D2:
                T.append(("C2", {"family": "C2c", "L": L, "q": q, "d": d}))
    for D in [20, 60, 120, 250]:
        for th in [0.1, 0.2, 0.3]:
            for d in D2:
                T.append(("C3", {"family": "C3a", "D": D, "th": th, "d": d}))
    for W in [8, 26, 52]:
        for th in [0.25, 0.4]:
            for d in D2:
                T.append(("C3", {"family": "C3b", "W": W, "th": th, "d": d}))
    for L in [5, 15, 60, 240]:
        for k in [1.0, 2.0, 4.0]:
            for d in D2:
                T.append(("C4", {"family": "C4a", "L": L, "k": k, "d": d}))
    for L in [15, 240]:
        for k in [1.0, 2.0, 4.0]:
            for d in D2:
                T.append(("C4", {"family": "C4b", "L": L, "k": k, "d": d}))
    for M in [30, 60, 120]:
        for th in [0.0001, 0.0003]:
            for d in D2:
                T.append(("C4", {"family": "C4c", "M": M, "th": th, "d": d}))
    for th in [0.0001, 0.0002, 0.0005]:
        for d in D2:
            T.append(("C4", {"family": "C4d", "th": th, "d": d}))
    for L in [1, 5, 15, 30, 60]:
        for q in [0.80, 0.90, 0.95, 0.99]:
            thr = R.dev_quantile("imb:%d" % L, q)
            for d in D2:
                T.append(("C5", {"family": "C5a", "L": L, "q": q, "thr": thr, "d": d}))
    for L in [5, 15, 60]:
        for m in [2.0, 3.0, 5.0]:
            for d in D2:
                T.append(("C5", {"family": "C5b", "L": L, "m": m, "d": d}))
    for L in [5, 15, 60]:
        for k in [1.0, 2.0]:
            for regime in ["high", "low"]:
                for d in D2:
                    T.append(("C6", {"family": "C6a", "L": L, "k": k, "regime": regime, "d": d}))
    for c in [0.6, 0.8]:
        for k in [1.0, 2.0]:
            for d in D2:
                T.append(("C6", {"family": "C6b", "c": c, "k": k, "d": d}))
    for alpha in [1e-4, 1e-2]:
        for fs_name, fs in [("price", FS_PRICE), ("all", FS_ALL)]:
            for f in [0.025, 0.05, 0.10, 0.20]:
                T.append(("C7", {"family": "C7", "features": fs, "fs_name": fs_name, "alpha": alpha, "f": f}))
    return T
