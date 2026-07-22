#!/usr/bin/env python3
"""Apply locked preregistration and schema fixes before invoking the builder.

No account, key, order, balance, or live-trading endpoint is used. The wrapper
only changes the research start date and adds the declared CSV header that the
base builder omitted; archive bytes and their official checksums are untouched.
"""
import datetime as dt
import csv
import gzip
import pathlib
import tempfile

import build_fbr_public_data as builder

builder.START = dt.datetime(2019, 10, 1, tzinfo=dt.timezone.utc)
_original_build_series = builder.build_series
_HEADER = [
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
        writer.writerow(_HEADER)
        for line in src:
            dst.write(line)
    tmp.replace(path)
    audit["normalized_sha256"] = builder.sha256_file(path)
    audit["normalized_bytes"] = path.stat().st_size
    audit["header_added_by_preregistered_wrapper"] = True
    return receipts, audit


builder.build_series = _build_series_with_header
raise SystemExit(builder.main())
