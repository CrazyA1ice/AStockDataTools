#!/usr/bin/env python3
"""只读交叉验证：用Hikyuu独立1min文件重组5min K线，并与H5、Parquet的5min比较。

重要：1min来源不保证独立于H5 5min的上游数据；它只是另一周期文件，
可用来检验聚合口径，不能凭相符次数判定数据商绝对正确。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "diagnose_5min_alignment_for_1min_crosscheck", HERE / "diagnose-5min-alignment.py")
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)
core = diagnostic.core

PRICE_FIELDS = ("open", "high", "low", "close")
DEFAULT_TICKERS = ("SH600000", "SZ000636", "SH603181", "SZ300747", "BJ920680")
CONVENTIONS = ("minute_end_label", "minute_start_label")


def one_minute_times(bar_end: int, convention: str) -> tuple[int, ...]:
    """5 raw minute labels: (end-4 ... end) or (end-5 ... end-1).

    The first convention treats one-minute bars as end-stamped, the second
    treats them as start-stamped. Both are hypotheses, not silently normalized.
    """
    if convention not in CONVENTIONS:
        raise ValueError("Unknown one-minute timestamp convention")
    end = datetime.strptime(str(bar_end), "%Y%m%d%H%M")
    offsets = range(4, -1, -1) if convention == CONVENTIONS[0] else range(5, 0, -1)
    return tuple(int((end - timedelta(minutes=i)).strftime("%Y%m%d%H%M")) for i in offsets)


def aggregate_minute_window(minute_rows: dict, symbol: str, bar_end: int, convention: str):
    keys = [(symbol, t) for t in one_minute_times(bar_end, convention)]
    if any(key not in minute_rows for key in keys):
        return None
    values = [minute_rows[k] for k in keys]
    return (
        values[0][0], max(x[1] for x in values), min(x[2] for x in values),
        values[-1][3], sum(x[4] for x in values), sum(x[5] for x in values)
    )


def load_h5_minute_day(root: Path, symbols: tuple[str, ...], day: date):
    import h5py

    begin, end, _, _ = core.parse_day_range(day.year, day.isoformat(), day.isoformat())
    records, coverage = {}, {}
    for symbol in symbols:
        filename = root / "HikyuuData" / (symbol[:2].lower() + "_1min.h5")
        status = {"file_present": filename.is_file(), "dataset_present": False,
                  "one_minute_rows": 0, "duplicate_minute_keys": 0, "availability": "missing_file"}
        coverage[symbol] = status
        if not filename.is_file():
            continue
        with h5py.File(filename, "r") as file:
            dataset = file.get("data/" + symbol)
            if not isinstance(dataset, h5py.Dataset):
                status["availability"] = "missing_dataset"
                continue
            status["dataset_present"] = True
            if not set(core.H5_FIELDS).issubset(dataset.dtype.names or ()):
                status["availability"] = "unsupported_schema"
                continue
            lo, hi = core.h5_key_slice(dataset, begin, end)
            for row in dataset[lo:hi]:
                t = int(row["datetime"])
                key = (symbol, t)
                if key in records:
                    status["duplicate_minute_keys"] += 1
                    continue
                records[key] = (
                    float(row["openPrice"]) / 1000,
                    float(row["highPrice"]) / 1000,
                    float(row["lowPrice"]) / 1000,
                    float(row["closePrice"]) / 1000,
                    float(row["transCount"]),
                    float(row["transAmount"]) * 1000
                )
                status["one_minute_rows"] += 1
            status["availability"] = ("has_records" if status["one_minute_rows"] > 0
                                      else "no_records_on_date")
    return records, coverage


def _safe_ratio(numerator: float, denominator: float):
    return round(numerator / denominator, 7) if denominator != 0 else None


def compare_to_reaggregation(minute_rows: dict, five_minute_bars: dict, symbol: str,
                             convention: str, *, minute_volume_factor: int = 1):
    """Only compare bars with *exactly five* observed minute labels.

    five_minute_bars keyed by (symbol, bar_end) with (O,H,L,C,V,A).
    Values are used only transiently. Returned summary has no raw OHLCV.
    """
    # The factor is an explicit unverified H5-minute-to-purchased-PQ
    # comparison hypothesis. Never mutate the original minute rows.
    if type(minute_volume_factor) is not int or minute_volume_factor not in (1, 100):
        raise ValueError("Only predeclared 1 or 100 diagnostic volume factors are allowed")
    state = Counter()
    ratios = {"volume": [], "amount": []}
    missing = []
    for (ticker, bar_end), bar in five_minute_bars.items():
        if ticker != symbol:
            continue
        state["five_minute_bars"] += 1
        aggregate = aggregate_minute_window(minute_rows, symbol, bar_end, convention)
        if aggregate is None:
            state["incomplete_minute_windows"] += 1
            if len(missing) < 8:
                missing.append(str(bar_end))
            continue
        state["complete_minute_windows"] += 1
        prices_ok = True
        for i, field in enumerate(PRICE_FIELDS):
            if diagnostic.close_enough(bar[i], aggregate[i], "price"):
                state[field + "_agree"] += 1
            else:
                prices_ok = False
        if prices_ok:
            state["all_ohlc_agree"] += 1
        for index, field in ((4, "volume"), (5, "amount")):
            candidate_value = (
                aggregate[index] * minute_volume_factor if field == "volume"
                else aggregate[index]
            )
            if diagnostic.close_enough(bar[index], candidate_value, field):
                state[field + "_agree"] += 1
            if candidate_value != 0:
                ratio = bar[index] / candidate_value
                if math.isfinite(ratio):
                    ratios[field].append(ratio)
            else:
                state["zero_minute_" + field + "_sum"] += 1
    counters = ("five_minute_bars", "complete_minute_windows", "incomplete_minute_windows",
                "all_ohlc_agree", "volume_agree", "amount_agree",
                "zero_minute_volume_sum", "zero_minute_amount_sum")
    result = {key: int(state[key]) for key in counters}
    result["h5_minute_volume_factor_diagnostic_only"] = minute_volume_factor
    result["volume_factor_certified"] = False
    result["raw_market_values_modified"] = False
    result["price_field_agree"] = {field: int(state[field + "_agree"]) for field in PRICE_FIELDS}
    result["bar_over_one_minute_sum_volume_ratio"] = diagnostic.summarize_values(ratios["volume"])
    result["bar_over_one_minute_sum_amount_ratio"] = diagnostic.summarize_values(ratios["amount"])
    result["incomplete_window_end_labels_examples"] = missing
    return result


def summarize_five_minute_sources(h5_rows: dict, parquet_start_rows: dict, symbol: str):
    """Show matched-time total V/A ratios, without disclosing source totals."""
    paired = []
    for (ticker, start), p in parquet_start_rows.items():
        if ticker != symbol:
            continue
        end = diagnostic.shift_bar_stamp(start, 5)
        h = h5_rows.get((symbol, end))
        if h is not None:
            paired.append((p, h))
    n = len(paired)
    return {
        "matched_five_minute_bars": n,
        "parquet_over_h5_total_volume_ratio_on_matched_bars": _safe_ratio(
            sum(p[4] for p, h in paired), sum(h[4] for p, h in paired)) if n else None,
        "parquet_over_h5_total_amount_ratio_on_matched_bars": _safe_ratio(
            sum(p[5] for p, h in paired), sum(h[5] for p, h in paired)) if n else None
    }


def build_crosscheck(h5_five: dict, parquet_start: dict, h5_one: dict,
                     coverage: dict, symbols: tuple[str, ...]) -> dict:
    parquet_end = {(symbol, diagnostic.shift_bar_stamp(t, 5)): values
                   for (symbol, t), values in parquet_start.items()}
    result = {}
    for symbol in symbols:
        status = coverage[symbol]
        report = {
            "one_minute_source": dict(status),
            "five_minute_day_total_comparison": summarize_five_minute_sources(
                h5_five, parquet_start, symbol),
            "one_minute_reaggregation": {}
        }
        if status["availability"] != "has_records":
            report["validation_status"] = "not_verifiable_no_one_minute_data"
            result[symbol] = report
            continue
        if status["duplicate_minute_keys"]:
            report["validation_status"] = "not_verifiable_duplicate_one_minute_keys"
            result[symbol] = report
            continue
        report["validation_status"] = "conditional_evidence"
        for convention in CONVENTIONS:
            report["one_minute_reaggregation"][convention] = {
                "H5_5min": compare_to_reaggregation(h5_one, h5_five, symbol, convention),
                "Parquet_5min": compare_to_reaggregation(h5_one, parquet_end, symbol, convention),
                "Parquet_5min_H5_1min_volume_x100_candidate": compare_to_reaggregation(
                    h5_one, parquet_end, symbol, convention, minute_volume_factor=100)
            }
        if all(v["H5_5min"]["complete_minute_windows"] == 0 and
               v["Parquet_5min"]["complete_minute_windows"] == 0
               for v in report["one_minute_reaggregation"].values()):
            report["validation_status"] = "not_verifiable_no_complete_one_minute_windows"
        result[symbol] = report
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True, help="Trading day YYYY-MM-DD")
    ap.add_argument("--symbols", nargs="+", default=list(DEFAULT_TICKERS))
    ap.add_argument("--out", type=Path, default=Path("reports") / "5min-h5-1min-crosscheck.json")
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        symbols = tuple(dict.fromkeys(symbol.upper() for symbol in args.symbols))
        if not 1 <= len(symbols) <= 20 or any(core.symbol_id(s) != s for s in symbols):
            raise ValueError("Provide 1..20 SH/SZ/BJ six-digit symbols")
        out, scratch = core.resolve_module_artifact_paths(args.out, None)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if out.exists():
            raise ValueError(f"Output already exists; choose a new filename: {out}")
        h5_five, h5_five_coverage = diagnostic.load_h5(root, symbols, day)
        print(f"5min H5 selected bars: {len(h5_five)}", flush=True)
        parquet_five, pq_info = diagnostic.load_parquet(root, symbols, day, True)
        print(f"5min Parquet selected bars: {len(parquet_five)}", flush=True)
        h5_one, one_coverage = load_h5_minute_day(root, symbols, day)
        print(f"1min H5 selected bars: {len(h5_one)}", flush=True)
        report = {
            "format": "AStockDataTools independent H5 1min to 5min crosscheck v1",
            "date": day.isoformat(), "symbols": list(symbols),
            "five_minute_h5_coverage": h5_five_coverage,
            "five_minute_parquet_scan": pq_info,
            "symbols_crosscheck": build_crosscheck(
                h5_five, parquet_five, h5_one, one_coverage, symbols),
            "source_files_modified": False,
            "source_units_certified": False,
            "h5_1min_volume_x100_candidate_certified": False,
            "parquet_5min_candidate_comparison_is_parallel_to_unchanged_raw_baseline": True,
            "safe_to_automatically_union": False,
            "minute_window_hypotheses": {
                "minute_end_label": "end-4min...end; 5 exact 1min bars",
                "minute_start_label": "end-5min...end-1min; 5 exact 1min bars"
            },
            "interpretation_limitations": [
                "1min Hikyuu is a distinct period file, not necessarily independently sourced trades.",
                "Only five observed 1min bars form a complete 5min window; partial windows are excluded.",
                "5min Parquet source timestamps are provisionally start-labeled and shifted +5min.",
                "Volume/amount use unverified H5 units; agreement is not a final source certification.",
                "The additional Parquet_5min_H5_1min_volume_x100_candidate multiplies only the in-memory H5 1minute aggregate volume by 100; the original H5/PQ comparison stays unchanged.",
                "A missing or incomplete H5 one-minute window is never counted as a mismatch in either comparison.",
                "Total ratios compare only 5min keys available in both sources, not missing-source keys.",
                "No OHLCV source values are written; output is aggregate counts, ratios, availability and bar timestamps."
            ]
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = out.with_name(out.name + ".tmp")
        staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        staging.replace(out)
        print("Saved", out, "(original market files unchanged)", flush=True)
    except (ValueError, OSError, OverflowError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
