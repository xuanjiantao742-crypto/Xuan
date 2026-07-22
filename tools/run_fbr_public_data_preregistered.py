#!/usr/bin/env python3
"""Build the checksum-verified price artifact for the locked pure-FBR window.

This wrapper implements preregistration amendments A001-A003 before any
strategy result is computed:
- effective optimization window: [2020-01-01, 2026-07-01) UTC;
- trade and mark 1m data: Binance Vision monthly archives, each verified
  against its adjacent official .CHECKSUM;
- funding artifact: Binance Vision complete monthly fundingRate archives;
- mark archive gaps: checksum-verified daily mark archives where available.

The local A003 preparation step subsequently merges the read-only Drive
package's preserved official Binance mark/funding raw responses and creates the
final immutable data lock. No account, API key, order, balance, or live-trading
endpoint is used here.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
from typing import Iterable

import build_fbr_public_data as builder

UTC = dt.timezone.utc
LOCKED_START = dt.datetime(2020, 1, 1, tzinfo=UTC)
LOCKED_CUTOFF = dt.datetime(2026, 7, 1, tzinfo=UTC)
builder.START = LOCKED_START
builder.CUTOFF = LOCKED_CUTOFF
_original_build_series = builder.build_series

OHLC_HEADER = [
    "open_time_ms", "open", "high", "low", "close", "volume",
    "close_time_ms", "quote_volume", "trade_count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _build_series_with_header(dataset: str, output_name: str):
    receipts, audit = _original_build_series(dataset, output_name)
    path = builder.ROOT / audit["normalized_path"]
    tmp = path.with_suffix(path.suffix + ".headerfix")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as src, gzip.open(
        tmp, "wt", encoding="utf-8", newline="", compresslevel=6
    ) as dst:
        writer = csv.writer(dst, lineterminator="\n")
        writer.writerow(OHLC_HEADER)
        for row in csv.reader(src):
            if row:
                writer.writerow(row)
    tmp.replace(path)
    audit.update({
        "normalized_sha256": builder.sha256_file(path),
        "normalized_bytes": path.stat().st_size,
        "header_added_by_preregistered_wrapper": True,
        "effective_start_utc": LOCKED_START.isoformat(),
        "effective_cutoff_exclusive_utc": LOCKED_CUTOFF.isoformat(),
        "amendments": ["A001", "A002", "A003"],
    })
    return receipts, audit


def _funding_url(month: dt.datetime) -> tuple[str, str]:
    period = month.strftime("%Y-%m")
    name = f"{builder.SYMBOL}-fundingRate-{period}.zip"
    return f"{builder.BASE}/monthly/fundingRate/{builder.SYMBOL}/{name}", name


def _month_starts(start: dt.datetime, end_exclusive: dt.datetime):
    cur = dt.datetime(start.year, start.month, 1, tzinfo=UTC)
    while cur < end_exclusive:
        yield cur
        cur = dt.datetime(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1, tzinfo=UTC)


def _build_funding_monthly() -> dict:
    out = builder.OUT / "btcusdt_funding_research.csv.gz"
    rows: dict[int, tuple[str, str]] = {}
    receipts = []
    for month in _month_starts(LOCKED_START, LOCKED_CUTOFF):
        url, name = _funding_url(month)
        local = builder.CACHE / "fundingRate" / "monthly" / name
        expected, actual, size = builder.download_verified(url, local)
        count = 0
        first = None
        last = None
        for raw in builder.iter_zip_rows(local):
            if len(raw) < 3:
                raise ValueError(f"short funding row in {local}: {raw}")
            ts = builder.normalize_ts(raw[0])
            if not (int(LOCKED_START.timestamp() * 1000) <= ts < int(LOCKED_CUTOFF.timestamp() * 1000)):
                continue
            value = (str(raw[1]), str(raw[2]))
            if ts in rows and rows[ts] != value:
                raise ValueError(f"conflicting funding duplicate at {ts}")
            rows[ts] = value
            count += 1
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
        receipt = {
            "dataset": "fundingRate",
            "cadence": "monthly",
            "period": month.strftime("%Y-%m"),
            "url": url,
            "local_name": str(local.relative_to(builder.ROOT)),
            "checksum_sha256": expected,
            "actual_sha256": actual,
            "bytes": size,
            "rows": count,
            "first_ts_ms": first,
            "last_ts_ms": last,
        }
        receipts.append(receipt)
        print(f"fundingRate {receipt['period']}: {count:,} rows", flush=True)

    ordered = sorted(rows.items())
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        writer = csv.writer(gz, lineterminator="\n")
        writer.writerow(["funding_time_ms", "funding_rate", "mark_price", "funding_interval_hours"])
        for ts, (hours, rate) in ordered:
            writer.writerow([ts, rate, "", hours])
    return {
        "dataset": "Binance Vision fundingRate monthly archives",
        "normalized_path": str(out.relative_to(builder.ROOT)),
        "normalized_sha256": builder.sha256_file(out),
        "normalized_bytes": out.stat().st_size,
        "rows": len(ordered),
        "first_ts_ms": ordered[0][0] if ordered else None,
        "last_ts_ms": ordered[-1][0] if ordered else None,
        "archive_receipts": receipts,
        "effective_cutoff_exclusive_utc": LOCKED_CUTOFF.isoformat(),
    }


def _build_mark_supplements_daily(missing: Iterable[int]) -> dict:
    missing = sorted(set(int(x) for x in missing))
    needed = set(missing)
    found: dict[int, list[str]] = {}
    receipts = []
    days = sorted({dt.datetime.fromtimestamp(ts / 1000, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0) for ts in missing})
    for day in days:
        url, name = builder.archive_url("markPriceKlines", "daily", day)
        local = builder.CACHE / "markPriceKlines" / "daily" / name
        try:
            expected, actual, size = builder.download_verified(url, local)
        except Exception as exc:
            receipts.append({
                "dataset": "markPriceKlines",
                "cadence": "daily",
                "period": day.strftime("%Y-%m-%d"),
                "url": url,
                "status": "archive_unavailable",
                "error": f"{type(exc).__name__}: {exc}",
                "rows_inserted": 0,
            })
            continue
        count = 0
        for raw in builder.iter_zip_rows(local):
            if len(raw) < 12:
                continue
            ts = builder.normalize_ts(raw[0])
            if ts not in needed:
                continue
            row = list(raw[:12])
            row[0] = str(ts)
            row[6] = str(builder.normalize_ts(row[6]))
            found[ts] = row
            count += 1
        receipts.append({
            "dataset": "markPriceKlines",
            "cadence": "daily",
            "period": day.strftime("%Y-%m-%d"),
            "url": url,
            "checksum_sha256": expected,
            "actual_sha256": actual,
            "bytes": size,
            "rows_inserted": count,
            "status": "checksum_verified",
        })

    unresolved = [ts for ts in missing if ts not in found]
    out = builder.OUT / "btcusdt_mark_supplements_research.csv.gz"
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        writer = csv.writer(gz, lineterminator="\n")
        writer.writerow(OHLC_HEADER)
        for ts in sorted(found):
            writer.writerow(found[ts])
    return {
        "normalized_path": str(out.relative_to(builder.ROOT)),
        "normalized_sha256": builder.sha256_file(out),
        "normalized_bytes": out.stat().st_size,
        "rows": len(found),
        "requested_missing_minutes": len(missing),
        "unresolved_count": len(unresolved),
        "unresolved_minutes_ms": unresolved,
        "archive_receipts": receipts,
        "completion_note": "remaining gaps are completed only by the local A003 audited preparation step",
    }


builder.build_series = _build_series_with_header
builder.build_funding = _build_funding_monthly
builder.build_mark_supplements = _build_mark_supplements_daily
raise SystemExit(builder.main())
