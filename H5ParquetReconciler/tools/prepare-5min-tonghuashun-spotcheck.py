#!/usr/bin/env python3
"""Prepare real discrepant 5min K-line points for manual Tonghuashun verification.

The shareable JSON contains ONLY symbol, date, bar interval, differing field
names and source-provenance flags. Optionally print the 2 vendors' OHLCV
side-by-side on the LOCAL terminal (--show-local-values); never persist or
send their proprietary value fields in the JSON. Reads the selected 2026
Parquet rowgroups anew; this is NOT a metadata-only operation or new index.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "local_manual_ths_5min_focus", HERE / "analyze-5min-x100-focused-sessions.py")
focused = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(focused)
diagnose = focused.diagnose
core = focused.core
FIELDS = ("open", "high", "low", "close", "volume", "amount")
PRICE_FIELDS = FIELDS[:4]


def five_minute_interval(bar_end):
    end = datetime.strptime(str(bar_end), "%Y%m%d%H%M")
    start = end - timedelta(minutes=5)
    if start.date() != end.date():
        raise ValueError("Five-minute bar crosses a trading-day boundary")
    return start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M")


def discrepancy_fields(h_normalized, pq):
    if not all(math.isfinite(float(x)) for x in (*h_normalized, *pq)):
        raise ValueError("Nonfinite candidate source bar")
    diffs = [
        field for i, field in enumerate(FIELDS)
        if not diagnose.close_enough(
            h_normalized[i], pq[i], "price" if i < 4 else field)
    ]
    return diffs


def severity_key(row):
    """Prefer truly useful mismatches: changed OHLC, then large price difference."""
    h, p = row["h_normalized"], row["p"]
    price = max(abs(h[i] - p[i]) for i in range(4))
    size = max(abs(h[3]), abs(p[3]), 0.01)
    relative_price = price / size
    volume = abs(h[4]-p[4]) / max(abs(h[4]), abs(p[4]), 1)
    amount = abs(h[5]-p[5]) / max(abs(h[5]), abs(p[5]), 1)
    has_price = any(x in row["different_fields"] for x in PRICE_FIELDS)
    return (int(has_price), round(relative_price, 12),
            round(volume + amount, 12), -row["bar_end"])


def select_verification_rows(h5_bars, pq_start_bars, symbols, per_symbol=3):
    """Only select actual compared, above-tolerance 5min differences."""
    if not (type(per_symbol) is int and 1 <= per_symbol <= 8):
        raise ValueError("--per-symbol must be in 1..8")
    rows = []
    for sym in symbols:
        candidates = []
        for (source_sym, start), p in pq_start_bars.items():
            if source_sym != sym:
                continue
            bar_end = diagnose.shift_bar_stamp(start, 5)
            h = h5_bars.get((sym, bar_end))
            if h is None:
                continue
            h_normalized = (
                *h[:4], h[4] * 100.0, h[5]
            )
            fields = discrepancy_fields(h_normalized, p)
            if not fields:
                continue
            interval_start, interval_end = five_minute_interval(bar_end)
            candidates.append({
                "symbol": sym, "bar_end": bar_end,
                "interval_start": interval_start,
                "interval_end": interval_end,
                "different_fields": fields,
                "h_normalized": h_normalized, "p": p,
            })
        morning = sorted(
            (r for r in candidates if r["bar_end"] % 10000 <= 1130),
            key=severity_key, reverse=True)
        afternoon = sorted(
            (r for r in candidates if r["bar_end"] % 10000 >= 1305),
            key=severity_key, reverse=True)
        chosen = []
        if morning:
            chosen.append(morning[0])
        if afternoon and len(chosen) < per_symbol:
            chosen.append(afternoon[0])
        chosen_ends = {x["bar_end"] for x in chosen}
        for row in sorted(candidates, key=severity_key, reverse=True):
            if len(chosen) >= per_symbol:
                break
            if row["bar_end"] not in chosen_ends:
                chosen.append(row)
                chosen_ends.add(row["bar_end"])
        rows.extend(sorted(chosen, key=lambda r: r["bar_end"]))
    return rows


def safe_report(selected, symbols, trade_day, exact_name, meta):
    """No market prices, quantities, amounts, or raw source tuples in output."""
    by_symbol = {sym: [] for sym in symbols}
    for r in selected:
        by_symbol[r["symbol"]].append({
            "bar_interval_start_beijing": r["interval_start"],
            "bar_interval_end_beijing": r["interval_end"],
            "h5_bar_end_stamp": str(r["bar_end"]),
            "parquet_bar_start_stamp": str(diagnose.shift_bar_stamp(
                r["bar_end"], -5)),
            "mismatch_fields_after_h5_5min_volume_x100_candidate":
                list(r["different_fields"]),
            "requires_same_interval_not_same_displayed_timestamp": True,
        })
    return {
        "format": "AStockDataTools Tonghuashun manual 5min source selection v1",
        "date": trade_day.isoformat(),
        "selected_symbols": list(symbols),
        "exact_masks_baseline_report_name": exact_name,
        "verification_points_by_symbol": by_symbol,
        "selected_points": sum(len(x) for x in by_symbol.values()),
        "selection": "actual source-differing K-lines, OHLC-priority, morning/afternoon",
        "reference_adjustment": "unadjusted (no/qfq disabled)",
        "h5_timestamp": "end-labelled",
        "parquet_timestamp": "start-labelled; +5min to H5 end",
        "h5_5min_volume_factor_is_candidate": 100,
        "h5_5min_amount_multiplier": 1,
        "source_read_cost_from_this_run": meta,
        "raw_source_ohlcv_exported": False,
        "raw_source_data_sent_to_chat": False,
        "source_market_files_modified": False,
        "manual_ths_comparison_not_yet_performed": True,
        "official_source_correctness_certified": False,
        "safe_to_automatically_union": False,
    }


def show_values_only_locally(selected):
    print("\nLOCAL DISPLAY ONLY — DO NOT UPLOAD THESE VALUES")
    for r in selected:
        h = r["h_normalized"]
        p = r["p"]
        print(f"{r['symbol']} [{r['interval_start']} -> {r['interval_end']}] "
              f"changed={','.join(r['different_fields'])}")
        for name, i in zip(FIELDS, range(6)):
            print(f"  {name:<7s} H5={h[i]:.6f}   Parquet={p[i]:.6f}")
        print("  Check Tonghuashun with NO adjustment, same bar interval, "
              "volume in shares and amount in yuan.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--baseline-report", type=Path, required=True)
    ap.add_argument("--top-symbols", type=int, default=3)
    ap.add_argument("--per-symbol", type=int, default=3)
    ap.add_argument("--show-local-values", action="store_true",
                    help="Explicit opt-in: display paid market OHLCV only on YOUR terminal")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        if not 1 <= args.per_symbol <= 8:
            raise ValueError("--per-symbol must be in 1..8")
        out, scratch = core.resolve_module_artifact_paths(args.out, None)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json"
            or not out.is_relative_to((HERE.parent / "reports").resolve())
            or out.exists()):
            raise ValueError("New --out JSON must stay in module reports/; no overwrite")
        baseline_file = args.baseline_report.resolve()
        if baseline_file.suffix.lower() != ".json" or baseline_file == out:
            raise ValueError("Baseline must be an existing separate JSON report")
        candidates = focused.load_baseline(
            json.loads(baseline_file.read_text(encoding="utf-8")),
            day, args.top_symbols)
        symbols = tuple(candidates)
        print("Reading H5 & relevant Parquet rows to find TRUE changed bars...",
              flush=True)
        h5, _ = diagnose.load_h5(root, symbols, day)
        pq, scan = diagnose.load_parquet(root, symbols, day, True)
        if scan.get("duplicate_keys", 0) or scan.get("nonfinite_rows", 0):
            raise ValueError("Invalid or duplicate Parquet bars; abort manual list")
        # Previously audited per-stock exclusive masks MUST still match.
        focused.summarized_pair_masks(h5, pq, candidates)
        selected = select_verification_rows(h5, pq, symbols, args.per_symbol)
        if not selected or any(not any(r["symbol"] == s for r in selected)
                               for s in symbols):
            raise ValueError("No comparable real source disagreement for a selected symbol")
        meta = {
            "parquet_row_groups_read": scan.get("row_groups_read"),
            "parquet_source_rows_examined": scan.get("source_rows_in_scanned_groups"),
            "parquet_selected_rows": scan.get("selected_source_rows"),
        }
        result = safe_report(selected, symbols, day, baseline_file.name, meta)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        print("Saved comparison keys ONLY:", out, flush=True)
        print("Actual verified differing bars:", len(selected))
        if args.show_local_values:
            show_values_only_locally(selected)
        else:
            print("Use --show-local-values to DISPLAY both sources' numerical "
                  "OHLCV on your PC (no numeric values enter report JSON).")
    except (ValueError, OSError, TypeError, OverflowError, json.JSONDecodeError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
