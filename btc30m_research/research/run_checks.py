# -*- coding: utf-8 -*-
"""Mandatory checks for the frozen system (task section 5.6 + 5.5b), using only data < 2026-01-01.

    python run_checks.py --out research/out/checks.json [--n-trunc 24]

1. truncation invariance: random signal times T (dev and val), delete every kline with open time >= T,
   rerun frozen/generate_signals.py, compare T and all earlier signals with signals_dev/val.csv.
2. shuffle control: keep directions, move T to random minutes of the same segment, 200 repetitions.
3. --start 2025-03-01 / --end 2025-07-01 in a brand-new directory (fetch + generate) must equal the
   matching rows of signals_val.csv.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import siglib as S  # noqa: E402
import evalib as E  # noqa: E402
from score_segments import load_signals, dirs_on_grid  # noqa: E402

FROZEN = os.path.join(ROOT, "frozen")
TMP = os.path.join(ROOT, "data", "tmp_checks")


def read_rows(path):
    with open(path) as f:
        return f.read().splitlines()


def truncated_copy(src_dir, dst_dir, cut_ms, sources):
    cut_month = S.ms_to_iso(cut_ms)[:7]
    for src in sources:
        os.makedirs(os.path.join(dst_dir, src), exist_ok=True)
        for f in sorted(glob.glob(os.path.join(src_dir, src, "????-??.csv"))):
            m = os.path.basename(f)[:7]
            dst = os.path.join(dst_dir, src, os.path.basename(f))
            if m < cut_month:
                os.symlink(os.path.abspath(f), dst)
            elif m == cut_month:
                with open(f) as fi, open(dst, "w") as fo:
                    fo.write(fi.readline())
                    for line in fi:
                        if int(line.split(",", 1)[0]) < cut_ms:
                            fo.write(line)


def run_frozen_generate(data_dir, start, end, out):
    cmd = [sys.executable, "generate_signals.py", "--data-dir", os.path.abspath(data_dir),
           "--start", start, "--end", end, "--out", os.path.abspath(out)]
    r = subprocess.run(cmd, cwd=FROZEN, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("generate failed: %s" % r.stderr[-2000:])


def truncation_test(n_per_seg, seed):
    system = json.load(open(os.path.join(FROZEN, "system.json")))
    sources = S.rule_sources(system["rule"])
    rng = np.random.default_rng(seed)
    results = []
    for seg, sig_file, data_dir, seg_start in [
            ("dev", "signals_dev.csv", "data/frozen_dev", "2020-01-01T00:00:00Z"),
            ("val", "signals_val.csv", "data/frozen_val", "2025-01-01T00:00:00Z")]:
        rows = read_rows(os.path.join(ROOT, sig_file))[1:]
        if not rows:
            continue
        picks = sorted(rng.choice(len(rows), size=min(n_per_seg, len(rows)), replace=False).tolist())
        for p in picks:
            T_iso = rows[p].split(",")[0]
            T = S.parse_ts(T_iso)
            # rows of the full file with time <= T (and >= seg_start)
            ref = [r for r in rows[:p + 1]]
            d = os.path.join(TMP, "trunc")
            if os.path.exists(d):
                shutil.rmtree(d)
            truncated_copy(os.path.join(ROOT, data_dir), d, T, sources)
            out = os.path.join(TMP, "trunc_out.csv")
            run_frozen_generate(d, seg_start, S.ms_to_iso(T + 60000), out)
            got = read_rows(out)[1:]
            ok = got == ref
            results.append({"segment": seg, "T": T_iso, "n_signals_compared": len(ref), "identical": ok})
            print("truncation", seg, T_iso, "compared", len(ref), "OK" if ok else "MISMATCH", flush=True)
    return results


def start_invariance_test():
    d = os.path.join(TMP, "mar_jul")
    if os.path.exists(d):
        shutil.rmtree(d)
    r = subprocess.run([sys.executable, "fetch_data.py", "--start", "2025-03-01T00:00:00Z",
                        "--end", "2025-07-01T00:00:00Z", "--data-dir", os.path.abspath(d)],
                       cwd=FROZEN, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("fetch failed: %s" % r.stderr[-2000:])
    out = os.path.join(TMP, "mar_jul.csv")
    run_frozen_generate(d, "2025-03-01T00:00:00Z", "2025-07-01T00:00:00Z", out)
    got = read_rows(out)[1:]
    lo, hi = "2025-03-01T00:00:00Z", "2025-07-01T00:00:00Z"
    ref = [x for x in read_rows(os.path.join(ROOT, "signals_val.csv"))[1:] if lo <= x.split(",")[0] < hi]
    ok = got == ref
    print("start-invariance 2025-03-01..2025-07-01:", len(got), "rows vs", len(ref), "OK" if ok else "MISMATCH")
    return {"rows_new_dir": len(got), "rows_signals_val": len(ref), "identical": ok}


def start_invariance_early():
    """Extra: --start 2020-02-15 on the dev data dir must reproduce signals_dev.csv rows from 2020-02-15."""
    out = os.path.join(TMP, "early.csv")
    run_frozen_generate(os.path.join(ROOT, "data", "frozen_dev"), "2020-02-15T00:00:00Z", "2020-06-01T00:00:00Z", out)
    got = read_rows(out)[1:]
    lo, hi = "2020-02-15T00:00:00Z", "2020-06-01T00:00:00Z"
    ref = [x for x in read_rows(os.path.join(ROOT, "signals_dev.csv"))[1:] if lo <= x.split(",")[0] < hi]
    ok = got == ref
    print("start-invariance 2020-02-15..2020-06-01:", len(got), "rows vs", len(ref), "OK" if ok else "MISMATCH")
    return {"rows_new_start": len(got), "rows_signals_dev": len(ref), "identical": ok}


def shuffle_test(reps, seed):
    g0, g1 = S.parse_ts("2020-01-01T00:00:00Z"), S.parse_ts("2026-01-01T00:00:00Z")
    md = S.MarketData(os.path.join(ROOT, "data", "research"), g0, g1, ["index_1m"])
    out = E.Outcomes(md)
    res = {}
    for seg, f in [("dev", "signals_dev.csv"), ("val", "signals_val.csv")]:
        ts, ds = load_signals(os.path.join(ROOT, f))
        dirs = dirs_on_grid(md.grid, ts, ds)
        r = E.evaluate(dirs, out, md.grid, seg, detail=True)
        if r["n"] == 0:
            res[seg] = None
            continue
        m, s = E.shuffle_control(r, out, md.grid, seg, reps=reps, seed=seed)
        res[seg] = {"reps": reps, "mean_win_rate": m, "sd_win_rate": s, "actual_win_rate": r["win_rate"],
                    "n": r["n"]}
        print("shuffle", seg, res[seg], flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-trunc", type=int, default=12, help="per segment (dev and val)")
    ap.add_argument("--seed", type=int, default=20261109)
    args = ap.parse_args()
    os.makedirs(TMP, exist_ok=True)
    trunc = truncation_test(args.n_trunc, args.seed)
    start = start_invariance_test()
    early = start_invariance_early()
    shuf = shuffle_test(200, args.seed)
    res = {"truncation": trunc, "truncation_ok": all(x["identical"] for x in trunc) and len(trunc) >= 20,
           "n_truncation_points": len(trunc), "start_invariance": start,
           "start_invariance_early_2020": early, "shuffle": shuf,
           "seed": args.seed}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(res, f, indent=1)
    shutil.rmtree(TMP, ignore_errors=True)
    print("checks written to", args.out, "truncation_ok =", res["truncation_ok"])


if __name__ == "__main__":
    main()
