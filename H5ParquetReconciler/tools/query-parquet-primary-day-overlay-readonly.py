#!/usr/bin/env python3
"""EXPLICIT private day-overlay query: purchased Parquet first, verified H5 gap only.

Research-only read path. Never reads active-day-overlay.json, writes a market
source, publishes a production database, or changes original units. Requires
a specific immutable prepared version SHA and re-audits the requested H5-only
dates against the live originals before returning any private overlay bars.

Only SAFE counts/provenance are written to module reports/. Actual OHLCVA bars
are returned to the local Python caller and optionally printed with opt-in.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def import_tool(module_name, file_name):
    spec = importlib.util.spec_from_file_location(module_name, HERE / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


purchased = import_tool("private_day_overlay_purchased_query",
                        "query-parquet-primary-readonly.py")
versioner = import_tool("private_day_overlay_version_check",
                        "build-parquet-primary-day-overlay.py")
FIELDS = ("open", "high", "low", "close", "volume", "amount")
FORMAT = "AStockDataTools explicit private Parquet day overlay query summary v1"


def _report_name(value):
    if (type(value) is not str or not value.endswith(".json")
            or value != Path(value).name or "/" in value or "\\" in value):
        raise ValueError("Private version must name a module reports JSON basename")
    return value


def verified_version(version_sha256, max_overlay_source_rows):
    """Verify ALL private stage hashes, key sets and source report linkage."""
    if (type(max_overlay_source_rows) is not int
            or not 1 <= max_overlay_source_rows <= 1000000):
        raise ValueError("Invalid bounded private overlay source-row budget")
    versioner.safe_private()
    record = versioner.load_version(version_sha256)
    if (record.get("status") != "prepared_private_day_overlay_not_production"
            or record.get("period") != "day"
            or record.get("source_parquet_priority") is not True
            or record.get("safe_to_automatically_union") is not False
            or record.get("production_query_route_modified") is not False
            or record.get("purchased_historical_parquet_modified") is not False
            or record.get("h5_market_files_modified") is not False
            or type(record.get("rows_in_overlay")) is not int
            or record["rows_in_overlay"] < 1
            or record["rows_in_overlay"] > max_overlay_source_rows):
        raise ValueError("Private overlay is not an eligible bounded prepared version")
    gate = versioner.MODULE / "reports" / _report_name(
        record.get("gate_report_basename"))
    source = versioner.MODULE / "reports" / _report_name(
        record.get("source_report_basename"))
    evidence = versioner.verify_reports(gate, source)
    if (record.get("source_report_sha256") != evidence["source_sha"]
            or record.get("gate_report_sha256") != evidence["gate_sha"]):
        raise ValueError("Private version reports changed after prepare")
    stages = record.get("stages")
    if (not isinstance(stages, list)
            or not stages
            or any(not isinstance(x, dict)
                   or type(x.get("stage_dir")) is not str
                   for x in stages)):
        raise ValueError("Invalid immutable stage manifest")
    actual = versioner.validate_stages(
        [versioner.MODULE / item["stage_dir"] for item in stages], evidence)
    if (actual != stages or
            sum(row["rows"] for row in actual) != record["rows_in_overlay"]):
        raise ValueError("Private stage SHA/key/count evidence differs from version")
    return record, evidence, actual


def _decode_selected_stage(stage, symbol):
    """Read at most ONE verified staged date and select a canonical stock."""
    import pyarrow.parquet as pq

    stage_dir = versioner.safe_stage_path(
        versioner.MODULE / stage["stage_dir"])
    path = stage_dir / "day.parquet"
    table = pq.read_table(path, columns=list(versioner.stage_tool.SCHEMA_FIELDS))
    if table.num_rows != stage["rows"]:
        raise ValueError("Private staged Parquet row count changed during read")
    seen = set()
    selected = []
    trading_day = date.fromisoformat(stage["day"])
    stamp = int(datetime(trading_day.year, trading_day.month,
                         trading_day.day,
                         tzinfo=versioner.stage_tool.core.UTC8).timestamp() * 1000)
    for item in table.to_pylist():
        canonical = versioner.stage_tool.core.symbol_id(item["symbol"])
        if (item["ts"] != stamp or
                item["source"] != "hikyuu_h5_tail_candidate" or
                canonical is None or canonical in seen):
            raise ValueError("Invalid/duplicate private stage day-stock key")
        seen.add(canonical)
        if canonical != symbol:
            continue
        values = tuple(float(item[key]) for key in FIELDS)
        if (not all(math.isfinite(v) for v in values)
                or min(values[:4]) <= 0 or
                values[1] + 1e-8 < max(values[0], values[2], values[3]) or
                values[2] - 1e-8 > min(values[0], values[1], values[3]) or
                values[4] < 0 or values[5] < 0):
            raise ValueError("Invalid OHLCVA in selected private staged day bar")
        selected.append({
            "symbol": symbol, "period": "day",
            "trading_date": trading_day.isoformat(),
            "source_timestamp_ms": stamp,
            "source_beijing_time": datetime.fromtimestamp(
                stamp / 1000, tz=versioner.stage_tool.core.UTC8
            ).strftime("%Y-%m-%d %H:%M"),
            "normalized_query_label": trading_day.isoformat(),
            "source_file_relative_path": (
                stage["stage_dir"] + "/day.parquet"),
            "source_row_group": None,
            "value_source": "private_hikyuu_h5_gap_candidate",
            **dict(zip(FIELDS, values)),
        })
    if versioner.stage_tool.file_digest(path) != stage["parquet_sha256"]:
        raise ValueError("Private Parquet bytes changed while querying")
    return selected


def query_private_day_overlay(root, symbol, first, last, version_sha256,
                              max_candidate_rows=30000000,
                              max_result_bars=25000,
                              max_overlay_source_rows=30000):
    """Bounded experimental unified daily query (no implicit pointer access).

    The purchased Parquet remains authoritative for any existing date-stock.
    Any newly appeared purchased bars on a private-overlay date FAIL CLOSED:
    an originally wholly absent day may not become a silent mixed-day merge.
    """
    query_started = time.perf_counter()
    canonical, start, end = purchased.request_dates(
        symbol, "day", first, last, max_candidate_rows, max_result_bars)
    root = Path(root).resolve()
    record, evidence, stages = verified_version(
        version_sha256, max_overlay_source_rows)
    version_verified_at = time.perf_counter()
    requested_stages = [
        item for item in stages
        if start <= date.fromisoformat(item["day"]) <= end
    ]
    source_before = None
    if requested_stages:
        year = date.fromisoformat(requested_stages[0]["day"]).year
        if any(date.fromisoformat(x["day"]).year != year
               for x in requested_stages):
            raise ValueError("Private query does not allow multi-year gap audits")
        # A prepared snapshot is not a live market-source absence guarantee.
        # Recheck exact full-day keys before exposing H5-only private values.
        source_before = versioner.stage_tool.source_file_states(root, year)
        scratch = versioner.MODULE / "work" / "overlay_query_live_recheck"
        scratch.mkdir(parents=True, exist_ok=True)
        for stage in requested_stages:
            versioner.stage_tool.verify_live_absence(
                root, scratch, date.fromisoformat(stage["day"]),
                evidence["expected"][stage["day"]])
    live_recheck_finished_at = time.perf_counter()
    base = purchased.query_bars(
        root, canonical, "day", start.isoformat(), end.isoformat(),
        max_candidate_rows=max_candidate_rows,
        max_result_bars=max_result_bars, local_cache=False)
    purchased_query_finished_at = time.perf_counter()
    baseline_rows = []
    for bar in base["bars"]:
        baseline_rows.append({**bar, "value_source": "purchased_parquet"})
    private_rows = []
    for item in requested_stages:
        private_rows.extend(_decode_selected_stage(item, canonical))
    private_decode_finished_at = time.perf_counter()
    baseline_dates = {row["trading_date"] for row in baseline_rows}
    if any(row["trading_date"] in baseline_dates for row in private_rows):
        raise ValueError("Purchased/private day overlap; stale overlay cannot mix")
    if len(baseline_rows) + len(private_rows) > max_result_bars:
        raise ValueError("Combined private day query exceeds --max-result-bars")
    if source_before is not None and (
            source_before != versioner.stage_tool.source_file_states(root, year)):
        raise ValueError("Market source size/mtime changed during private query")
    rows = sorted(baseline_rows + private_rows,
                  key=lambda r: (r["trading_date"],
                                 r["source_timestamp_ms"]))
    summary = dict(base["safe_summary"])
    # The underlying Parquet query reports its own scan amplification and
    # elapsed time. Those metrics exclude staged Parquet reads and the
    # costly fresh full-day H5/PQ absence audits. A unified denominator of
    # five returned bars must not be paired with a numerator for only one
    # purchased bar without an explicit measurement scope.
    purchased_scanned = summary["source_rows_scanned"]
    purchased_count = len(baseline_rows)
    private_decoded = sum(item["rows"] for item in requested_stages)
    known_read_rows = purchased_scanned + private_decoded
    purchased_elapsed = summary["query_elapsed_seconds_this_invocation"]
    summary.update({
        "format": FORMAT,
        "period": "day",
        "private_version_sha256": record["version_sha256"],
        "private_version_prepared_not_activated": True,
        "private_overlay_dates_live_rechecked": [
            item["day"] for item in requested_stages],
        "private_overlay_stages_sha_and_keys_verified": True,
        "private_overlay_bars_returned": len(private_rows),
        "purchased_parquet_bars_returned": len(baseline_rows),
        "matching_bar_count": len(rows),
        "source_rows_read_per_returned_bar": None,
        "inherited_source_rows_per_returned_bar_suppressed": True,
        "purchased_parquet_source_rows_scanned": purchased_scanned,
        "purchased_parquet_source_rows_per_purchased_bar": (
            round(purchased_scanned / purchased_count, 3)
            if purchased_count else None),
        "known_minimum_purchased_plus_stage_rows_decoded": known_read_rows,
        "known_minimum_rows_per_combined_returned_bar": (
            round(known_read_rows / len(rows), 3) if rows else None),
        "known_minimum_excludes_live_h5_pq_absence_recheck_io": True,
        "purchased_query_elapsed_seconds_this_invocation": purchased_elapsed,
        "private_version_verification_elapsed_seconds_this_invocation": round(
            version_verified_at - query_started, 6),
        "live_absence_recheck_elapsed_seconds_this_invocation": round(
            live_recheck_finished_at - version_verified_at, 6),
        "purchased_stage_elapsed_seconds_this_invocation": round(
            purchased_query_finished_at - live_recheck_finished_at, 6),
        "private_stage_decode_elapsed_seconds_this_invocation": round(
            private_decode_finished_at - purchased_query_finished_at, 6),
        "query_elapsed_seconds_this_invocation": round(
            time.perf_counter() - query_started, 6),
        "elapsed_time_includes_version_stage_checks_and_live_audit": True,
        "first_matching_raw_beijing_label": (
            rows[0]["source_beijing_time"] if rows else None),
        "last_matching_raw_beijing_label": (
            rows[-1]["source_beijing_time"] if rows else None),
        "query_delivery": "explicit_private_day_overlay_readonly_pilot",
        "source_priority_policy": "purchased_existing_date_wins; stale_gap_rejected",
        "h5_day_units_are_diagnostic_candidate_not_supplier_certified": True,
        "source_quantity_unit_rescaling_applied": bool(private_rows),
        "rescaling_applied_only_to_private_h5_stages_not_purchased": True,
        "no_h5_read": not bool(requested_stages),
        "purchased_scan_costs_do_not_include_live_h5_absence_recheck": True,
        "private_stage_rows_decoded_for_selected_dates": private_decoded,
        "no_raw_ohlcva_in_safe_summary": True,
        "no_source_market_truth_certification": True,
        "no_source_market_writes": True,
        "no_production_query_switch": True,
        "no_active_pointer_read_or_change": True,
        "no_automatic_gaps_fill": True,
        "private_overlay_source_rows_budget": max_overlay_source_rows,
        "local_cache_used": False,
    })
    return {"bars": rows, "safe_summary": summary}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--version-sha256", required=True,
                    help="EXPLICIT prepared private version SHA, never active pointer")
    ap.add_argument("--max-candidate-rows", type=int, default=30000000)
    ap.add_argument("--max-result-bars", type=int, default=25000)
    ap.add_argument("--max-overlay-source-rows", type=int, default=30000)
    ap.add_argument("--show-first-bars", type=int, default=0,
                    help="Only local terminal: show up to 10 licensed bars")
    ap.add_argument("--out", type=Path, required=True,
                    help="New SAFE report JSON under module reports/")
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        if not 0 <= args.show_first_bars <= 10:
            raise ValueError("--show-first-bars must be 0..10")
        out, scratch = purchased.core.resolve_module_artifact_paths(args.out)
        root, _, _ = purchased.core.resolve_safe_paths(
            args.root, out, scratch)
        if (out.suffix.lower() != ".json" or out.exists()
                or not out.is_relative_to(
                    (HERE.parent / "reports").resolve())):
            raise ValueError("Use a NEW SAFE JSON inside module reports/")
        result = query_private_day_overlay(
            root, args.symbol, args.from_date, args.to_date,
            args.version_sha256, args.max_candidate_rows,
            args.max_result_bars, args.max_overlay_source_rows)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as stream:
            json.dump(result["safe_summary"], stream,
                      ensure_ascii=False, indent=2)
            stream.write("\n")
        print("Saved research-only private overlay SAFE summary:", out)
        print("Bars:", len(result["bars"]),
              "private:", result["safe_summary"]["private_overlay_bars_returned"])
        if args.show_first_bars:
            print("LOCAL LICENSED OHLCVA - never paste into GitHub or shared reports")
            for bar in result["bars"][:args.show_first_bars]:
                print(json.dumps(bar, ensure_ascii=False))
    except (ValueError, OSError, TypeError, KeyError,
            OverflowError, ModuleNotFoundError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
