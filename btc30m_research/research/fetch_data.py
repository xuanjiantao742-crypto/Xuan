#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_data.py -- download the public Binance data listed in data_manifest.json.

    python fetch_data.py --start 2025-11-01T00:00:00Z --end 2025-12-01T00:00:00Z --data-dir DIR

Behaviour
* Range fetched for every source: [floor_to_day(--start) - warmup_days, --end), clipped at the
  source's earliest available date. --end is exclusive.
* Per minute the layers are: monthly zip -> daily zip -> REST (GET with startTime/endTime,
  <= 1500 rows per request).  A monthly zip is only requested for a month that ends at or before
  --end, a daily zip only for a day that ends at or before --end; anything later can only come
  from REST with endTime = --end - 1 ms.  Rows with open_time >= --end are dropped in memory and
  never written to disk.
* Rows are aligned by open_time (never by line number).  Header lines are detected and skipped.
* Output: DIR/<source>/<YYYY-MM>.csv (header: open_time,<fields>), DIR/<source>/_gaps.json.
  Existing month files are merged (rows >= --end are not rewritten).
* A minute that is in none of the three layers is a gap.  A gap counts as confirmed if REST
  answered with no rows for it, or it is in the manifest's list of known gaps.
* Exit codes: 0 ok (confirmed gaps < 1 day are listed in _gaps.json and on stderr);
  2 a gap of >= 1 day (1440 minutes) could not be filled;
  3 unconfirmed gaps remain (REST unreachable) -- pass --allow-unconfirmed-gaps to accept them;
  1 any other error.
