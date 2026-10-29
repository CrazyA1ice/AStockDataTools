#!/usr/bin/env python3
"""Explicit, bounded, read-only MULTI-STOCK query over a prepared day overlay.

One complete private-version verification and one live H5/Parquet whole-day
absence audit per REQUEST BATCH, not per stock. Purchased Parquet remains the
first and only baseline for overlapping dates. All licensed OHLCVA remains in
local memory, and the CLI writes only safe aggregate/provenance JSON.

This does NOT activate a private pointer or change production query routing.
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


def import_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


single = import_tool("private_overlay_batch_single_query",
                     "query-parquet-primary-day-overlay-readonly.py")
FORMAT = "AStockDataTools private day overlay multi-symbol safe query summary v1"
MAX_SYMBOLS = 10


def selected_private_rows(stages, symbols):
    """Decode each selected staged date ONCE and route validated rows by stock.

    The full immutable version was checked by single.verified_version()
    before this function. Each selected Parquet is hashed again AFTER decode
    to detect mutation during the query.
    """
    import pyarrow.parquet as pq

    requested = set(symbols)
    grouped = {s: [] for s in symbols}
    for stage in stages:
        stage_dir = single.versioner.safe_stage_path(
            single.versioner.MODULE / stage["stage_dir"])
        file = stage_dir / "day.parquet"
        table = pq.read_table(
            file, columns=list(single.versioner.stage_tool.SCHEMA_FIELDS))
        if table.num_rows != stage["rows"]:
            raise ValueError("Private stage count changed during batched read")
        day = date.fromisoformat(stage["day"])
        ts = int(datetime(day.year, day.month, day.day,
                          tzinfo=single.versioner.stage_tool.core.UTC8).timestamp()*1000)
        seen = set()
        for row in table.to_pylist():
            sym = single.versioner.stage_tool.core.symbol_id(row["symbol"])
            if (sym is None or
                    not single.versioner.stage_tool.core.is_a_share_candidate(
                        sym, day.year) or
                    row["source"] != "hikyuu_h5_tail_candidate" or
                    row["ts"] != ts or sym in seen):
                raise ValueError("Private stage day/stock/source key changed")
            seen.add(sym)
            if sym not in requested:
                continue
            values = tuple(float(row[k]) for k in single.FIELDS)
            if (not all(math.isfinite(v) for v in values)
                    or min(values[:4]) <= 0
                    or values[1] + 1e-8 < max(values[0],values[2],values[3])
                    or values[2] - 1e-8 > min(values[0],values[1],values[3])
                    or values[4] < 0 or values[5] < 0):
                raise ValueError("Invalid selected private OHLCVA")
            grouped[sym].append({
                "symbol": sym, "period": "day",
                "trading_date": day.isoformat(),
                "source_timestamp_ms": ts,
                "source_beijing_time": datetime.fromtimestamp(
                    ts/1000,tz=single.versioner.stage_tool.core.UTC8
                    ).strftime("%Y-%m-%d %H:%M"),
                "normalized_query_label": day.isoformat(),
                "source_file_relative_path": stage["stage_dir"]+"/day.parquet",
                "source_row_group": None,
                "value_source": "private_hikyuu_h5_gap_candidate",
                **dict(zip(single.FIELDS,values)),
            })
        if single.versioner.stage_tool.file_digest(file) != stage["parquet_sha256"]:
            raise ValueError("Private stage file bytes changed during batched read")
    return grouped


def query_private_day_overlay_batch(
        root, symbols, first, last, version_sha256,
        max_candidate_rows_per_symbol=300000,
        max_total_candidate_rows=3000000,
        max_result_bars_per_symbol=500,
        max_total_result_bars=5000,
        max_overlay_source_rows=30000):
    """Local in-memory multi-symbol daily query; explicit immutable version only.

    Per-symbol Parquet read budgets and an aggregate source-row budget are
    enforced. An invalid/stale source aborts the ENTIRE batch; no partial safe
    result is returned or persisted. Use only in bounded 1..31 day windows.
    """
    if (type(symbols) not in (tuple,list)
            or not 1 <= len(symbols) <= MAX_SYMBOLS):
        raise ValueError("Provide 1..10 explicit A-share symbols")
    if (type(max_total_candidate_rows) is not int
            or not 1 <= max_total_candidate_rows <= 100000000
            or type(max_total_result_bars) is not int
            or not 1 <= max_total_result_bars <= 100000):
        raise ValueError("Invalid total source-row/result-row budgets")
    checked = [
        single.purchased.request_dates(
            name, "day", first, last,
            max_candidate_rows_per_symbol, max_result_bars_per_symbol)
        for name in symbols
    ]
    canon = [row[0] for row in checked]
    if len(set(canon)) != len(canon):
        raise ValueError("Duplicate symbol in private batch")
    start, end = checked[0][1:]
    if start.year != end.year:
        raise ValueError("Batch private day queries must stay within one year")
    if any(row[1:] != (start,end) for row in checked[1:]):
        raise ValueError("All batch symbols must share the same date window")
    root = Path(root).resolve()
    started = time.perf_counter()
    record, evidence, stages = single.verified_version(
        version_sha256, max_overlay_source_rows)
    verification_done = time.perf_counter()
    selected = [
        item for item in stages
        if start <= date.fromisoformat(item["day"]) <= end
    ]
    before = None
    audit = None
    if selected:
        years = {date.fromisoformat(item["day"]).year for item in selected}
        if len(years) != 1:
            raise ValueError("Multi-year private day audit is prohibited")
        year = next(iter(years))
        before = single.versioner.stage_tool.source_file_states(root, year)
        scratch = (single.versioner.MODULE /
                   "work" / "overlay_batch_live_recheck")
        scratch.mkdir(parents=True,exist_ok=True)
        audit = single.versioner.stage_tool.verify_live_absence_dates(
            root,scratch,{
                item["day"]: evidence["expected"][item["day"]]
                for item in selected})
    audit_done = time.perf_counter()

    # Source-budgeted purchased queries. The exact same source priority and
    # OHLCVA geometry checks as the established single-stock query are reused.
    purchased_by_symbol = {}
    scanned = 0
    purchased_total = 0
    for sym in canon:
        remaining = max_total_candidate_rows-scanned
        if remaining <= 0:
            raise ValueError("Batch total purchased Parquet row budget exhausted")
        base = single.purchased.query_bars(
            root,sym,"day",start.isoformat(),end.isoformat(),
            max_candidate_rows=min(max_candidate_rows_per_symbol,remaining),
            max_result_bars=max_result_bars_per_symbol,
            local_cache=False)
        scanned += base["safe_summary"]["source_rows_scanned"]
        if scanned > max_total_candidate_rows:
            raise ValueError("Batch purchased source-row budget exceeded")
        bought = [
            {**b,"value_source":"purchased_parquet"} for b in base["bars"]
        ]
        purchased_total += len(bought)
        purchased_by_symbol[sym] = bought
    purchase_done = time.perf_counter()
    private_by_symbol = selected_private_rows(selected,canon)
    decode_done = time.perf_counter()

    output = {}
    safe_counts = {}
    total_private = 0
    total_returned = 0
    for sym in canon:
        base = purchased_by_symbol[sym]
        supplement = private_by_symbol[sym]
        baseline_dates = {b["trading_date"] for b in base}
        if any(b["trading_date"] in baseline_dates for b in supplement):
            raise ValueError("Purchased/private date overlap in batch")
        if len(base)+len(supplement) > max_result_bars_per_symbol:
            raise ValueError("Combined per-symbol result budget exceeded")
        combined = sorted(
            base+supplement, key=lambda b:(
                b["trading_date"], b["source_timestamp_ms"]))
        total_private += len(supplement)
        total_returned += len(combined)
        if total_returned > max_total_result_bars:
            raise ValueError("Batch total returned bars budget exceeded")
        output[sym] = combined
        safe_counts[sym] = {
            "purchased_bars":len(base),
            "private_bars":len(supplement),
            "returned_bars":len(combined)}
    if before is not None and (
            before != single.versioner.stage_tool.source_file_states(root,year)):
        raise ValueError("Market sources changed during batched query")
    summary = {
        "format":FORMAT,
        "period":"day",
        "from_date":start.isoformat(),"to_date":end.isoformat(),
        "symbols":canon,
        "symbol_count":len(canon),
        "per_symbol_counts":safe_counts,
        "matching_bar_count":total_returned,
        "purchased_parquet_bars_returned":purchased_total,
        "private_overlay_bars_returned":total_private,
        "private_version_sha256":record["version_sha256"],
        "private_overlay_stages_sha_and_keys_verified":True,
        "private_overlay_dates_live_rechecked":[s["day"] for s in selected],
        "live_absence_recheck_scan_count":1 if selected else 0,
        "live_absence_recheck_h5_in_window_rows":(
            audit.get("h5_rows",0) if audit else 0),
        "live_absence_recheck_purchased_in_window_rows":(
            audit.get("pq_rows",0) if audit else 0),
        "private_stage_verification_row_count":record["rows_in_overlay"],
        "private_stage_rows_decoded_for_selected_dates":sum(
            item["rows"] for item in selected),
        "purchased_source_rows_scanned_across_symbols":scanned,
        "query_elapsed_seconds_this_invocation":round(
            time.perf_counter()-started,6),
        "version_verification_elapsed_seconds":round(
            verification_done-started,6),
        "live_recheck_elapsed_seconds":round(audit_done-verification_done,6),
        "purchased_stock_queries_elapsed_seconds":round(
            purchase_done-audit_done,6),
        "selected_private_stage_decode_elapsed_seconds":round(
            decode_done-purchase_done,6),
        "purchased_parquet_priority":True,
        "only_prepared_version_explicit_opt_in":True,
        "h5_daily_units_are_unverified_candidate":True,
        "no_raw_ohlcva_in_safe_summary":True,
        "no_source_market_writes":True,
        "no_production_query_switch":True,
        "no_active_pointer_read_or_change":True,
        "no_automatic_gap_fills":True,
        "local_cache_used":False,
    }
    return {"bars_by_symbol":output,"safe_summary":summary}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--symbols",nargs="+",required=True)
    parser.add_argument("--from-date",required=True)
    parser.add_argument("--to-date",required=True)
    parser.add_argument("--version-sha256",required=True)
    parser.add_argument("--max-candidate-rows-per-symbol",type=int,default=300000)
    parser.add_argument("--max-total-candidate-rows",type=int,default=3000000)
    parser.add_argument("--max-result-bars-per-symbol",type=int,default=500)
    parser.add_argument("--max-total-result-bars",type=int,default=5000)
    parser.add_argument("--max-overlay-source-rows",type=int,default=30000)
    parser.add_argument("--out",type=Path,required=True,
                        help="NEW safe JSON under module reports/")
    parser.add_argument("--read-only",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        out,scratch=single.purchased.core.resolve_module_artifact_paths(args.out)
        root,_,_=single.purchased.core.resolve_safe_paths(
            args.root,out,scratch)
        reports=(HERE.parent/"reports").resolve()
        if (out.suffix.lower()!=".json" or out.exists()
                or out.is_symlink() or not out.is_relative_to(reports)):
            raise ValueError("Write a NEW safe report only under module reports/")
        result=query_private_day_overlay_batch(
            root,args.symbols,args.from_date,args.to_date,
            args.version_sha256,args.max_candidate_rows_per_symbol,
            args.max_total_candidate_rows,args.max_result_bars_per_symbol,
            args.max_total_result_bars,args.max_overlay_source_rows)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as stream:
            json.dump(result["safe_summary"],stream,
                      ensure_ascii=False,indent=2)
            stream.write("\n")
        print("SAFE multi-symbol query summary saved:",out)
        print("Stocks:",len(result["bars_by_symbol"]),
              "Total bars:",result["safe_summary"]["matching_bar_count"],
              "Live full-day scans:",
              result["safe_summary"]["live_absence_recheck_scan_count"])
    except (ValueError,OSError,TypeError,KeyError,
            OverflowError,ModuleNotFoundError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
