#!/usr/bin/env python3
"""Read-only 5min conservation audit: distinguish cross-window redistribution from loss.

Compares matched H5 vs vendor Parquet five-minute bars by morning/afternoon
without exporting raw OHLCV.  Requires no 1min H5 data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "diagnose_5min_for_conservation", HERE / "diagnose-5min-alignment.py")
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)
core = diagnostic.core

DEFAULT_TICKERS = ("SH600000", "SZ000636", "SH603181", "SZ300747", "BJ920680")
FIELDS = ("volume", "amount")


def session_name(bar_end: int) -> str:
    clock = bar_end % 10000
    if 935 <= clock <= 1130:
        return "morning"
    if 1305 <= clock <= 1500:
        return "afternoon"
    return "outside_regular_5min_session"


def minute_gap(left: int, right: int) -> int:
    a = datetime.strptime(str(left), "%Y%m%d%H%M")
    b = datetime.strptime(str(right), "%Y%m%d%H%M")
    return int((b - a).total_seconds() / 60)


def pct(numer: float, denom: float):
    return round(100 * numer / denom, 6) if denom > 0 else None


def invalid_ohlc(value: tuple[float, ...]) -> bool:
    o, hi, lo, c = value[:4]
    return hi + 0.005 < max(o, c) or lo - 0.005 > min(o, c) or hi + 0.005 < lo


def _pearson(pairs: list[tuple[float, float]]):
    if len(pairs) < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    corr = sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(sx * sy)
    return round(max(-1.0, min(1.0, corr)), 6)


def field_conservation(pairs: list[tuple[int, tuple, tuple]], index: int,
                       field: str) -> dict:
    """All quantities computed on the same matched keys and one session."""
    if not pairs:
        return {"matched_bars": 0, "source_total_ratio_parquet_over_h5": None,
                "net_difference_pct_of_h5_total": None, "gross_bar_difference_pct_of_h5_total": None,
                "cancellation_fraction": None, "max_cumulative_imbalance_pct": None,
                "different_bars": 0, "adjacent_pairs": 0,
                "adjacent_nonzero_difference_pairs": 0, "adjacent_opposite_sign_pairs": 0,
                "neighbor_difference_lag1_correlation": None}
    htot, ptot, totalabs, running, runningpeak, different = 0.0, 0.0, 0.0, 0.0, 0.0, 0
    differences = []
    for t, h, p in pairs:
        hv, pv = h[index], p[index]
        htot += hv
        ptot += pv
        delta = pv - hv
        differences.append((t, delta, abs(delta) > 1e-8))
        totalabs += abs(delta)
        running += delta
        runningpeak = max(runningpeak, abs(running))
        if not diagnostic.close_enough(pv, hv, field):
            different += 1
    adjacent, nz_pairs, opposite, lag = 0, 0, 0, []
    for (t1, d1, nz1), (t2, d2, nz2) in zip(differences, differences[1:]):
        if minute_gap(t1, t2) != 5:
            continue
        adjacent += 1
        lag.append((d1, d2))
        if nz1 and nz2:
            nz_pairs += 1
            if d1 * d2 < 0:
                opposite += 1
    return {
        "matched_bars": len(pairs),
        "different_bars": different,
        "source_total_ratio_parquet_over_h5": round(ptot / htot, 8) if htot else None,
        "net_difference_pct_of_h5_total": pct(abs(ptot - htot), abs(htot)),
        "gross_bar_difference_pct_of_h5_total": pct(totalabs, abs(htot)),
        "cancellation_fraction": round(1 - abs(ptot - htot) / totalabs, 6) if totalabs else None,
        "max_cumulative_imbalance_pct": pct(runningpeak, abs(htot)),
        "adjacent_pairs": adjacent,
        "adjacent_nonzero_difference_pairs": nz_pairs,
        "adjacent_opposite_sign_pairs": opposite,
        "neighbor_difference_lag1_correlation": _pearson(lag)
    }


def boundary_price_stats(pairs: list[tuple[int, tuple, tuple]]) -> dict:
    """Cross-source boundary relations, evaluated only within each market session."""
    out = {
        "open_different_bars": 0, "open_diff_with_previous_contiguous_bar": 0,
        "h5_open_equals_previous_parquet_close": 0,
        "h5_open_equals_previous_h5_close": 0,
        "parquet_open_equals_previous_parquet_close": 0,
        "close_different_bars": 0, "close_diff_with_next_contiguous_bar": 0,
        "parquet_close_equals_next_h5_open": 0,
        "parquet_close_equals_next_parquet_open": 0,
        "h5_close_equals_next_h5_open": 0
    }
    for i, (t, h, p) in enumerate(pairs):
        if not diagnostic.close_enough(h[0], p[0], "price"):
            out["open_different_bars"] += 1
            if i > 0 and minute_gap(pairs[i - 1][0], t) == 5:
                previous_h, previous_p = pairs[i - 1][1:]
                out["open_diff_with_previous_contiguous_bar"] += 1
                for field, a, b in (
                    ("h5_open_equals_previous_parquet_close", h[0], previous_p[3]),
                    ("h5_open_equals_previous_h5_close", h[0], previous_h[3]),
                    ("parquet_open_equals_previous_parquet_close", p[0], previous_p[3])):
                    if diagnostic.close_enough(a, b, "price"):
                        out[field] += 1
        if not diagnostic.close_enough(h[3], p[3], "price"):
            out["close_different_bars"] += 1
            if i + 1 < len(pairs) and minute_gap(t, pairs[i + 1][0]) == 5:
                next_h, next_p = pairs[i + 1][1:]
                out["close_diff_with_next_contiguous_bar"] += 1
                for field, a, b in (
                    ("parquet_close_equals_next_h5_open", p[3], next_h[0]),
                    ("parquet_close_equals_next_parquet_open", p[3], next_p[0]),
                    ("h5_close_equals_next_h5_open", h[3], next_h[0])):
                    if diagnostic.close_enough(a, b, "price"):
                        out[field] += 1
    return out


def analyze(h5_rows: dict, parquet_starts: dict, symbols: tuple[str, ...]) -> dict:
    pq_end = {(symbol, diagnostic.shift_bar_stamp(start, 5)): values
              for (symbol, start), values in parquet_starts.items()}
    result = {}
    for symbol in symbols:
        h = {t: values for (s, t), values in h5_rows.items() if s == symbol}
        p = {t: values for (s, t), values in pq_end.items() if s == symbol}
        all_times = sorted(set(h) & set(p))
        sessions = defaultdict(list)
        for end in all_times:
            sessions[session_name(end)].append((end, h[end], p[end]))
        per_session = {}
        for label, pairs in sorted(sessions.items()):
            per_session[label] = {
                "matched_bars": len(pairs),
                "volume": field_conservation(pairs, 4, "volume"),
                "amount": field_conservation(pairs, 5, "amount"),
                "price_boundaries": boundary_price_stats(pairs)
            }
        combined = [(t, h[t], p[t]) for t in all_times]
        # The all-day net conservation is not a contiguous-sequence statistic.
        # Do not compute lag-1 or price boundary across the 11:30-13:05 break.
        daily = {
            "matched_bars": len(combined),
            "volume": field_conservation(combined, 4, "volume"),
            "amount": field_conservation(combined, 5, "amount")
        }
        result[symbol] = {
            "h5_5min_bars": len(h), "parquet_5min_bars": len(p),
            "h5_only_bars": len(set(h) - set(p)),
            "parquet_only_bars": len(set(p) - set(h)),
            "h5_ohlc_geometry_violations": sum(invalid_ohlc(row) for row in h.values()),
            "parquet_ohlc_geometry_violations": sum(invalid_ohlc(row) for row in p.values()),
            "conservation_on_matched_keys_only": daily,
            "sessions": per_session,
            "status": ("no_comparable_bars" if not combined else "hypothesis_diagnostic_only")
        }
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True, help="Trading day YYYY-MM-DD")
    ap.add_argument("--symbols", nargs="+", default=list(DEFAULT_TICKERS))
    ap.add_argument("--out", type=Path, default=Path("reports") / "5min-session-conservation.json")
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        symbols = tuple(dict.fromkeys(s.upper() for s in args.symbols))
        if not 1 <= len(symbols) <= 20 or any(core.symbol_id(s) != s for s in symbols):
            raise ValueError("Supply 1..20 market-prefixed six-digit symbols")
        out, scratch = core.resolve_module_artifact_paths(args.out, None)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if out.exists():
            raise ValueError(f"Report already exists; choose a new filename: {out}")
        h5, h5_availability = diagnostic.load_h5(root, symbols, day)
        print("H5 selected 5min bars:", len(h5), flush=True)
        pq, source_summary = diagnostic.load_parquet(root, symbols, day, True)
        print("Parquet selected 5min bars:", len(pq), flush=True)
        report = {
            "format": "AStockDataTools 5min session conservation v1",
            "date": day.isoformat(), "symbols": list(symbols),
            "h5_coverage": h5_availability, "parquet_scan": source_summary,
            "symbol_results": analyze(h5, pq, symbols),
            "source_files_modified": False,
            "source_units_certified": False,
            "safe_to_automatically_union": False,
            "scope": "Only common (symbol, 5min_end) keys; source timestamps provisionally start+5min",
            "interpretation": [
                "Near-zero daily net discrepancies with positive gross bar differences support, but do not prove, redistribution between bars.",
                "Negative neighbor delta correlation and alternating signs strengthen only a boundary-allocation hypothesis.",
                "Session metrics are split at the noon break; adjacency never bridges the lunch break.",
                "High/low/open/close construction may differ. Geometry checks only establish internal OHLC consistency.",
                "H5 1min was unavailable on 2025-09-30 in the prior sample, so this check uses no minute data.",
                "Input is local licensed OHLCV, output contains aggregate counts and ratios, not OHLCV prices or amounts."
            ]
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.name + ".tmp")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        temp.replace(out)
        print("Saved", out, "(source data read-only)", flush=True)
    except (OSError, ValueError, OverflowError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
