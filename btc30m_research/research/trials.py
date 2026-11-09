# -*- coding: utf-8 -*-
"""trials.csv schema and helpers.  Every backtest (including failures) is one row."""
import csv
import datetime as dt
import json
import os

METRICS = ["n", "dropped", "n_clusters", "wins", "win_rate", "wilson_low", "wilson_high",
           "clusters_per_month", "min_month_clusters", "signals_per_month", "units_per_month",
           "max_losing_streak", "max_drawdown_units", "delay_n", "delay_win_rate",
           "delay_units_per_month", "payout080_units_per_month"]
DEV_YEARS = ["2020", "2021", "2022", "2023", "2024"]
COLUMNS = (["trial_id", "round", "category", "family", "params", "eval_window", "status", "error",
            "R", "E1"]
           + ["dev_" + m for m in METRICS] + ["dev_units_" + y for y in DEV_YEARS]
           + ["val_" + m for m in METRICS] + ["timestamp_utc"])

BREAKEVEN = 1.0 / 1.85


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def flat_metrics(prefix, r):
    out = {}
    for m in METRICS:
        if m.startswith("delay_"):
            v = r["delay"][m[len("delay_"):]]
        elif m == "payout080_units_per_month":
            v = r["payout_080"]["units_per_month"]
        else:
            v = r[m]
        out[prefix + m] = v
    return out


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v:
            return "nan"
        return repr(round(v, 6))
    return str(v)


def dev_score(r, years):
    """R score and E1 eligibility from a dev evaluation result."""
    R = min(r["units_per_month"], r["delay"]["units_per_month"])
    by = r["by_year"]
    years_ok = all(by.get(y, {"units": 0.0})["units"] >= 0 for y in years)
    e1 = (r["clusters_per_month"] >= 150 and r["win_rate"] > BREAKEVEN
          and r["delay"]["win_rate"] > BREAKEVEN and years_ok)
    return R, bool(e1)


class TrialLog:
    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            with open(path, "w", newline="") as f:
                csv.writer(f).writerow(COLUMNS)

    def rows(self):
        with open(self.path, newline="") as f:
            return list(csv.DictReader(f))

    def next_id(self):
        rows = self.rows()
        return 1 + max([int(r["trial_id"]) for r in rows], default=0)

    def append(self, row):
        row = dict(row)
        row.setdefault("timestamp_utc", now_utc())
        with open(self.path, "a", newline="") as f:
            csv.writer(f).writerow([fmt(row.get(c)) for c in COLUMNS])
            f.flush()
            os.fsync(f.fileno())

    def update_val(self, trial_id, val_result):
        rows = self.rows()
        flat = flat_metrics("val_", val_result)
        for r in rows:
            if int(r["trial_id"]) == int(trial_id):
                for k, v in flat.items():
                    r[k] = fmt(v)
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        os.replace(tmp, self.path)


def params_json(rule):
    return json.dumps(rule, sort_keys=True, separators=(",", ":"))
