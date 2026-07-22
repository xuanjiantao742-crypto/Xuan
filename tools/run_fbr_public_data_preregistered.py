#!/usr/bin/env python3
"""Apply the locked FBR preregistration start date before invoking the builder.

This wrapper contains no account, key, order, or live-trading access.
"""
import datetime as dt
import build_fbr_public_data as builder

builder.START = dt.datetime(2019, 10, 1, tzinfo=dt.timezone.utc)
raise SystemExit(builder.main())
