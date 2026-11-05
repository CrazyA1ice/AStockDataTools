#!/usr/bin/env python3
"""Read-only bounded eight-cycle purchased-primary research query.

Native purchased Parquet is read in place for day, 15min, 30min, 60min, week,
month. 1min/5min delegate to the previously verified purchased-primary
stockday key-index router with explicitly opt-in, SHA-checked PRIVATE H5
fallback. No source copies, new indexes, H5 mirror or production activation.
The CLI emits counts/provenance only; local Python API returns licensed OHLCVA.

No vendor certification of physical units, corporate actions/adjustments,
non-5m cycle labels or weekly/monthly date semantics is implied.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import re
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERIODS = ("1min", "5min", "15min", "30min", "60min", "day", "week", "month")
MINUTES = ("1min", "5min")
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _load(tag, name):
    spec = importlib.util.spec_from_file_location(tag, HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PURCHASED = _load("all_cycle_original_parquet_query", "query-parquet-primary-readonly.py")
MINUTE = _load("all_cycle_private_gap_minute_query",
               "query-purchased-primary-minute-with-private-gap-readonly.py")
DAY_PRIVATE = _load("all_cycle_explicit_registered_combined_day_query",
                    "query-private-combined-day-22274-readonly.py")
DAY_EVIDENCE = frozenset((
    "version_sha256", "live_safe", "private_keys", "history_ledger",
    "source_2016", "source_2026", "mixed_plan",
))
DAY_PROVENANCE = (
    "purchased_parquet", "private_h5_whole_date_candidate",
    "private_h5_mixed_stockday_candidate",
)


def validate_private_day_evidence(evidence):
    """Require the exact explicit evidence set; never auto-detect stages."""
    if type(evidence) is not dict or set(evidence) != DAY_EVIDENCE:
        raise ValueError("Explicit 22,274 day evidence requires seven named fields")
    for k in DAY_EVIDENCE:
        if type(evidence[k]) is not str or not evidence[k].strip():
            raise ValueError("Untrusted private day evidence field: " + k)
    if not re.fullmatch(r"[a-f0-9]{64}", evidence["version_sha256"]):
        raise ValueError("Private combined day requires SHA256 registered version")
    return dict(evidence)


def load_private_day_config(path):
    """Read a tiny user-owned private research config; no credentials/market bars."""
    p = Path(path)
    private = (HERE.parent / "work" / "unified_parquet").resolve()
    if (p.is_symlink() or not p.is_file() or
            not p.resolve().is_relative_to(private)
            or p.stat().st_size > 8192 or p.stat().st_size == 0):
        raise ValueError("Private day config must be existing local work/unified_parquet JSON")
    def no_repeated_keys(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError("Repeated key in private day config: " + key)
            data[key] = value
        return data
    return validate_private_day_evidence(
        json.loads(p.read_text(encoding="utf-8"),
                   object_pairs_hook=no_repeated_keys))


def _registered_private_day_query(root, canonical, first, last,
                                  evidence, max_candidate_rows,
                                  max_result_bars):
    evidence = validate_private_day_evidence(evidence)
    first_d = DAY_PRIVATE.date.fromisoformat(str(first))
    last_d = DAY_PRIVATE.date.fromisoformat(str(last))
    if (first_d.year != last_d.year or first_d.year not in (2016, 2026)):
        raise ValueError("Registered 22,274 candidate day overlay is only 2016 or 2026")
    version = DAY_PRIVATE.REG.load_version(evidence["version_sha256"])
    if (version.get("ready_for_production_query") is not False
            or version.get("candidate_total_new_stockday_rows") != 22274):
        raise ValueError("Private combined day immutable version is not research-only")
    # Existing private combined query *already* performs live H5/PQ
    # source+SHA+key checks on EACH request, and creates only SAFE JSON.
    # Never bypass it or treat a manifest alone as sufficient proof.
    reports = DAY_PRIVATE.PRE.REPORTS
    runid = uuid.uuid4().hex
    recheck = reports / ("eight-cycle-day-22274-live-" + runid + ".json")
    out = reports / ("eight-cycle-day-22274-safe-" + runid + ".json")
    result = DAY_PRIVATE.query(
        root, canonical, first, last,
        evidence["version_sha256"], evidence["live_safe"],
        evidence["private_keys"], evidence["history_ledger"],
        evidence["source_2016"], evidence["source_2026"],
        evidence["mixed_plan"], recheck, out,
        max_candidate_rows=max_candidate_rows,
        max_result_bars=max_result_bars,
        max_overlay_source_rows=30000,
        fast_bounded_h5_scan=False)
    safe = result["safe_summary"]
    bars = result["bars"]
    if (safe.get("private_combined_version_sha256") !=
            evidence["version_sha256"]
            or safe.get("matching_stockday_bars") != len(bars)
            or safe.get("total_candidate_rows_in_registered_version") != 22274
            or safe.get("ready_for_production_query") is not False
            or safe.get("ready_for_automatic_market_merge") is not False
            or safe.get("source_market_files_written") is not False
            or safe.get("private_or_production_active_pointer_modified") is not False
            or safe.get("purchased_parquet_replaced") is not False
            or safe.get("no_raw_ohlcva_in_safe") is not True
            or safe.get("candidate_source_units_certified") is not False):
        raise ValueError("Private daily full live-source gate has unsafe or missing evidence")
    sources = {
        period: safe["matched_purchased_stockday_bars" if period ==
                "purchased_parquet" else
                "matched_private_whole_day_stockday_bars" if period ==
                "private_h5_whole_date_candidate" else
                "matched_private_mixed_day_stockday_bars"]
        for period in DAY_PROVENANCE
    }
    observed = Counter(row.get("value_source") for row in bars)
    if (any(type(n) is not int or n < 0 for n in sources.values())
            or sum(sources.values()) != len(bars)
            or any(observed[key] != sources[key] for key in DAY_PROVENANCE)
            or any(row.get("value_source") not in DAY_PROVENANCE for row in bars)):
        raise ValueError("Private daily per-stockday provenance does not conserve")
    return bars, sources, "explicit_immutable_22274_day_live_verified_purchased_first"



def query_bars(root, symbol, period, first, last, *,
               allow_verified_private_h5=False,
               max_candidate_rows=30000000, max_result_bars=10000,
               private_day_evidence=None):
    """Return original-source bars in local memory; no writes or silent fill."""
    if period not in PERIODS:
        raise ValueError("Unsupported K-line cycle (adjustment factors are not K-lines)")
    if type(allow_verified_private_h5) is not bool:
        raise ValueError("Private H5 fallback must be explicitly boolean")
    if allow_verified_private_h5 and period not in MINUTES:
        raise ValueError("Verified private H5 fallback exists only for 1min/5min")
    if private_day_evidence is not None:
        if period != "day" or allow_verified_private_h5:
            raise ValueError("Immutable 22,274 private overlay is exclusively day cycle")
        validate_private_day_evidence(private_day_evidence)
    # The original purchased API enforces single-security identity and bounded
    # 1..31 calendar day range before any market file is opened.
    canonical, _, _ = PURCHASED.request_dates(
        symbol, period, first, last, max_candidate_rows, max_result_bars)
    if private_day_evidence is not None:
        bars, sources, source_gate = _registered_private_day_query(
            root, canonical, first, last, private_day_evidence,
            max_candidate_rows, max_result_bars)
    elif period in MINUTES:
        result = MINUTE.query_bars(
            root, canonical, period, first, last,
            allow_verified_private_h5=allow_verified_private_h5,
            max_candidate_rows=max_candidate_rows,
            max_result_bars=max_result_bars)
        bars = result["bars"]
        sources = result["safe_summary"]["bars_by_source"]
        # Querying a period with purchased missing indexes still fails closed.
        source_gate = "purchased_key_index_first_with_explicit_h5_stockday_fallback"
    else:
        result = PURCHASED.query_bars(
            root, canonical, period, first, last,
            max_candidate_rows=max_candidate_rows,
            max_result_bars=max_result_bars, local_cache=False)
        bars = [{
            "symbol": row["symbol"], "period": row["period"],
            "trading_date": row["trading_date"],
            "source_timestamp_ms": row["source_timestamp_ms"],
            "source_beijing_time": row["source_beijing_time"],
            "value_source": "purchased_parquet",
            "source_file_relative_path": row["source_file_relative_path"],
            "source_row_group": row["source_row_group"],
            "h5_native_datetime": None,
            **{field: row[field] for field in FIELDS},
        } for row in result["bars"]]
        sources = {"purchased_parquet": len(bars)}
        source_gate = "original_purchased_parquet_direct_no_h5"
    if any(row.get("symbol") != canonical or row.get("period") != period
           for row in bars):
        raise ValueError("Unified cycle query returned a foreign symbol/period")
    if sum(sources.values()) != len(bars):
        raise ValueError("Unified cycle provenance counts mismatch")
    if len({row["source_timestamp_ms"] for row in bars}) != len(bars):
        raise ValueError("Unified cycle returned duplicate timestamps")
    return {
        "bars": bars,
        "safe_summary": {
            "format": "AStockDataTools purchased-primary eight-cycle research query v1",
            "period": period, "symbol": canonical,
            "from_day": str(first), "through_day": str(last),
            "matching_bar_count": len(bars),
            "bars_by_source": sources,
            "routing": source_gate,
            "purchased_source_priority": True,
            "verified_private_h5_fallback_enabled": allow_verified_private_h5,
            "registered_private_22274_day_overlay_explicitly_enabled":
                private_day_evidence is not None,
            "registered_private_day_version_sha256": (
                private_day_evidence["version_sha256"]
                if private_day_evidence is not None else None),
            "vendor_physical_units_certified": False,
            "corporate_action_adjustments_certified": False,
            "period_time_label_semantics_certified_for_all_cycles": False,
            "weekly_monthly_labels_are_raw_source_dates": period in ("week", "month"),
            "original_market_files_modified": False,
            "new_market_or_index_files_written": False,
            "production_query_activated": False,
            "no_raw_ohlcva_in_safe_summary": True,
        },
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--period", choices=PERIODS, required=True)
    p.add_argument("--from-day", required=True)
    p.add_argument("--through-day", required=True)
    p.add_argument("--allow-verified-private-h5", action="store_true")
    p.add_argument("--allow-registered-private-day", action="store_true",
                   help="Research only; requires --private-day-config and live evidence")
    p.add_argument("--private-day-config", type=Path, default=None,
                   help="Strictly private, seven-field version and evidence JSON under work/unified_parquet/")
    p.add_argument("--max-result-bars", type=int, default=10000)
    p.add_argument("--max-candidate-rows", type=int, default=30000000)
    args = p.parse_args(argv)
    if bool(args.allow_registered_private_day) != (args.private_day_config is not None):
        p.error("Private day requires BOTH explicit opt-in and private evidence config")
    evidence = (load_private_day_config(args.private_day_config)
                if args.allow_registered_private_day else None)
    result = query_bars(
        args.root, args.symbol, args.period, args.from_day, args.through_day,
        allow_verified_private_h5=args.allow_verified_private_h5,
        max_candidate_rows=args.max_candidate_rows,
        max_result_bars=args.max_result_bars,
        private_day_evidence=evidence)
    print(json.dumps(result["safe_summary"], ensure_ascii=False,
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
