#!/usr/bin/env python3
"""只读并集预检：按证券+五分钟终点时间键，生成双源差集与冲突隔离计划。

绝不导出原始OHLCV、生成合并数据库、决定冲突源优先级或修改D:\stock。
这是按日、少量证券的安全预检原型；并非全历史并集转换器。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "diagnose_5min_for_union_preflight", HERE / "diagnose-5min-alignment.py")
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)
core = diagnose.core

DEFAULT_SYMBOLS = ("SH600000", "SZ000636", "SH603181", "SZ300747", "BJ920680")
CATEGORIES = ("h5_only", "parquet_only", "identical_values",
              "within_unverified_tolerance", "value_conflict")
FIELDS = ("open", "high", "low", "close", "volume", "amount")
MAX_SAMPLES = 12


def h5_dataset_inventory(root: Path, symbols: tuple[str, ...]) -> dict:
    """Differentiate absent per-stock dataset from an unreadable/missing market file."""
    import h5py
    result = {}
    for ticker in symbols:
        filename = root / "HikyuuData" / (ticker[:2].lower() + "_5min.h5")
        if not filename.is_file():
            result[ticker] = "missing_market_file"
            continue
        with h5py.File(filename, "r") as fh:
            dataset = fh.get("data/" + ticker)
            result[ticker] = ("dataset_present" if isinstance(dataset, h5py.Dataset)
                              else "missing_symbol_dataset")
    return result


def nonfinite_or_bad_geometry(values):
    if len(values) != 6:
        return True
    import math
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return True
    o, high, low, close, volume, amount = values
    return (high + 0.005 < max(o, close)
            or low - 0.005 > min(o, close)
            or high + 0.005 < low
            or volume < 0 or amount < 0)


def classify_pairs(h5_rows: dict, parquet_starts: dict,
                   symbols: tuple[str, ...]):
    """Pure reconciliation core. Only aggregate counters + capped key examples leave memory."""
    parquet_rows = {
        (ticker, diagnose.shift_bar_stamp(start, 5)): values
        for (ticker, start), values in parquet_starts.items()
    }
    symbol_set = set(symbols)
    if any(ticker not in symbol_set for ticker, stamp in
           set(h5_rows) | set(parquet_rows)):
        raise ValueError("Unexpected symbol in source data")
    result, overall = {}, Counter()
    for ticker in symbols:
        one_h5 = {stamp: vals for (s, stamp), vals in h5_rows.items() if s == ticker}
        one_pq = {stamp: vals for (s, stamp), vals in parquet_rows.items() if s == ticker}
        counts, field_differences, examples = Counter(), Counter(), {
            category: [] for category in CATEGORIES
        }
        bad_geometry = {
            "h5": sum(nonfinite_or_bad_geometry(v) for v in one_h5.values()),
            "parquet": sum(nonfinite_or_bad_geometry(v) for v in one_pq.values())
        }
        for stamp in sorted(one_h5.keys() | one_pq.keys()):
            hv, pv = one_h5.get(stamp), one_pq.get(stamp)
            fields = []
            if hv is None:
                category = "parquet_only"
            elif pv is None:
                category = "h5_only"
            elif hv == pv:
                category = "identical_values"
            else:
                for i, name in enumerate(FIELDS):
                    typ = "price" if i < 4 else name
                    if not diagnose.close_enough(hv[i], pv[i], typ):
                        fields.append(name)
                category = "value_conflict" if fields else "within_unverified_tolerance"
            counts[category] += 1
            overall[category] += 1
            for field in fields:
                field_differences[field] += 1
            if len(examples[category]) < MAX_SAMPLES:
                example = {"symbol": ticker, "bar_end": str(stamp)}
                if fields:
                    example["differing_fields"] = fields
                examples[category].append(example)
        h5_count, parquet_count = len(one_h5), len(one_pq)
        common = counts["identical_values"] + counts["within_unverified_tolerance"] + counts["value_conflict"]
        assert h5_count + parquet_count - common == sum(counts.values())
        result[ticker] = {
            "h5_keys": h5_count, "parquet_keys": parquet_count,
            "intersection_keys": common,
            "candidate_h5_to_parquet_keys": counts["h5_only"],
            "candidate_parquet_to_h5_keys": counts["parquet_only"],
            "quarantined_overlap_conflicts": counts["value_conflict"],
            "counts": {category: counts[category] for category in CATEGORIES},
            "value_conflict_fields": dict(field_differences),
            "invalid_or_nonfinite_ohlcv_records": bad_geometry,
            "examples": {category: values for category, values in examples.items() if values}
        }
    return result, {category: overall[category] for category in CATEGORIES}


def quality_barriers(h5_status: dict, h5_coverage: dict, parquet_coverage: dict,
                     by_symbol: dict) -> list[str]:
    blockers = [
        "SECURITY_MASTER_NOT_CERTIFIED",
        "FIVE_MINUTE_TIME_LABEL_CONVENTION_UNVERIFIED",
        "VOLUME_AMOUNT_UNITS_AND_RECONCILIATION_TOLERANCES_UNVERIFIED",
        "CONFLICT_RESOLUTION_POLICY_NOT_APPROVED"
    ]
    if not parquet_coverage.get("files"):
        blockers.append("PARQUET_YEAR_FILE_NOT_FOUND")
    for flag in ("duplicate_keys", "nonfinite_rows"):
        if parquet_coverage.get(flag, 0):
            blockers.append("PARQUET_" + flag.upper())
    if parquet_coverage.get("source_rows_in_scanned_groups", 0) == 0 and parquet_coverage.get("files"):
        blockers.append("PARQUET_SCAN_RETURNED_NO_SOURCE_ROWS")
    for symbol, inventory in h5_status.items():
        if inventory == "missing_market_file":
            blockers.append("MISSING_H5_MARKET_FILE")
        if h5_coverage.get(symbol, {}).get("h5_duplicate_keys", 0):
            blockers.append("H5_DUPLICATE_KEYS")
    if any(sum(v["invalid_or_nonfinite_ohlcv_records"].values()) > 0
           for v in by_symbol.values()):
        blockers.append("OHLCV_GEOMETRY_OR_NONFINITE_ANOMALY")
    return sorted(set(blockers))


def build_plan(h5_rows: dict, parquet_rows: dict, symbols: tuple[str, ...],
               h5_status: dict, h5_coverage: dict, pq_coverage: dict,
               day: date):
    per_stock, totals = classify_pairs(h5_rows, parquet_rows, symbols)
    for symbol, entry in per_stock.items():
        entry["h5_dataset_inventory"] = h5_status[symbol]
        entry["h5_file_present"] = bool(h5_coverage.get(symbol, {}).get("h5_file_present"))
        entry["candidate_action"] = (
            "requires_security_master_and_data_quality_review"
            if (entry["candidate_h5_to_parquet_keys"] or entry["candidate_parquet_to_h5_keys"])
            else "no_single_source_additions"
        )
        entry["prohibit_automatic_overwrite"] = True
    barriers = quality_barriers(h5_status, h5_coverage, pq_coverage, per_stock)
    total_h5 = sum(entry["h5_keys"] for entry in per_stock.values())
    total_pq = sum(entry["parquet_keys"] for entry in per_stock.values())
    overlap = sum(entry["intersection_keys"] for entry in per_stock.values())
    assert total_h5 + total_pq - overlap == sum(totals.values())
    return {
        "format": "AStockDataTools H5/Parquet 5min union preflight v1",
        "day": day.isoformat(), "symbols": list(symbols),
        "scope": "selected symbols, single local trading date, five-minute bar-end candidate +5min",
        "keys": {"h5_unique": total_h5, "parquet_unique": total_pq,
                 "intersection_unique": overlap, "union_candidate_unique": sum(totals.values())},
        "totals": totals,
        "by_symbol": per_stock,
        "quality_barriers": barriers,
        "preflight_passed_for_automatic_union": False,
        "raw_source_values_exported": False,
        "original_files_modified": False,
        "output_database_generated": False,
        "interpretation": [
            "Single-source counts are candidate additions only; no OHLCV is exported or written.",
            "Duplicates found during source decoding may have been dropped from the key maps; never apply plans while duplicate/source errors exist.",
            "Comparisons use candidate timestamp adjustment +5min and heuristic price/amount/volume tolerances.",
            "Overlapping value conflicts are quarantined; no source is selected as correct.",
            "Data from absent H5 market files or absent Parquet annual partitions cannot prove true key absence.",
            "Full historical rollout requires a streaming, independently verified key index and source provenance."
        ]
    }




def validated_parquet_locator(index_file, root, symbols, day, universe):
    """Use only complete source-matched index; refuse unindexed abnormal source labels."""
    index_file = Path(index_file).resolve()
    if universe == "a-share-candidate" and any(
            not core.is_a_share_candidate(symbol, day.year) for symbol in symbols):
        raise ValueError("Selected symbols outside the candidate universe of this index")
    spec = importlib.util.spec_from_file_location(
        "parquet_5min_coverage_index", HERE / "index-parquet-5min-coverage.py")
    indexer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(indexer)
    manifest = indexer.validate_existing_index(index_file, root, day.year, universe)
    db = sqlite3.connect(f"file:{index_file.as_posix()}?mode=ro", uri=True)
    try:
        state = dict(db.execute("SELECT key,value FROM meta"))
        for key in ("bad_timestamp", "unexpected_session_stamp", "unrecognized_symbol", "outside_year"):
            if int(state.get(key, "0")):
                raise ValueError(f"Index contains {key} anomalies; unindexed audit required")
        group_ids = indexer.index_matches_and_groups(
            db, symbols, int(day.strftime("%Y%m%d")))
    finally:
        db.close()
    paths = core.year_files(root, "5min", day.year)
    if len(paths) != len(manifest["files"]):
        raise ValueError("Parquet file list differs from validated locator")
    allow = {str(path.resolve()): set(group_ids.get(file_id, ()))
             for file_id, path in enumerate(paths)}
    return allow, {
        "used": True,
        "source_fingerprint": indexer.manifest_signature(manifest),
        "duplicate_regular_session_keys_in_index": int(
            state.get("duplicate_regular_session_keys", "0")),
        "coverage_index_complete": True
    }

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True, help="Local exchange date YYYY-MM-DD")
    ap.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    ap.add_argument("--out", type=Path, default=Path("reports") / "5min-union-preflight.json")
    ap.add_argument("--coverage-index", type=Path, default=None,
                    help="Optional completed work/indexes SQLite index; accelerate day/symbol lookups")
    ap.add_argument("--index-universe", choices=("a-share-candidate","all"),
                    default="a-share-candidate")
    ap.add_argument("--read-only", required=True, action="store_true")
    options = ap.parse_args(argv)
    try:
        day = date.fromisoformat(options.date)
        symbols = tuple(dict.fromkeys(x.upper() for x in options.symbols))
        if not 1 <= len(symbols) <= 20 or any(core.symbol_id(s) != s for s in symbols):
            raise ValueError("Choose 1..20 valid SH/SZ/BJ six-digit symbols")
        out, scratch = core.resolve_module_artifact_paths(options.out, None)
        root, _, _ = core.resolve_safe_paths(options.root, out, scratch)
        if out.exists():
            raise ValueError("Report exists. Use a new --out filename to preserve prior audits")
        h5_presence = h5_dataset_inventory(root, symbols)
        h5, h5_info = diagnose.load_h5(root, symbols, day)
        print(f"5min H5 keys loaded: {len(h5)}", flush=True)
        index_info = {"used": False}
        allow = None
        if options.coverage_index is not None:
            index_file, _ = core.resolve_module_artifact_paths(options.coverage_index, None)
            allow, index_info = validated_parquet_locator(
                index_file, root, symbols, day, options.index_universe)
            print("Using validated Parquet row-group coverage index", flush=True)
        pq, pq_info = diagnose.load_parquet(root, symbols, day, True,
                                           allowed_groups=allow)
        print(f"5min Parquet keys loaded: {len(pq)}", flush=True)
        report = build_plan(h5, pq, symbols, h5_presence, h5_info, pq_info, day)
        report["parquet_scan"] = pq_info
        report["parquet_coverage_index"] = index_info
        if index_info.get("duplicate_regular_session_keys_in_index", 0):
            report["quality_barriers"].append("PARQUET_INDEX_HAS_DUPLICATE_KEYS")
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.name + ".tmp")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(out)
        print("Saved", out, "plan only; source files unchanged", flush=True)
    except (ValueError, OSError, OverflowError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
