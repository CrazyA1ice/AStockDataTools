#!/usr/bin/env python3
"""Read-only, bounded Hikyuu daily HDF5 layout survey (NO mirror creation).

Returns only file/schema/count/date/provenance metadata. No OHLCVA values,
licensed raw bars, or H5 table contents are written to JSON or printed.
A structural candidate is NOT certified Hikyuu driver compatibility.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent.resolve()
REPORTS = MODULE / "reports"
FORMAT = "AStockDataTools Hikyuu native daily H5 structural read-only survey v1"
EXPECTED_FIELDS = ("datetime", "openPrice", "highPrice", "lowPrice",
                   "closePrice", "transAmount", "transCount")
FIELD_TYPES = {
    "datetime": ("u", 8),
    "openPrice": ("u", 4), "highPrice": ("u", 4),
    "lowPrice": ("u", 4), "closePrice": ("u", 4),
    "transAmount": ("u", 8), "transCount": ("u", 8),
}
MAX_SYMBOLS = 10


def import_core():
    spec = importlib.util.spec_from_file_location(
        "hikyuu_daily_contract_probe_core",
        HERE / "reconcile-local-a-share-h5-parquet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = import_core()


def _dates(first, last):
    start, end = date.fromisoformat(str(first)), date.fromisoformat(str(last))
    if start > end or start.year != end.year or (end-start).days >= 31:
        raise ValueError("Daily H5 survey requires a 1..31 day single-year window")
    return start, end


def _market_sources(root, symbols):
    root = Path(root).resolve()
    folder = root / "HikyuuData"
    if not root.is_dir() or not folder.is_dir() or folder.is_symlink():
        raise ValueError("Native HikyuuData source directory must exist and not be a link")
    source = {}
    for symbol in symbols:
        market = symbol[:2].lower()
        path = folder / (market + "_day.h5")
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(folder.resolve())):
            raise ValueError("Missing/unsafe native daily H5 source for " + market.upper())
        source[market] = path
    return source


def _file_state(file):
    stat = file.stat()
    return {"relative_path": "HikyuuData/" + file.name,
            "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _schema(ds):
    if ds.ndim != 1 or ds.dtype.names is None:
        return {"one_dimensional_compound_dataset": False,
                "expected_field_set": False,
                "field_order_matches_legacy_h5record": False,
                "integer_width_sign_compatible_with_h5record": False,
                "field_layout": [],
                "dtype_itemsize_bytes": int(ds.dtype.itemsize)}
    fields = []
    type_match = True
    for name in ds.dtype.names:
        field, offset = ds.dtype.fields[name][:2]
        fields.append({
            "field": name,
            "kind": field.kind,
            "itemsize_bytes": int(field.itemsize),
            "offset_bytes": int(offset),
        })
        if name in FIELD_TYPES and (field.kind, field.itemsize) != FIELD_TYPES[name]:
            type_match = False
    return {
        "one_dimensional_compound_dataset": True,
        "expected_field_set": set(ds.dtype.names) == set(EXPECTED_FIELDS),
        "field_order_matches_legacy_h5record":
            ds.dtype.names == EXPECTED_FIELDS,
        "integer_width_sign_compatible_with_h5record":
            type_match and set(ds.dtype.names) == set(EXPECTED_FIELDS),
        "field_layout": fields,
        "dtype_itemsize_bytes": int(ds.dtype.itemsize),
    }


def _scan_dataset(ds, start, end):
    if ds.dtype.names is None or "datetime" not in ds.dtype.names or ds.ndim != 1:
        return {"matched_rows_in_window": None,
                "window_timestamp_edges_have_valid_day_labels": False,
                "full_history_sortedness_verified": False}
    lower = int(start.strftime("%Y%m%d")) * 10000
    upper = int((end + timedelta(days=1)).strftime("%Y%m%d")) * 10000
    left, right = core.h5_key_slice(ds, lower, upper)
    count = int(right-left)
    edge_valid = True
    for index in (left,right-1):
        if 0 <= index < len(ds) and left <= index < right:
            key = int(ds[index]["datetime"])
            if key % 10000 or not lower <= key < upper:
                edge_valid = False
    return {
        "matched_rows_in_window": count,
        "window_timestamp_edges_have_valid_day_labels": edge_valid,
        "full_history_sortedness_verified": False,
    }


def probe_native_day_h5(root, symbols, first, last):
    """Read native H5 metadata and at most O(log N) boundary records per symbol."""
    import h5py

    if type(symbols) not in (list, tuple) or not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise ValueError("Supply 1..10 specific canonical A-share symbols")
    if any(type(s) is not str or core.symbol_id(s) != s
           or s != s.upper() or s.strip() != s for s in symbols):
        raise ValueError("Only canonical uppercase symbols are accepted")
    if len(set(symbols)) != len(symbols):
        raise ValueError("Duplicate symbol in native daily survey")
    start, end = _dates(first, last)
    if any(not core.is_a_share_candidate(s, start.year) for s in symbols):
        raise ValueError("Only candidate A-share symbols supported")
    paths = _market_sources(root, symbols)
    before = {venue: _file_state(path) for venue, path in paths.items()}
    by_symbol = {}
    for venue, path in sorted(paths.items()):
        with h5py.File(path, "r") as h5:
            group = h5.get("data")
            if not isinstance(group, h5py.Group):
                raise ValueError("H5 /data group absent: " + path.name)
            for symbol in (s for s in symbols if s[:2].lower() == venue):
                if symbol not in group:
                    by_symbol[symbol] = {
                        "dataset_present": False,
                        "structural_h5record_candidate": False,
                        "hikyuu_native_driver_verified": False}
                    continue
                ds = group[symbol]
                if not isinstance(ds, h5py.Dataset):
                    raise ValueError("Expected H5 /data stock table is not dataset")
                layout = _schema(ds)
                attrs = ds.attrs
                marker = attrs.get("CLASS")
                if isinstance(marker, bytes):
                    marker = marker.decode("ascii", errors="replace")
                table_marker = marker == "TABLE"
                sampled = _scan_dataset(ds, start, end)
                valid_structure = (
                    layout["one_dimensional_compound_dataset"]
                    and layout["expected_field_set"]
                    and layout["integer_width_sign_compatible_with_h5record"]
                    and sampled["window_timestamp_edges_have_valid_day_labels"])
                by_symbol[symbol] = {
                    "dataset_present": True,
                    "rows_in_dataset": int(len(ds)),
                    "pytables_table_class_marker_present": table_marker,
                    "dataset_class_attribute_keys_only": sorted(
                        str(a) for a in attrs.keys()),
                    "compression_filter": ds.compression,
                    "chunked": ds.chunks is not None,
                    **layout, **sampled,
                    "structural_h5record_candidate": bool(valid_structure),
                    "hikyuu_native_driver_verified": False,
                }
    after = {venue: _file_state(path) for venue, path in paths.items()}
    if before != after:
        raise ValueError("Original H5 source changed during structural survey")
    return {
        "format": FORMAT,
        "period": "day",
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "symbols": list(symbols),
        "symbol_count": len(symbols),
        "source_file_stat_provenance": [
            before[venue] for venue in sorted(before)],
        "per_symbol_native_h5_contract": {
            sym: by_symbol[sym] for sym in symbols},
        "requested_source_structure_candidates": all(
            v["structural_h5record_candidate"] for v in by_symbol.values()),
        "hikyuu_native_driver_load_tested": False,
        "ready_for_full_h5_mirror_write": False,
        "h5_daily_units_supplier_certified": False,
        "full_history_sortedness_verified": False,
        "no_raw_ohlcva_in_safe_summary": True,
        "source_h5_files_modified": False,
        "purchased_parquet_files_read": False,
        "market_source_files_modified": False,
        "mirror_files_created": False,
        "production_query_route_modified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--symbols",nargs="+",required=True)
    parser.add_argument("--from-date",required=True)
    parser.add_argument("--to-date",required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only",action="store_true",required=True)
    args = parser.parse_args(argv)
    try:
        if REPORTS.is_symlink():
            raise ValueError("Reports path must not be symlinked")
        destination = (MODULE / args.out).resolve() if not args.out.is_absolute() else args.out.resolve()
        if (destination.suffix.lower() != ".json"
                or destination.parent != REPORTS.resolve()
                or destination.is_symlink() or destination.exists()):
            raise ValueError("Use a NEW safe JSON directly inside module reports/")
        result = probe_native_day_h5(
            args.root,args.symbols,args.from_date,args.to_date)
        REPORTS.mkdir(parents=True,exist_ok=True)
        with destination.open("x",encoding="utf-8") as fp:
            json.dump(result,fp,ensure_ascii=False,indent=2)
            fp.write("\n")
        print("SAFE native Hikyuu H5 structural survey:",destination)
        print("Subjects:",len(args.symbols),"candidate layouts:",
              result["requested_source_structure_candidates"])
        print("NOT an actual Hikyuu driver test; no mirror generated.")
    except (ValueError,OSError,TypeError,KeyError,ModuleNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