Only the Python standard library is used.
"""
import argparse
import calendar
import csv
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

MIN_MS = 60_000
DAY_MS = 86_400_000
USER_AGENT = "btc30m-research-fetch/1.0"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def parse_ts(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000)


def ms_to_iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_start(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
    return int(dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def next_month(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def ym(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m")


def ymd(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------- HTTP
class HttpResult:
    def __init__(self, status, body):
        self.status = status  # int HTTP status, or 0 for network failure
        self.body = body


def http_get(url, params=None, retries=4, timeout=60):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = HttpResult(0, b"")
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return HttpResult(r.status, r.read())
        except urllib.error.HTTPError as e:
            last = HttpResult(e.code, b"")
            if e.code in (400, 403, 404, 410, 451):
                return last  # definitive answers, no retry
        except Exception:  # network error, timeout, tunnel refused ...
            last = HttpResult(0, b"")
        time.sleep(2 ** attempt)
    return last


def download_zip_rows(url, verify_checksum=True):
    """Return (status, rows) where rows are lists of strings from the CSV inside the zip."""
    res = http_get(url)
    if res.status != 200:
        return res.status, None
    body = res.body
    if verify_checksum:
        ck = http_get(url + ".CHECKSUM", retries=2)
        if ck.status == 200 and ck.body:
            want = ck.body.decode("ascii", "ignore").split()[0].strip().lower()
            got = hashlib.sha256(body).hexdigest()
            if want and want != got:
                # retry the download once
                res = http_get(url)
                body = res.body if res.status == 200 else b""
                if hashlib.sha256(body).hexdigest() != want:
                    raise RuntimeError("checksum mismatch for %s" % url)
    rows = []
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for name in z.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = z.read(name).decode("utf-8", "replace")
            for rec in csv.reader(io.StringIO(text)):
                if not rec:
                    continue
                rows.append(rec)
    return 200, rows


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def norm_time(v):
    """Archive timestamps are ms; some newer archives use microseconds."""
    t = int(float(v))
    if t > 10 ** 14:
        t //= 1000
    return t


# ----------------------------------------------------------------------------- storage
def month_path(data_dir, src_name, month_ms):
    return os.path.join(data_dir, src_name, ym(month_ms) + ".csv")


def read_month_file(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        for rec in r:
            if rec:
                out[int(rec[0])] = rec[1:]
    return out


def write_month_file(path, fields, rows_by_time):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time"] + fields)
        for t in sorted(rows_by_time):
            w.writerow([t] + rows_by_time[t])
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- kline sources
def kline_rows_to_dict(rows, cols, lo, hi):
    """rows: list of string lists (archive or REST); cols: indices of wanted fields."""
    out = {}
    for rec in rows:
        if not rec or not is_number(rec[0]):
            continue  # header or junk
        t = norm_time(rec[0])
        if t < lo or t >= hi or t % MIN_MS != 0:
            continue
        out[t] = [str(rec[c]).strip() for c in cols]
    return out


def rest_klines(src, a, b, end_ms):
    """Fetch [a, b) from REST.  Returns (ok, dict).  ok=False if REST could not be reached."""
    out = {}
    cur = a
    hard_end = min(b, end_ms)
    while cur < hard_end:
        params = dict(src["rest_params"])
        params.update({"startTime": cur, "endTime": hard_end - 1, "limit": 1500})
        res = http_get(src["rest_url"], params)
        if res.status != 200:
            return False, out
        try:
            data = json.loads(res.body.decode())
        except Exception:
            return False, out
        if not data:
            break
        got = kline_rows_to_dict([[str(x) for x in rec] for rec in data], src["cols"], a, hard_end)
        out.update(got)
        last = max(norm_time(rec[0]) for rec in data)
        if last + MIN_MS <= cur:
            break
        cur = last + MIN_MS
        time.sleep(0.25)
    return True, out


def contiguous_ranges(sorted_minutes):
    """sorted list of ms -> list of [start, end_exclusive)."""
    out = []
    for t in sorted_minutes:
        if out and t == out[-1][1]:
            out[-1][1] = t + MIN_MS
        else:
            out.append([t, t + MIN_MS])
    return out


def fetch_kline_source(src, data_dir, lo, end_ms, workers):
    name, fields = src["name"], src["fields"]
    months = []
    m = month_start(lo)
    while m < end_ms:
        months.append(m)
        m = next_month(m)

    def do_month(mstart):
        mend = next_month(mstart)
        a, b = max(lo, mstart), min(end_ms, mend)
        got = {}
        layer_counts = {"monthly": 0, "daily": 0, "rest": 0}
        if mend <= end_ms:
            st, rows = download_zip_rows(src["monthly_url"].format(ym=ym(mstart)))
            if st == 200:
                got.update(kline_rows_to_dict(rows, src["cols"], a, b))
                layer_counts["monthly"] = len(got)
        expected = range(a, b, MIN_MS)
        missing = [t for t in expected if t not in got]
        if missing:
            days = sorted({t - t % DAY_MS for t in missing})
            for d in days:
                if d + DAY_MS > end_ms:
                    continue  # partial day: REST only
                st, rows = download_zip_rows(src["daily_url"].format(ymd=ymd(d)))
                if st == 200:
                    dd = kline_rows_to_dict(rows, src["cols"], max(a, d), min(b, d + DAY_MS))
                    n0 = len(got)
                    for t, v in dd.items():
                        got.setdefault(t, v)
                    layer_counts["daily"] += len(got) - n0
        return mstart, got, layer_counts

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for mstart, got, lc in ex.map(do_month, months):
            results[mstart] = (got, lc)
            log("  %s %s: monthly=%d daily=%d" % (name, ym(mstart), lc["monthly"], lc["daily"]))

    # REST layer for whatever is still missing
    rest_reachable = None
    confirmed, unconfirmed = [], []
    known = [(parse_ts(g[0]), parse_ts(g[1]) + MIN_MS) for g in src.get("known_gaps", [])]

    def in_known(t):
        return any(k0 <= t < k1 for k0, k1 in known)

    for mstart in months:
        got, lc = results[mstart]
        a, b = max(lo, mstart), min(end_ms, next_month(mstart))
        missing = [t for t in range(a, b, MIN_MS) if t not in got]
        for r0, r1 in contiguous_ranges(missing):
            ok = False
            if rest_reachable is not False:
                ok, dd = rest_klines(src, r0, r1, end_ms)
                if ok:
                    rest_reachable = True
                    n0 = len(got)
                    for t, v in dd.items():
                        got.setdefault(t, v)
                    lc["rest"] += len(got) - n0
                elif rest_reachable is None:
                    rest_reachable = False
                    log("  %s: REST unreachable (%s); REST layer skipped" % (name, src["rest_url"]))
            still = [t for t in range(r0, r1, MIN_MS) if t not in got]
            for g0, g1 in contiguous_ranges(still):
                rec = [ms_to_iso(g0), ms_to_iso(g1 - MIN_MS), (g1 - g0) // MIN_MS]
                if ok or all(in_known(t) for t in range(g0, g1, MIN_MS)):
                    confirmed.append(rec)
                else:
                    unconfirmed.append(rec)
        # write
        path = month_path(data_dir, name, mstart)
        existing = {t: v for t, v in read_month_file(path).items() if t < end_ms}
        existing.update(got)
        if existing:
            write_month_file(path, fields, existing)

    gaps = {"source": name, "range": [ms_to_iso(lo), ms_to_iso(end_ms)],
            "rest_reachable": rest_reachable, "confirmed_gaps": confirmed,
            "unconfirmed_gaps": unconfirmed}
    os.makedirs(os.path.join(data_dir, name), exist_ok=True)
    with open(os.path.join(data_dir, name, "_gaps.json"), "w") as f:
        json.dump(gaps, f, indent=1)
    return gaps


# ----------------------------------------------------------------------------- funding source
def fetch_funding_source(src, data_dir, lo, end_ms):
    name, fields = src["name"], src["fields"]
    m = month_start(lo)
    unconfirmed = []
    while m < end_ms:
        mend = next_month(m)
        a, b = max(lo, m), min(end_ms, mend)
        got = {}
        if mend <= end_ms:
            st, rows = download_zip_rows(src["monthly_url"].format(ym=ym(m)))
            if st == 200:
                for rec in rows:
                    if rec and is_number(rec[0]):
                        t = norm_time(rec[0])
                        if a <= t < b:
                            got[t] = [rec[1].strip(), rec[2].strip()]
        if not got:
            params = dict(src["rest_params"])
            params.update({"startTime": a, "endTime": b - 1, "limit": 1000})
            res = http_get(src["rest_url"], params)
            if res.status == 200:
                for rec in json.loads(res.body.decode()):
                    t = int(rec["fundingTime"])
                    if a <= t < b:
                        got[t] = [str(src.get("default_interval_hours", 8)), str(rec["fundingRate"])]
            else:
                unconfirmed.append([ms_to_iso(a), ms_to_iso(b)])
        log("  %s %s: %d records" % (name, ym(m), len(got)))
        if got:
            path = month_path(data_dir, name, m)
            existing = {t: v for t, v in read_month_file(path).items() if t < end_ms}
            existing.update(got)
            write_month_file(path, fields, existing)
        m = mend
    gaps = {"source": name, "range": [ms_to_iso(lo), ms_to_iso(end_ms)],
            "confirmed_gaps": [], "unconfirmed_gaps": unconfirmed}
    os.makedirs(os.path.join(data_dir, name), exist_ok=True)
    with open(os.path.join(data_dir, name, "_gaps.json"), "w") as f:
        json.dump(gaps, f, indent=1)
    return gaps


# ----------------------------------------------------------------------------- main
def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--manifest", default=os.path.join(here, "data_manifest.json"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--allow-unconfirmed-gaps", action="store_true",
                    help="accept gaps that could not be checked against REST (research use only)")
    args = ap.parse_args(argv)

    start_ms, end_ms = parse_ts(args.start), parse_ts(args.end)
    if end_ms <= start_ms:
        log("--end must be after --start")
        return 1
    now_ms = int(time.time() * 1000)
    with open(args.manifest) as f:
        manifest = json.load(f)
    warm_ms = int(manifest.get("warmup_days", 0)) * DAY_MS
    os.makedirs(args.data_dir, exist_ok=True)

    status = 0
    summary = []
    for src in manifest["sources"]:
        lo = max(start_ms - start_ms % DAY_MS - warm_ms, parse_ts(src["earliest"]))
        log("source %s: [%s, %s)" % (src["name"], ms_to_iso(lo), ms_to_iso(end_ms)))
        if src["kind"] == "kline":
            g = fetch_kline_source(src, args.data_dir, lo, end_ms, args.workers)
        elif src["kind"] == "funding":
            g = fetch_funding_source(src, args.data_dir, lo, end_ms)
        else:
            log("unknown source kind %s" % src["kind"])
            return 1
        # a gap that touches --end while --end is (almost) now is unpublished data, not a true gap
        if src["kind"] == "kline" and end_ms > now_ms - 10 * MIN_MS:
            keep = []
            for gp in g["confirmed_gaps"]:
                if parse_ts(gp[1]) + MIN_MS >= end_ms:
                    g["unconfirmed_gaps"].append(gp)
                else:
                    keep.append(gp)
            g["confirmed_gaps"] = keep
        summary.append(g)
        for gp in g["confirmed_gaps"]:
            log("  confirmed gap %s .. %s (%d min)" % tuple(gp))
        for gp in g["unconfirmed_gaps"]:
            log("  UNCONFIRMED gap %s" % (gp,))
        if src["kind"] == "funding":
            long_gap = list(g["unconfirmed_gaps"])  # a missing month of funding records
        else:
            long_gap = [gp for gp in g["confirmed_gaps"] + g["unconfirmed_gaps"] if gp[2] >= 1440]
        if long_gap:
            log("ERROR: %s has a gap of >= 1 day that could not be filled: %s" % (src["name"], long_gap[:3]))
            status = max(status, 2)
        elif g["unconfirmed_gaps"] and not args.allow_unconfirmed_gaps:
            log("ERROR: %s has gaps that could not be confirmed via REST" % src["name"])
            status = max(status, 3)
        if end_ms > now_ms:
            log("WARNING: --end is in the future; the most recent minutes cannot exist yet")
    with open(os.path.join(args.data_dir, "fetch_summary.json"), "w") as f:
        json.dump({"start": args.start, "end": args.end, "fetched_at_utc": ms_to_iso(now_ms),
                   "manifest": os.path.basename(args.manifest), "sources": summary}, f, indent=1)
    if status:
        log("fetch_data.py: FAILED with status %d" % status)
    else:
        log("fetch_data.py: OK")
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # pragma: no cover
        log("fetch_data.py: error: %r" % (e,))
        sys.exit(1)
