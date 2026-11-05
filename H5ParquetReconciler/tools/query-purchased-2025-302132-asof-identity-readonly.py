#!/usr/bin/env python3
"""Opt-in 2025 SZ302132 vendor-relabelled original 1/5min read-only pilot.

The purchased vendor's full-year 2025 dataset stores all 243 observed 5min
stockdays under SZ302132, including 26 pre-2025-02-17 days. Official issuer
code changed from SZ300114 to SZ302132 effective 2025-02-17.

This pilot reuses the existing purchased Parquet RowGroup query with a narrow
per-call source-code exception. It preserves source_symbol EXACTLY as stored,
adds a distinct as-of official code label and fails if any observed stockday
is missing the full native-source time grid (1m 241 / 5m 48).

Neither original Parquet, private minute indexes, H5 fallback nor production
identity rules are touched. No local licensed-bar cache. CLI prints ONLY
aggregate source code/day counts; OHLCVA is returned in Python memory only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_CODE = "SZ302132"
OLD_CODE = "SZ300114"
EFFECTIVE = date(2025, 2, 17)
ALLOWED = ("1min", "5min")
FIELDS = ("open", "high", "low", "close", "volume", "amount")
NOTICE = ("https://disc.static.szse.cn/download/disc/disk03/finalpage/"
          "2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF")


def _load(tag, filename):
    spec = importlib.util.spec_from_file_location(tag, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


Q = _load("302132_purchased_original_bounded_query",
          "query-parquet-primary-readonly.py")
GRID = _load("302132_exact_source_session_key_grid",
             "preview-minute-exact-key-diff-readonly.py")
KEY_FIRST = _load("302132_two_phase_original_source_key_first",
                  "query-purchased-2025-302132-key-first-bounded-readonly.py")


def official_code_asof(trading_day):
    day = date.fromisoformat(trading_day) if isinstance(trading_day, str) else trading_day
    if type(day) is not date or day.year != 2025:
        raise ValueError("Issuer as-of identity pilot only supports 2025")
    return OLD_CODE if day < EFFECTIVE else SOURCE_CODE


def _expected_keys(day, period):
    keys = set(GRID.normalized_native_keys(day, period).values())
    if period == "1min":
        keys.add(GRID.I.day_epoch_ms(day) + 570 * 60000)
    if len(keys) != (241 if period == "1min" else 48):
        raise ValueError("Untrusted canonical 2025 1/5min time reference")
    return keys


def query_bars(root, period, first, last, *,
               max_candidate_rows=30000000, max_result_bars=10000):
    if period not in ALLOWED:
        raise ValueError("Documented SZ302132 pilot supports only 1min/5min")
    _, from_day, through_day = Q.request_dates(
        SOURCE_CODE, period, first, last, max_candidate_rows,
        max_result_bars, allow_2025_302132_source=True)
    if from_day.year != 2025 or through_day.year != 2025:
        raise ValueError("Source-code change mapping must stay in 2025")
    underlying = KEY_FIRST.query_bars(
        root, SOURCE_CODE, period, first, last,
        max_candidate_rows=max_candidate_rows,
        max_result_bars=max_result_bars)
    original = underlying["bars"]
    days = defaultdict(set)
    annotated = []
    counts = Counter()
    for row in original:
        if (row.get("symbol") != SOURCE_CODE or row.get("period") != period
                or row.get("trading_date") is None
                or type(row.get("source_timestamp_ms")) is not int):
            raise ValueError("Unexpected source security/period/time key")
        day = date.fromisoformat(row["trading_date"])
        if not from_day <= day <= through_day or day.year != 2025:
            raise ValueError("Source date escaped audited 2025 window")
        ts = row["source_timestamp_ms"]
        if ts in days[day]:
            raise ValueError("Duplicate vendor source key")
        days[day].add(ts)
        asof = official_code_asof(day)
        counts[asof] += 1
        annotated.append({
            **row, "vendor_source_symbol": SOURCE_CODE,
            "official_symbol_asof_trading_date": asof,
            "issuer_stable_identity": "2025_300114_to_302132_single_issuer",
            "official_code_effective_from": EFFECTIVE.isoformat(),
            "asof_code_is_annotation_not_source_rewrite": True,
        })
    for day, actual_keys in days.items():
        if actual_keys != _expected_keys(day, period):
            raise ValueError("Observed 2025 SZ302132 source stockday has nonstandard time keys")
    if underlying["safe_summary"]["matching_bar_count"] != len(annotated):
        raise ValueError("Original purchased summary and selected bars differ")
    return {
        "bars": annotated,
        "safe_summary": {
            "format": "AStockDataTools opt-in 2025 issuer as-of identity source query v1",
            "status": "explicit_2025_documented_vendor_code_source_relabel_research_only",
            "source_symbol": SOURCE_CODE,
            "old_official_symbol": OLD_CODE,
            "new_official_symbol": SOURCE_CODE,
            "official_code_change_day": EFFECTIVE.isoformat(),
            "period": period,
            "from_day": from_day.isoformat(),
            "through_day": through_day.isoformat(),
            "source_matching_bars": len(annotated),
            "observed_complete_source_stockdays": len(days),
            "source_bars_annotated_by_asof_code": dict(sorted(counts.items())),
            "original_vendor_source_code_preserved": True,
            "vendor_historic_relabelling_detected_in_2025": True,
            "bar_value_source": "purchased_parquet",
            "issuer_notice_reference": NOTICE,
            "A_share_global_code_filter_changed": False,
            "purchased_minute_key_index_rebuilt": False,
            "private_licensed_bar_cache_written": False,
            "H5_fallback_invoked": False,
            "original_market_files_modified": False,
            "production_identity_mapping_activated": False,
            "vendor_ohlcva_unit_certified": False,
            "official_identity_asof_code_is_not_original_source_label": True,
            "source_timestamp_semantics_not_rewritten": True,
            "raw_ohlcva_in_safe_summary": False,
            "source_key_only_rows_scanned":
                underlying["safe_summary"]["key_only_source_rows_scanned"],
            "source_ohlcva_rowgroups_read":
                underlying["safe_summary"]["physical_ohlcva_rowgroups_read"],
            "source_ohlcva_rows_read":
                underlying["safe_summary"]["physical_ohlcva_source_rows_read"],
            "source_ohlcva_budget":
                underlying["safe_summary"]["physical_ohlcva_rows_budget"],
            "key_only_to_ohlcva_exact_key_verified":
                underlying["safe_summary"]["keys_equal_between_key_probe_and_ohlcva"],
            "native_session_grid_checked_before_ohlcva":
                underlying["safe_summary"]["native_session_grid_checked_before_ohlcva"],
            "generic_purchased_query_budget_unchanged":
                underlying["safe_summary"]["generic_purchased_query_budget_unchanged"],
            "physical_ohlcva_exception_scope":
                underlying["safe_summary"]["physical_ohlcva_exception_scope"],
        },
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--period", choices=ALLOWED, required=True)
    p.add_argument("--from-day", required=True)
    p.add_argument("--through-day", required=True)
    p.add_argument("--max-candidate-rows", type=int, default=30000000)
    p.add_argument("--max-result-bars", type=int, default=10000)
    args = p.parse_args(argv)
    result = query_bars(
        args.root, args.period, args.from_day, args.through_day,
        max_candidate_rows=args.max_candidate_rows,
        max_result_bars=args.max_result_bars)
    print(json.dumps(result["safe_summary"], ensure_ascii=False,
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
