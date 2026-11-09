# -*- coding: utf-8 -*-
"""Independent re-implementation of the scoring rules (pandas + plain Python), used only to
cross-check evalib.py.  Reads a signals CSV and the raw index month files.

    python xcheck_scorer.py SIGNALS.csv DATA_DIR SEG_START SEG_END
"""
import glob
import os
import sys

import pandas as pd


def load_index(data_dir):
    fs = sorted(glob.glob(os.path.join(data_dir, "index_1m", "????-??.csv")))
    df = pd.concat([pd.read_csv(f, dtype={"close": str}) for f in fs])
    return dict(zip(df["open_time"].astype("int64"), df["close"].map(lambda s: round(float(s) * 1e8))))


def main(sig_path, data_dir, s0, s1):
    px = load_index(data_dir)
    sig = pd.read_csv(sig_path)
    import datetime as dt
    def to_ms(x):
        return int(dt.datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    allms = [to_ms(x) for x in sig["signal_time_utc"]]
    a, b = to_ms(s0), to_ms(s1)
    ms, dirs = [], []
    for m_, d_ in zip(allms, sig["direction"]):
        if a <= m_ < b:
            ms.append(m_)
            dirs.append(d_)
    accepted = []
    for T, d in zip(ms, dirs):
        open_cnt = sum(1 for (u, _) in accepted[-10:] if T - 30 * 60000 < u < T)
        if open_cnt < 5:
            accepted.append((T, d))
    n = wins = dropped = 0
    nd = winsd = 0
    stats = []
    for T, d in accepted:
        o, s = px.get(T - 60000), px.get(T + 29 * 60000)
        if o is None or s is None:
            dropped += 1
        else:
            w = (s > o) if d == "Higher" else (s < o)
            n += 1
            wins += int(w)
            stats.append((T, d))
        o2, s2 = px.get(T), px.get(T + 30 * 60000)
        if o2 is not None and s2 is not None:
            nd += 1
            winsd += int((s2 > o2) if d == "Higher" else (s2 < o2))
    # clusters on scored signals
    first = {}
    ncl = 0
    for T, d in stats:
        if d not in first or T - first[d] >= 30 * 60000:
            first[d] = T
            ncl += 1
    print({"accepted": len(accepted), "n": n, "wins": wins, "win_rate": wins / n if n else None,
           "dropped": dropped, "n_clusters": ncl, "delay_n": nd, "delay_wins": winsd})


if __name__ == "__main__":
    main(*sys.argv[1:5])
