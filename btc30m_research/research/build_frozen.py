# -*- coding: utf-8 -*-
"""Write frozen/ for one rule: generate_signals.py (= siglib.py, byte-identical), fetch_data.py,
system.json, data_manifest.json, requirements.txt.

    python build_frozen.py --system-json path/to/system.json
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import siglib as S  # noqa: E402

PY_VERSION = "3.13.18"
NUMPY_VERSION = "2.5.3"

KLINE_DOC = {
    "index_1m": {
        "description": "Binance USD-M BTCUSDT index price, 1-minute klines (indexPriceKlines).",
        "fields_used": {"open_time": "kline open time, ms since epoch (UTC)",
                        "close": "index price at the end of the minute (used: P(t))",
                        "open/high/low": "stored but unused"},
    },
    "fut_1m": {
        "description": "Binance USD-M BTCUSDT perpetual, 1-minute trade klines.",
        "fields_used": {"close": "last trade price", "volume": "base volume (BTC)",
                        "taker_buy_volume": "taker-buy base volume (BTC)", "count": "number of trades"},
    },
    "prem_1m": {
        "description": "Binance USD-M BTCUSDT premium index, 1-minute klines (premiumIndexKlines).",
        "fields_used": {"close": "premium index at the end of the minute"},
    },
}


def warmup_days(rule):
    fam = rule["family"]
    if fam == "COMBO":
        return max(warmup_days(rule["a"]), warmup_days(rule["b"]))
    if fam == "C3a":
        return int(rule["D"]) + 3
    if fam == "C3b":
        return 7 * int(rule["W"]) + 3
    if fam == "C7":
        days = 3
        for k in rule["model"]["features"]:
            if k.startswith("hday:"):
                days = max(days, int(k.split(":")[1].split("|")[0]) + 3)
            if k.startswith("hweek:"):
                days = max(days, 7 * int(k.split(":")[1].split("|")[0]) + 3)
        return days
    return 3  # every other feature looks back at most 1441 + 1440 minutes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system-json", required=True, help="file with {trial_id, description, rule}")
    ap.add_argument("--out", default=os.path.join(ROOT, "frozen"))
    args = ap.parse_args()
    with open(args.system_json) as f:
        spec = json.load(f)
    rule = spec["rule"]
    W = warmup_days(rule)
    out = args.out
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    shutil.copyfile(os.path.join(HERE, "siglib.py"), os.path.join(out, "generate_signals.py"))
    shutil.copyfile(os.path.join(HERE, "fetch_data.py"), os.path.join(out, "fetch_data.py"))
    system = {"trial_id": spec["trial_id"], "description": spec["description"],
              "warmup_days": W, "rule": rule}
    with open(os.path.join(out, "system.json"), "w") as f:
        json.dump(system, f, indent=1, sort_keys=True)
    with open(os.path.join(HERE, "data_manifest_research.json")) as f:
        rm = json.load(f)
    srcs = S.rule_sources(rule)
    sources = []
    for s in rm["sources"]:
        if s["name"] in srcs:
            s = dict(s)
            s.update(KLINE_DOC[s["name"]])
            s["frequency"] = "1m"
            s["earliest_available"] = s["earliest"]
            s["public_at"] = ("A kline with open time t is complete and public at t + 60 s. "
                              "generate_signals.py uses, for signal time T, only klines with open time <= T - 60 s.")
            if s["name"] == "index_1m":
                s["known_gaps"] = s["known_gaps"] + [["2024-08-12T10:02:00Z", "2024-08-12T10:03:00Z"]]
                s["known_gaps_note"] = ("The first three gaps are the ones listed in the task. 2024-08-12 10:02-10:03 "
                                        "was missing from both the monthly and the daily archive during research; "
                                        "REST (fapi.binance.com) answered HTTP 451 from the research machine, so it "
                                        "could not be confirmed there. With REST reachable the REST layer is tried first.")
            if s["name"] == "prem_1m":
                g = json.load(open(os.path.join(ROOT, "data", "research", "prem_1m", "_gaps.json")))
                s["known_gaps"] = [[a, b] for a, b, _ in g["unconfirmed_gaps"]]
                s["known_gaps_note"] = ("Minutes missing from both the monthly and the daily archive during research "
                                        "(2020-01..2025-12). REST answered HTTP 451 from the research machine, so they "
                                        "could not be confirmed there; with REST reachable the REST layer is tried first.")
            sources.append(s)
    manifest = {
        "description": "Public data needed by frozen/generate_signals.py. All URLs are public, free, need no key.",
        "warmup_days": W,
        "warmup_note": "fetch_data.py downloads [floor_to_day(--start) - warmup_days, --end); generate_signals.py "
                       "builds its minute grid from the same point, so every rolling window is complete.",
        "layers": "monthly zip -> daily zip -> REST with endTime (<=1500 rows/request); rows >= --end are never written",
        "sources": sources,
    }
    with open(os.path.join(out, "data_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    with open(os.path.join(out, "requirements.txt"), "w") as f:
        f.write("# Python %s\nnumpy==%s\n" % (PY_VERSION, NUMPY_VERSION))
    print("frozen/ written for trial %s (warmup %d days, sources %s)" % (spec["trial_id"], W, srcs))


if __name__ == "__main__":
    main()
