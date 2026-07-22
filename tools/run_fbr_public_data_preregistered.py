#!/usr/bin/env python3
"""Apply the locked FBR research window using checksum-verified Binance Vision data.

The research window starts at 2019-10-01 UTC and ends immediately before
2026-07-21 UTC. All price and funding inputs are obtained from Binance's public
archive only. Every ZIP is checked against its adjacent official .CHECKSUM.
No account, key, balance, order, or live-trading endpoint is used.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
from dataclasses import asdict
from typing import Iterable, Iterator

import build_fbr_public_data as builder

UTC = dt.timezone.utc
LOCKED_START = dt.datetime(2019, 10, 1, tzinfo=UTC)
ARCHIVE_MONTHLY_START = dt.datetime(2020, 1, 1, tzinfo=UTC)
builder.START = LOCKED_START
_original_build_series = builder.build_series

_OHLC_HEADER = [
    "open_time_ms", "open", "high", "low", "close", "volume",
    "close_time_ms", "quote_volume", "trade_count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _days(start: dt.datetime, end_exclusive: dt.datetime) -> Iterator[dt.datetime]:
    cur = start
    while cur < end_exclusive:
        yield cur
        cur += dt.timedelta(days=1)


def _months(start: dt.datetime, end_exclusive: dt.datetime) -> Iterator[dt.datetime]:
    cur = dt.datetime(start.year, start.month, 1, tzinfo=UTC)
    while cur < end_exclusive:
        yield cur
        if cur.month == 12:
            cur = dt.datetime(cur.year + 1, 1, 1, tzinfo=UTC)
        else:
            cur = dt.datetime(cur.year, cur.month + 1, 1, tzinfo=UTC)


def _download_ohlc_archive(dataset: str, cadence: str, when: dt.datetime):
    url, name = builder.archive_url(dataset, cadence, when)
    local = builder.CACHE / dataset / cadence / name
    expected, actual, size = builder.download_verified(url, local)
    receipt = builder.ArchiveReceipt(
        dataset=dataset,
        cadence=cadence,
        period=when.strftime("%Y-%m" if cadence == "monthly" else "%Y-%m-%d"),
        url=url,
        local_name=str(local.relative_to(builder.ROOT)),
        checksum_sha256=expected,
        actual_sha256=actual,
        bytes=size,
    )
    return local, receipt


def _daily_prefix_rows(dataset: str):
    """Load 2019-10..2019-12 from official daily archives with checksums."""
    rows: list[list[str]] = []
    receipts = []
    for day in _days(LOCKED_START, ARCHIVE_MONTHLY_START):
        local, receipt = _download_ohlc_archive(dataset, "daily", day)
        day_start = int(day.timestamp() * 1000)
        day_end = day_start + 86_400_000
        for raw in builder.iter_zip_rows(local):
            if len(raw) < 12:
                raise ValueError(f"short row in {local}: {raw}")
            ts = builder.normalize_ts(raw[0])
            if not (day_start <= ts < day_end):
                continue
            row = list(raw[:12])
            row[0] = str(ts)
            row[6] = str(builder.normalize_ts(row[6]))
            receipt.rows += 1
            if receipt.first_ts_ms is None:
                receipt.first_ts_ms = ts
            receipt.last_ts_ms = ts
            rows.append(row)
        receipts.append(receipt)
        print(f"{dataset} {receipt.period}: {receipt.rows:,} rows", flush=True)

    rows.sort(key=lambda r: int(r[0]))
    for a, b in zip(rows, rows[1:]):
        if int(b[0]) <= int(a[0]):
            raise ValueError(f"duplicate/out-of-order {dataset} prefix at {a[0]} -> {b[0]}")
    return rows, receipts


def _build_series_with_prefix_and_header(dataset: str, output_name: str):
    # The base builder uses monthly archives for completed months and daily archives
    # for the current partial month. Restrict it to 2020+, then prepend 2019 daily files.
    builder.START = ARCHIVE_MONTHLY_START
    try:
        receipts, audit = _original_build_series(dataset, output_name)
    finally:
        builder.START = LOCKED_START

    prefix, prefix_receipts = _daily_prefix_rows(dataset)
    path = builder.ROOT / audit["normalized_path"]
    tmp = path.with_suffix(path.suffix + ".prefixfix")
    stream_hash = hashlib.sha256()
    total = 0
    first_ts = None
    last_ts = None
    missing: list[int] = []

    with gzip.open(path, "rt", encoding="utf-8", newline="") as src, gzip.open(
        tmp, "wt", encoding="utf-8", newline="", compresslevel=6
    ) as dst:
        writer = csv.writer(dst, lineterminator="\n")
        writer.writerow(_OHLC_HEADER)
        for row in prefix:
            ts = int(row[0])
            if first_ts is None:
                first_ts = ts
            if last_ts is not None and ts != last_ts + 60_000:
                missing.extend(range(last_ts + 60_000, ts, 60_000))
            writer.writerow(row)
            stream_hash.update((",".join(row) + "\n").encode())
            last_ts = ts
            total += 1

        for row in csv.reader(src):
            if not row:
                continue
            ts = int(row[0])
            if last_ts is not None and ts <= last_ts:
                raise ValueError(f"non-increasing archive join at {last_ts} -> {ts}")
            if last_ts is not None and ts != last_ts + 60_000:
                missing.extend(range(last_ts + 60_000, ts, 60_000))
            writer.writerow(row)
            stream_hash.update((",".join(row) + "\n").encode())
            last_ts = ts
            total += 1

    tmp.replace(path)
    audit.update({
        "rows": total,
        "first_ts_ms": first_ts,
        "last_ts_ms": last_ts,
        "missing_minute_count": len(missing),
        "missing_minutes_ms": missing,
        "normalized_sha256": builder.sha256_file(path),
        "normalized_bytes": path.stat().st_size,
        "canonical_row_stream_sha256": stream_hash.hexdigest(),
        "header_added_by_preregistered_wrapper": True,
        "daily_archive_prefix_start_utc": LOCKED_START.isoformat(),
        "daily_archive_prefix_end_exclusive_utc": ARCHIVE_MONTHLY_START.isoformat(),
        "daily_archive_prefix_rows": len(prefix),
    })
    return prefix_receipts + receipts, audit


def _funding_archive_url(cadence: str, when: dt.datetime) -> tuple[str, str]:
    period = when.strftime("%Y-%m" if cadence == "monthly" else "%Y-%m-%d")
    name = f"{builder.SYMBOL}-fundingRate-{period}.zip"
    url = f"{builder.BASE}/{cadence}/fundingRate/{builder.SYMBOL}/{name}"
    return url, name


def _build_funding_from_archives() -> dict:
    """Build actual historical funding events from official fundingRate archives."""
    out = builder.OUT / "btcusdt_funding_research.csv.gz"
    month_cut = dt.datetime(builder.CUTOFF.year, builder.CUTOFF.month, 1, tzinfo=UTC)
    periods = [("monthly", m) for m in _months(LOCKED_START, month_cut)]
    periods.extend(("daily", d) for d in _days(month_cut, builder.CUTOFF))

    rows: dict[int, tuple[str, str]] = {}
    receipts = []
    for cadence, when in periods:
        url, name = _funding_archive_url(cadence, when)
        local = builder.CACHE / "fundingRate" / cadence / name
        expected, actual, size = builder.download_verified(url, local)
        count = 0
        first = None
        last = None
        for raw in builder.iter_zip_rows(local):
            if len(raw) < 3:
                raise ValueError(f"short funding row in {local}: {raw}")
            ts = builder.normalize_ts(raw[0])
            if not (int(LOCKED_START.timestamp() * 1000) <= ts < int(builder.CUTOFF.timestamp() * 1000)):
                continue
            interval_hours = str(raw[1])
            rate = str(raw[2])
            old = rows.get(ts)
            if old is not None and old != (interval_hours, rate):
                raise ValueError(f"conflicting funding duplicate at {ts}: {old} vs {(interval_hours, rate)}")
            rows[ts] = (interval_hours, rate)
            count += 1
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
        receipts.append({
            "dataset": "fundingRate",
            "cadence": cadence,
            "period": when.strftime("%Y-%m" if cadence == "monthly" else "%Y-%m-%d"),
            "url": url,
            "local_name": str(local.relative_to(builder.ROOT)),
            "checksum_sha256": expected,
            "actual_sha256": actual,
            "bytes": size,
            "rows": count,
            "first_ts_ms": first,
            "last_ts_ms": last,
        })
        print(f"fundingRate {receipts[-1]['period']}: {count:,} rows", flush=True)

    ordered = sorted(rows.items())
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        w = csv.writer(gz, lineterminator="\n")
        w.writerow(["funding_time_ms", "funding_rate", "mark_price", "funding_interval_hours"])
        for ts, (hours, rate) in ordered:
            w.writerow([ts, rate, "", hours])

    return {
        "dataset": "Binance Vision fundingRate archives",
        "normalized_path": str(out.relative_to(builder.ROOT)),
        "normalized_sha256": builder.sha256_file(out),
        "normalized_bytes": out.stat().st_size,
        "rows": len(ordered),
        "first_ts_ms": ordered[0][0] if ordered else None,
        "last_ts_ms": ordered[-1][0] if ordered else None,
        "archive_receipts": receipts,
        "rest_pages": [],
    }


def _build_mark_supplements_from_daily(missing: Iterable[int]) -> dict:
    """Fill monthly mark archive gaps from checksum-verified daily mark archives."""
    missing = sorted(set(int(x) for x in missing))
    out = builder.OUT / "btcusdt_mark_supplements_research.csv.gz"
    needed = set(missing)
    found: dict[int, list[str]] = {}
    receipts = []
    days = sorted({dt.datetime.fromtimestamp(ts / 1000, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0) for ts in missing})
    for day in days:
        local, receipt = _download_ohlc_archive("markPriceKlines", "daily", day)
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
            receipt.rows += 1
            if receipt.first_ts_ms is None:
                receipt.first_ts_ms = ts
            receipt.last_ts_ms = ts
        receipts.append(asdict(receipt))

    unresolved = [ts for ts in missing if ts not in found]
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
        w = csv.writer(gz, lineterminator="\n")
        w.writerow(_OHLC_HEADER)
        for ts in sorted(found):
            w.writerow(found[ts])

    return {
        "normalized_path": str(out.relative_to(builder.ROOT)),
        "normalized_sha256": builder.sha256_file(out),
        "normalized_bytes": out.stat().st_size,
        "rows": len(found),
        "requested_missing_minutes": len(missing),
        "unresolved_count": len(unresolved),
        "unresolved_minutes_ms": unresolved,
        "archive_receipts": receipts,
        "rest_pages": [],
    }


builder.build_series = _build_series_with_prefix_and_header
builder.build_funding = _build_funding_from_archives
builder.build_mark_supplements = _build_mark_supplements_from_daily
raise SystemExit(builder.main())
