#!/usr/bin/env python3
"""Apply the locked 2019-10 research start and normalized schema.

Binance Vision monthly archives for BTCUSDT USD-M 1m begin in 2020. The locked
2019-10 through 2019-12 prefix is therefore obtained from Binance's public,
no-key market-data REST endpoints and each response is hashed. Archive bytes
from 2020 onward remain verified against official adjacent .CHECKSUM files.
No account, key, order, balance, or live-trading endpoint is used.
"""
import datetime as dt
import csv
import gzip
import hashlib
import json
import time

import build_fbr_public_data as builder

LOCKED_START = dt.datetime(2019, 10, 1, tzinfo=dt.timezone.utc)
ARCHIVE_START = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
builder.START = LOCKED_START
_original_build_series = builder.build_series
_HEADER = [
    "open_time_ms", "open", "high", "low", "close", "volume",
    "close_time_ms", "quote_volume", "trade_count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _prefix_rows(dataset: str):
    endpoint = "/fapi/v1/klines" if dataset == "klines" else "/fapi/v1/markPriceKlines"
    cur = int(LOCKED_START.timestamp() * 1000)
    end_exclusive = int(ARCHIVE_START.timestamp() * 1000)
    rows = []
    receipts = []
    while cur < end_exclusive:
        payload, receipt = builder.public_json(endpoint, {
            "symbol": builder.SYMBOL,
            "interval": builder.INTERVAL,
            "startTime": cur,
            "endTime": end_exclusive - 1,
            "limit": 1500,
        })
        if not isinstance(payload, list):
            raise ValueError(f"unexpected {dataset} prefix payload: {payload!r}")
        receipts.append(receipt)
        if not payload:
            break
        advanced = cur
        for raw in payload:
            ts = builder.normalize_ts(str(raw[0]))
            if cur <= ts < end_exclusive:
                row = [str(ts)] + [str(x) for x in raw[1:12]]
                row[6] = str(builder.normalize_ts(row[6]))
                rows.append(row)
                advanced = max(advanced, ts + 60_000)
        if advanced <= cur:
            raise RuntimeError(f"{dataset} prefix pagination did not advance from {cur}")
        cur = advanced
        if len(payload) < 1500:
            break
        time.sleep(0.05)
    expected_first = int(LOCKED_START.timestamp() * 1000)
    expected_last = end_exclusive - 60_000
    if not rows or int(rows[0][0]) != expected_first or int(rows[-1][0]) != expected_last:
        raise ValueError(
            f"incomplete {dataset} REST prefix: rows={len(rows)}, "
            f"first={rows[0][0] if rows else None}, last={rows[-1][0] if rows else None}"
        )
    for a, b in zip(rows, rows[1:]):
        if int(b[0]) != int(a[0]) + 60_000:
            raise ValueError(f"gap/duplicate in {dataset} REST prefix at {a[0]} -> {b[0]}")
    return rows, receipts


def _build_series_with_prefix_and_header(dataset: str, output_name: str):
    # Restrict the archive builder to its first available full month, then restore
    # the locked start so funding and the final manifest retain the preregistration.
    builder.START = ARCHIVE_START
    try:
        receipts, audit = _original_build_series(dataset, output_name)
    finally:
        builder.START = LOCKED_START
    prefix, api_receipts = _prefix_rows(dataset)
    path = builder.ROOT / audit["normalized_path"]
    tmp = path.with_suffix(path.suffix + ".prefixfix")
    stream_hash = hashlib.sha256()
    total = 0
    first_ts = None
    last_ts = None
    missing = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as src, gzip.open(
        tmp, "wt", encoding="utf-8", newline="", compresslevel=6
    ) as dst:
        writer = csv.writer(dst, lineterminator="\n")
        writer.writerow(_HEADER)
        for row in prefix:
            writer.writerow(row)
            stream_hash.update((",".join(row) + "\n").encode())
            ts = int(row[0])
            if first_ts is None:
                first_ts = ts
            if last_ts is not None and ts != last_ts + 60_000:
                missing.extend(range(last_ts + 60_000, ts, 60_000))
            last_ts = ts
            total += 1
        reader = csv.reader(src)
        for row in reader:
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
        "rest_prefix_start_utc": LOCKED_START.isoformat(),
        "rest_prefix_end_exclusive_utc": ARCHIVE_START.isoformat(),
        "rest_prefix_rows": len(prefix),
        "rest_prefix_response_receipts": api_receipts,
    })
    return receipts, audit


builder.build_series = _build_series_with_prefix_and_header
raise SystemExit(builder.main())
