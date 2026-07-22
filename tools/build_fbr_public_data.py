#!/usr/bin/env python3
"""Build a checksum-verified BTCUSDT USD-M public-data snapshot.

No API key, account access, or trading endpoint is used. Research data is
hard-capped at 2026-07-20 23:59:59.999 UTC; the workflow never requests later
rows. Binance Vision archive ZIPs are verified against adjacent .CHECKSUM
files. Funding and rare mark-price gap supplements use public market-data REST
endpoints only.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import pathlib
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, asdict
from typing import Iterable, Iterator

UTC = dt.timezone.utc
START = dt.datetime(2020, 1, 1, tzinfo=UTC)
CUTOFF = dt.datetime(2026, 7, 21, tzinfo=UTC)  # exclusive
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
ROOT = pathlib.Path(os.environ.get("FBR_OUTPUT_DIR", "fbr_public_data_output"))
CACHE = ROOT / "raw_cache"
OUT = ROOT / "normalized"
AUDIT = ROOT / "audit"
BASE = "https://data.binance.vision/data/futures/um"
FAPI = "https://fapi.binance.com"
UA = "FBR-public-research/1.0 (+checksum-verified; no-account; no-keys)"


def sha256_file(path: pathlib.Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def request_bytes(url: str, *, attempts: int = 8, timeout: int = 90) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt + 1 == attempts:
                break
            time.sleep(min(30.0, 1.0 * (2 ** attempt)) + random.random())
    raise RuntimeError(f"download failed after {attempts} attempts: {url}: {last}")


def download_verified(url: str, dst: pathlib.Path) -> tuple[str, str, int]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    checksum_url = url + ".CHECKSUM"
    checksum_text = request_bytes(checksum_url).decode("utf-8", "replace").strip()
    expected = checksum_text.split()[0].lower()
    if len(expected) != 64:
        raise ValueError(f"invalid checksum response for {url}: {checksum_text[:200]!r}")
    if dst.exists() and sha256_file(dst) == expected:
        return expected, expected, dst.stat().st_size
    data = request_bytes(url)
    tmp = dst.with_suffix(dst.suffix + ".part")
    tmp.write_bytes(data)
    actual = sha256_file(tmp)
    if actual != expected:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"SHA256 mismatch for {url}: expected {expected}, got {actual}")
    tmp.replace(dst)
    return expected, actual, dst.stat().st_size


def month_starts(start: dt.datetime, end_exclusive: dt.datetime) -> Iterator[dt.datetime]:
    cur = dt.datetime(start.year, start.month, 1, tzinfo=UTC)
    last_full_month_start = dt.datetime(end_exclusive.year, end_exclusive.month, 1, tzinfo=UTC)
    while cur < last_full_month_start:
        yield cur
        if cur.month == 12:
            cur = dt.datetime(cur.year + 1, 1, 1, tzinfo=UTC)
        else:
            cur = dt.datetime(cur.year, cur.month + 1, 1, tzinfo=UTC)


def days_in_partial_month(end_exclusive: dt.datetime) -> Iterator[dt.datetime]:
    cur = dt.datetime(end_exclusive.year, end_exclusive.month, 1, tzinfo=UTC)
    while cur < end_exclusive:
        yield cur
        cur += dt.timedelta(days=1)


def normalize_ts(raw: str) -> int:
    v = int(raw)
    if v > 10**14:
        v //= 1000
    return v


@dataclass
class ArchiveReceipt:
    dataset: str
    cadence: str
    period: str
    url: str
    local_name: str
    checksum_sha256: str
    actual_sha256: str
    bytes: int
    rows: int = 0
    first_ts_ms: int | None = None
    last_ts_ms: int | None = None


def archive_url(dataset: str, cadence: str, when: dt.datetime) -> tuple[str, str]:
    period = when.strftime("%Y-%m" if cadence == "monthly" else "%Y-%m-%d")
    name = f"{SYMBOL}-{INTERVAL}-{period}.zip"
    return f"{BASE}/{cadence}/{dataset}/{SYMBOL}/{INTERVAL}/{name}", name


def iter_zip_rows(path: pathlib.Path) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV member in {path}, got {names}")
        with zf.open(names[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as txt:
            reader = csv.reader(txt)
            for row in reader:
                if not row:
                    continue
                first = row[0].strip()
                if not first or not first.lstrip("-").isdigit():
                    continue
                yield row


def build_series(dataset: str, output_name: str) -> tuple[list[ArchiveReceipt], dict]:
    receipts: list[ArchiveReceipt] = []
    output_path = OUT / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expected_cols = 12
    header = [
        "open_time_ms", "open", "high", "low", "close", "volume",
        "close_time_ms", "quote_volume", "trade_count",
        "taker_buy_volume", "taker_buy_quote_volume", "ignore",
    ]
    total = 0
    duplicate_count = 0
    out_of_order_count = 0
    missing_minutes: list[int] = []
    first_ts: int | None = None
    last_ts: int | None = None
    prev_ts: int | None = None
    source_row_hash = hashlib.sha256()

    with gzip.open(output_path, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        writer = csv.writer(gz, lineterminator="\n")
        periods = [("monthly", x) for x in month_starts(START, CUTOFF)]
        periods += [("daily", x) for x in days_in_partial_month(CUTOFF)]
        for cadence, when in periods:
            url, name = archive_url(dataset, cadence, when)
            local = CACHE / dataset / cadence / name
            expected, actual, size = download_verified(url, local)
            receipt = ArchiveReceipt(
                dataset=dataset,
                cadence=cadence,
                period=when.strftime("%Y-%m" if cadence == "monthly" else "%Y-%m-%d"),
                url=url,
                local_name=str(local.relative_to(ROOT)),
                checksum_sha256=expected,
                actual_sha256=actual,
                bytes=size,
            )
            for row in iter_zip_rows(local):
                if len(row) < expected_cols:
                    raise ValueError(f"short row in {local}: {row}")
                ts = normalize_ts(row[0])
                if not (int(START.timestamp() * 1000) <= ts < int(CUTOFF.timestamp() * 1000)):
                    continue
                row = row[:expected_cols]
                row[0] = str(ts)
                row[6] = str(normalize_ts(row[6]))
                if receipt.first_ts_ms is None:
                    receipt.first_ts_ms = ts
                receipt.last_ts_ms = ts
                receipt.rows += 1
                if first_ts is None:
                    first_ts = ts
                if prev_ts is not None:
                    if ts == prev_ts:
                        duplicate_count += 1
                        raise ValueError(f"duplicate timestamp {ts} in {dataset}")
                    if ts < prev_ts:
                        out_of_order_count += 1
                        raise ValueError(f"out-of-order timestamp {ts} after {prev_ts} in {dataset}")
                    if ts > prev_ts + 60_000:
                        missing_minutes.extend(range(prev_ts + 60_000, ts, 60_000))
                writer.writerow(row)
                source_row_hash.update((",".join(row) + "\n").encode())
                prev_ts = ts
                last_ts = ts
                total += 1
            receipts.append(receipt)
            print(f"{dataset} {receipt.period}: {receipt.rows:,} rows", flush=True)

    audit = {
        "dataset": dataset,
        "normalized_path": str(output_path.relative_to(ROOT)),
        "normalized_sha256": sha256_file(output_path),
        "normalized_bytes": output_path.stat().st_size,
        "canonical_row_stream_sha256": source_row_hash.hexdigest(),
        "rows": total,
        "first_ts_ms": first_ts,
        "last_ts_ms": last_ts,
        "duplicate_count": duplicate_count,
        "out_of_order_count": out_of_order_count,
        "missing_minute_count": len(missing_minutes),
        "missing_minutes_ms": missing_minutes,
    }
    return receipts, audit


def public_json(path: str, params: dict[str, str | int]) -> tuple[object, dict]:
    query = urllib.parse.urlencode(params)
    url = f"{FAPI}{path}?{query}"
    raw = request_bytes(url)
    receipt = {
        "url": url,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_bytes": len(raw),
    }
    return json.loads(raw), receipt


def build_funding() -> dict:
    out = OUT / "btcusdt_funding_research.csv.gz"
    pages: list[dict] = []
    rows: list[dict] = []
    cur = int(START.timestamp() * 1000)
    end = int(CUTOFF.timestamp() * 1000) - 1
    while cur <= end:
        payload, receipt = public_json(
            "/fapi/v1/fundingRate",
            {"symbol": SYMBOL, "startTime": cur, "endTime": end, "limit": 1000},
        )
        if not isinstance(payload, list):
            raise ValueError(f"unexpected funding payload: {payload!r}")
        pages.append(receipt)
        if not payload:
            break
        for item in payload:
            ts = int(item["fundingTime"])
            if ts >= int(CUTOFF.timestamp() * 1000):
                continue
            rows.append({
                "funding_time_ms": ts,
                "funding_rate": item["fundingRate"],
                "mark_price": item.get("markPrice", ""),
            })
        nxt = int(payload[-1]["fundingTime"]) + 1
        if nxt <= cur:
            raise RuntimeError("funding pagination did not advance")
        cur = nxt
        if len(payload) < 1000:
            break
        time.sleep(0.05)
    rows.sort(key=lambda x: x["funding_time_ms"])
    dedup: dict[int, dict] = {}
    for r in rows:
        ts = int(r["funding_time_ms"])
        if ts in dedup and dedup[ts] != r:
            raise ValueError(f"conflicting funding duplicate at {ts}")
        dedup[ts] = r
    rows = [dedup[k] for k in sorted(dedup)]
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        w = csv.DictWriter(gz, fieldnames=["funding_time_ms", "funding_rate", "mark_price"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return {
        "dataset": "fundingRate REST",
        "normalized_path": str(out.relative_to(ROOT)),
        "normalized_sha256": sha256_file(out),
        "normalized_bytes": out.stat().st_size,
        "rows": len(rows),
        "first_ts_ms": rows[0]["funding_time_ms"] if rows else None,
        "last_ts_ms": rows[-1]["funding_time_ms"] if rows else None,
        "pages": pages,
    }


def build_mark_supplements(missing: Iterable[int]) -> dict:
    missing = list(missing)
    out = OUT / "btcusdt_mark_supplements_research.csv.gz"
    rows: list[list[str]] = []
    pages: list[dict] = []
    unresolved: list[int] = []
    for ts in missing:
        payload, receipt = public_json(
            "/fapi/v1/markPriceKlines",
            {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "startTime": ts,
                "endTime": ts + 59_999,
                "limit": 2,
            },
        )
        pages.append(receipt)
        found = None
        if isinstance(payload, list):
            for row in payload:
                if normalize_ts(str(row[0])) == ts:
                    found = row
                    break
        if found is None:
            unresolved.append(ts)
        else:
            rows.append([str(normalize_ts(str(found[0])))] + [str(x) for x in found[1:12]])
        time.sleep(0.03)
    header = [
        "open_time_ms", "open", "high", "low", "close", "volume",
        "close_time_ms", "quote_volume", "trade_count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore",
    ]
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        w = csv.writer(gz, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return {
        "normalized_path": str(out.relative_to(ROOT)),
        "normalized_sha256": sha256_file(out),
        "normalized_bytes": out.stat().st_size,
        "rows": len(rows),
        "requested_missing_minutes": len(missing),
        "unresolved_count": len(unresolved),
        "unresolved_minutes_ms": unresolved,
        "pages": pages,
    }


def main() -> int:
    for p in (CACHE, OUT, AUDIT):
        p.mkdir(parents=True, exist_ok=True)
    trade_receipts, trade_audit = build_series("klines", "btcusdt_trade_1m_research.csv.gz")
    mark_receipts, mark_audit = build_series("markPriceKlines", "btcusdt_mark_1m_research.csv.gz")
    mark_supp = build_mark_supplements(mark_audit["missing_minutes_ms"])
    funding = build_funding()
    manifest = {
        "schema": "FBR public data snapshot v1",
        "created_at_utc": dt.datetime.now(tz=UTC).isoformat(),
        "market": "Binance USD-M BTCUSDT perpetual",
        "account_access": False,
        "api_keys": False,
        "trading_endpoints": False,
        "research_start_utc": START.isoformat(),
        "research_cutoff_exclusive_utc": CUTOFF.isoformat(),
        "forward_data_requested": False,
        "archive_receipts": [asdict(x) for x in trade_receipts + mark_receipts],
        "trade": trade_audit,
        "mark": mark_audit,
        "mark_supplements": mark_supp,
        "funding": funding,
    }
    manifest_path = AUDIT / "data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sums = []
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and "raw_cache" not in p.parts and p.name != "SHA256SUMS":
            sums.append(f"{sha256_file(p)}  {p.relative_to(ROOT).as_posix()}")
    (ROOT / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    import shutil
    shutil.rmtree(CACHE)
    print(json.dumps({
        "trade_rows": trade_audit["rows"],
        "trade_missing": trade_audit["missing_minute_count"],
        "mark_rows": mark_audit["rows"],
        "mark_missing": mark_audit["missing_minute_count"],
        "mark_supplement_rows": mark_supp["rows"],
        "mark_unresolved": mark_supp["unresolved_count"],
        "funding_rows": funding["rows"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
