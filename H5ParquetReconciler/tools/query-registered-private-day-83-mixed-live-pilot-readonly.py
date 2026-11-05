#!/usr/bin/env python3
"""SHA-bound, private 83-stockday mixed-H5 research live smoke.

Uses only the existing registered 22,274-day immutable version and its
seven SHA-recovered private inputs. Selects one deterministic *2026* mixed
candidate from the complete 83-key private manifest. The exact security ID
is intentionally NEVER printed or put in reports. All H5/purchased Parquet
live source, candidate SHA, exact-key, quarantine, and purchased-first checks
are performed by the existing unified eight-cycle daily read-only query.

No wholesale rescan for candidate discovery; no new market index, version,
H5 mirror, production promotion, market-file write, or bar-value export.
The live source recheck itself MAY read original market data and write only
the existing query's aggregate SAFE JSON receipts.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS = ("open", "high", "low", "close", "volume", "amount")
EXPECTED_VERSION = "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23"


def load(tag, name):
    spec = importlib.util.spec_from_file_location(tag, HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVIDENCE = load("mixed_83_full_offline_provenance",
                "resolve-registered-day-22274-evidence-offline.py")
ALL = load("mixed_83_unified_day_live_query",
           "query-purchased-primary-all-eight-cycles-readonly.py")
KEYS = EVIDENCE.KEYS
MIXED = EVIDENCE.MIXED


def sample_2026_mixed_key(selected):
    """Select only from a complete, already verified 83-key set; no source IO."""
    if type(selected) is not set or len(selected) != 83:
        raise ValueError("Mixed private keyset must be exactly 83 unique records")
    eligible = []
    year_counts = Counter()
    for key in selected:
        if (type(key) is not tuple or len(key) != 2 or
                type(key[0]) is not str or type(key[1]) is not int):
            raise ValueError("Malformed SHA-verified exact stockday key")
        symbol, stamp = key
        if stamp % 10000:
            raise ValueError("Non-daily private mixed stockday timestamp")
        compact = str(stamp // 10000)
        if not re.fullmatch(r"20[0-9]{6}", compact):
            raise ValueError("Invalid private mixed H5 source day")
        day = date.fromisoformat(compact)
        if day.year not in (2016, 2026) or day.isoformat() == "2026-07-16":
            raise ValueError("Out-of-scope or quarantined mixed H5 source date")
        if not MIXED.CORE.is_a_share_candidate(symbol, day.year):
            raise ValueError("Mixed candidate security not an approved A-share")
        year_counts[day.year] += 1
        if day.year == 2026:
            eligible.append((day.isoformat(), symbol))
    if year_counts != Counter({2016: 1, 2026: 82}):
        raise ValueError("Private 83 keys no longer agree with 2016/2026 audits")
    if not eligible:
        raise ValueError("No verified 2026 mixed-stockday sample")
    day, symbol = sorted(eligible)[0]
    return symbol, day


def offline_sample(version_sha, config):
    """Reconstruct the exact 83-key sample and refuse stale config.

    No market H5/Parquet is opened here. Real live gate runs separately below.
    """
    if version_sha != EXPECTED_VERSION:
        raise ValueError("Unexpected immutable registered 22274-day version")
    evidence = EVIDENCE.resolve(version_sha)
    actual = ALL.load_private_day_config(config)
    if actual != evidence:
        raise ValueError("Private day config does not match current SHA-linked evidence")
    original, dates = KEYS.verified_existing_plan(
        evidence["history_ledger"], evidence["source_2016"],
        evidence["source_2026"], evidence["mixed_plan"])
    _, _, _, _, _, selected = MIXED.read_verified_key_manifest(
        evidence["live_safe"], evidence["private_keys"], original, dates)
    symbol, day = sample_2026_mixed_key(selected)
    return evidence, symbol, day


def query_one(root, version_sha, config, *,
              max_candidate_rows=30000000, max_result_bars=3):
    evidence, symbol, day = offline_sample(version_sha, config)
    live = ALL.query_bars(
        root, symbol, "day", day, day,
        private_day_evidence=evidence,
        max_candidate_rows=max_candidate_rows,
        max_result_bars=max_result_bars)
    summary = live["safe_summary"]
    bars = live["bars"]
    expected_sources = {
        "purchased_parquet": 0,
        "private_h5_whole_date_candidate": 0,
        "private_h5_mixed_stockday_candidate": 1,
    }
    if (type(bars) is not list or len(bars) != 1
            or summary.get("matching_bar_count") != 1
            or summary.get("bars_by_source") != expected_sources
            or summary.get("period") != "day"
            or summary.get("symbol") != symbol
            or summary.get("from_day") != day
            or summary.get("through_day") != day
            or summary.get("registered_private_day_version_sha256") != version_sha
            or summary.get("registered_private_22274_day_overlay_explicitly_enabled") is not True
            or summary.get("routing") !=
                "explicit_immutable_22274_day_live_verified_purchased_first"
            or summary.get("purchased_source_priority") is not True
            or summary.get("production_query_activated") is not False
            or summary.get("new_market_or_index_files_written") is not False
            or summary.get("original_market_files_modified") is not False
            or summary.get("no_raw_ohlcva_in_safe_summary") is not True):
        raise ValueError("Real 83-key mixed candidate returned unsafe or wrong provenance")
    row = bars[0]
    if (row.get("symbol") != symbol or row.get("trading_date") != day
            or row.get("period") != "day"
            or row.get("value_source") != "private_h5_mixed_stockday_candidate"
            or any(field not in row for field in FIELDS)):
        raise ValueError("Real mixed candidate is not a verified one-stockday H5 bar")
    # Deliberately do NOT print symbol, security-specific source metadata,
    # OHLCVA or raw data. An aggregate SAFE JSON is the entire CLI output.
    return {
        "state": "registered_22274_mixed_83_real_stockday_passed_live",
        "period": "day",
        "source_day": day,
        "source_security_identifier_redacted": True,
        "verified_candidate_version_sha256": version_sha,
        "matched_bars": 1,
        "bars_by_source": expected_sources,
        "source_priority": "purchased_parquet_first_no_overlap_fail_closed",
        "live_original_h5_and_purchased_parquet_rechecked": True,
        "source_ohlcva_values_exposed_in_safe": False,
        "source_market_files_modified": False,
        "private_candidate_version_changed": False,
        "h5_mirror_created": False,
        "production_active_pointer_changed": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--version-sha256", required=True)
    p.add_argument("--private-day-config", type=Path, required=True)
    p.add_argument("--max-candidate-rows", type=int, default=30000000)
    p.add_argument("--max-result-bars", type=int, default=3)
    a = p.parse_args(argv)
    result = query_one(a.root, a.version_sha256, a.private_day_config,
                       max_candidate_rows=a.max_candidate_rows,
                       max_result_bars=a.max_result_bars)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
