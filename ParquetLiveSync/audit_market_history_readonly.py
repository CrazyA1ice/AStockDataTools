#!/usr/bin/env python3
"""Bounded, read-only SHA-pinned physical five-minute-cycle history audit.

Scans ONLY selected 2026-10-14..2026-11-18 stock-days in the already
committed 1/5/15/30/60-minute month files. Compares physical daily price
envelopes against independently accepted official TDX DAY and checks
stock-day coverage, clock grids and five-cycle OHLC agreement.

Never downloads market data, creates repairs, writes a journal/Parquet,
or changes Windows scheduled tasks. A daily audit candidate is NOT a
replacement for transactionally verified repair evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import math
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq

import live_sync as LIVE
import local_layout as L
import market_month_storage as S
import market_derived_cycles as D
import qmt_1m_pipeline as P
import qmt_1m_private_month_bridge as B

START = date(2026, 10, 14)
END = date(2026, 11, 18)
PERIODS = ("1min", "5min", "15min", "30min", "60min")
EXPECTED_ROWS = {"1min": 240, "5min": 48, "15min": 16,
                 "30min": 8, "60min": 4}
CN_MINUTES = 480
EPOCH_ORDINAL = date(1970, 1, 1).toordinal()
PRICE_EPS = .005
FIELDS = ("ts", "symbol", "open", "high", "low", "close", "volume", "amount")


def day_number(day):
    return day.toordinal() - EPOCH_ORDINAL


def months_between(start, end):
    months = []
    for y in range(start.year, end.year + 1):
        for m in range(1, 13):
            if (y, m) >= (start.year, start.month) and (y, m) <= (end.year, end.month):
                months.append(f"{y}-{m:02d}")
    return months


class Findings:
    def __init__(self):
        self.counts = Counter()
        self.examples = {}
        self.per_period = {}

    def add(self, period, issue, day, symbol, detail=None):
        label = period + ":" + issue
        self.counts[label] += 1
        collection = self.examples.setdefault(label, [])
        if len(collection) < 8:
            item = {"date": str(day), "symbol": symbol}
            if detail is not None:
                item["detail"] = detail
            collection.append(item)


def official_reference(project, start, end):
    work = project / "ParquetLiveSync" / "work"
    state = work / "state.json"
    if work.is_symlink() or state.is_symlink() or not state.is_file():
        raise ValueError("Original official DAY state missing or redirected")
    with patch.object(LIVE, "WORK", work), patch.object(LIVE, "STATE", state):
        snapshot = LIVE.read_state()
    original = {}
    per_day = {}
    for label, entry in sorted(snapshot["days"].items()):
        day = date.fromisoformat(label)
        if not start <= day <= end:
            continue
        physical = LIVE.checked_path(work, entry["file"])
        if L.hash_file(physical) != entry["sha256"]:
            raise ValueError("Accepted official DAY physical SHA mismatch " + label)
        bars = pq.read_table(physical, columns=list(L.COLS))
        L.validate_schema(bars.schema)
        expected = set()
        for bar in bars.to_pylist():
            sym = L.normal_symbol(bar["symbol"])
            if (len(sym) != 8 or sym[:2] not in ("SH", "SZ")
                    or not sym[2:].isdigit()
                    or float(bar["volume"]) <= 0
                    or float(bar["amount"]) <= 0):
                continue
            key = (day_number(day), sym)
            if key in original:
                raise ValueError("Duplicated official DAY security " + str(key))
            original[key] = {k: float(bar[k]) for k in FIELDS[2:]}
            expected.add(sym)
        per_day[label] = len(expected)
    if not per_day or not original:
        raise ValueError("No accepted official DAY references in requested date window")
    return original, per_day


def check_month_identity(root, project, period, month, minute_state, higher_state):
    path = L.storage_root(root) / period / (month + ".parquet")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing/redirected physical " + period + " " + month)
    if period == "1min":
        entry = minute_state["periods"]["1min"].get(month)
    else:
        entry = higher_state["months"][period].get(month)
    if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
        raise ValueError("Missing physical commit receipt " + period + " " + month)
    if L.hash_file(path) != entry["sha256"]:
        raise ValueError("Physical source SHA mismatch " + period + " " + month)
    return path, entry["sha256"]


def expected_clock(period, symbol, calibration, rules, cache):
    key = (period, P.category(symbol[2:] + "." + symbol[:2]))
    if key in cache:
        return cache[key]
    gate = B._calibration(calibration, symbol[2:] + "." + symbol[:2])
    shift = gate["offset_ms"] // 60000
    if period == "1min":
        slots = D.BASE_CLOCK
    else:
        width = D.BARS[period]
        spec = rules[period]
        stamp_shift = spec["timestamp_shift_from_1min_last_ms"]
        if type(stamp_shift) is not int or stamp_shift % 60000:
            raise ValueError("Higher-minute paid clock calibration invalid")
        shift += stamp_shift // 60000
        slots = [session[i + width - 1]
                 for session in (D.BASE_CLOCK[:120], D.BASE_CLOCK[120:])
                 for i in range(0, 120, width)]
    mask = 0
    for slot in slots:
        mask |= (1 << ((slot + shift) % 1440))
    if mask.bit_count() != EXPECTED_ROWS[period]:
        raise ValueError("Purchased clock grid has overlapping labels")
    cache[key] = mask
    return mask


def scan_month(path, period, start, end, findings):
    """One month at a time; 240/48/etc row groups need not be aligned.

    Per stock-day state remains bounded by month stock-day cardinality.
    A 1440-bit local-minute mask detects duplicates without retaining
    millions of minute objects.
    """
    lo, hi = day_number(start), day_number(end)
    groups = {}
    source = pq.ParquetFile(path)
    try:
        L.validate_schema(source.schema_arrow)
        for batch in source.iter_batches(batch_size=16384,
                                         columns=list(FIELDS), use_threads=False):
            for row in batch.to_pylist():
                ts = row["ts"]
                if type(ts) is not int:
                    raise ValueError("Physical timestamp must be integer epoch-ms")
                number = (ts + CN_MINUTES * 60000) // 86400000
                if number < lo or number > hi:
                    continue
                symbol = L.normal_symbol(row["symbol"])
                if len(symbol) != 8 or symbol[:2] not in ("SH", "SZ") or not symbol[2:].isdigit():
                    continue
                label = date.fromordinal(EPOCH_ORDINAL + number).isoformat()
                key = (number, symbol)
                values = [float(row[k]) for k in FIELDS[2:]]
                o, h, low, close, vol, amt = values
                if (not all(math.isfinite(x) for x in values)
                        or min(o, h, low, close) <= 0
                        or h < max(o, close) or low > min(o, close)
                        or vol < 0 or amt < 0 or (vol > 0) != (amt > 0)):
                    findings.add(period, "MALFORMED_OHLCVA", label, symbol)
                    continue
                minute = ((ts + CN_MINUTES * 60000) // 60000) % 1440
                if ts % 60000:
                    findings.add(period, "SUBMINUTE_TIMESTAMP", label, symbol)
                bit = 1 << minute
                state = groups.get(key)
                if state is None:
                    # count, first_ts, last_ts, open, close, high, low,
                    # total_vol, total_amt, minute_mask, traded_high, traded_low
                    groups[key] = [1, ts, ts, o, close, h, low, vol, amt,
                                   bit, h if vol > 0 else -math.inf,
                                   low if vol > 0 else math.inf]
                    continue
                if state[9] & bit:
                    findings.add(period, "DUPLICATE_MINUTE_LABEL", label, symbol)
                state[9] |= bit
                state[0] += 1
                if ts < state[1]:
                    state[1], state[3] = ts, o
                if ts > state[2]:
                    state[2], state[4] = ts, close
                state[5] = max(state[5], h)
                state[6] = min(state[6], low)
                state[7] += vol
                state[8] += amt
                if vol > 0:
                    state[10] = max(state[10], h)
                    state[11] = min(state[11], low)
    finally:
        source.close()
    return groups


def evaluate_groups(period, groups, references, calibration, rules, findings, baseline):
    clock_cache = {}
    observed = set()
    inspected = 0
    for (number, symbol), state in groups.items():
        day = date.fromordinal(EPOCH_ORDINAL + number).isoformat()
        key = (number, symbol)
        observed.add(key)
        inspected += 1
        count, _, _, op, cl, high, low, vol, amt, mask, traded_high, traded_low = state
        if count != EXPECTED_ROWS[period]:
            findings.add(period, "INCOMPLETE_STOCKDAY", day, symbol,
                         {"count": count, "expected": EXPECTED_ROWS[period]})
        elif mask != expected_clock(period, symbol, calibration, rules, clock_cache):
            findings.add(period, "UNEXPECTED_MINUTE_GRID", day, symbol)
        reference = references.get(key)
        if reference is None:
            findings.add(period, "MISSING_OFFICIAL_DAY", day, symbol)
            continue
        if high > reference["high"] + PRICE_EPS or low < reference["low"] - PRICE_EPS:
            findings.add(period, "PRICE_OUTSIDE_OFFICIAL_DAY", day, symbol,
                         {"high": high, "low": low,
                          "official_high": reference["high"],
                          "official_low": reference["low"]})
        for field, actual in (("open", op), ("high", high), ("low", low), ("close", cl)):
            if not math.isclose(actual, reference[field], rel_tol=.006, abs_tol=.04):
                findings.add(period, "DAY_" + field.upper() + "_MISMATCH",
                             day, symbol, {"actual": actual, "official": reference[field]})
        if period == "1min":
            baseline[key] = (op, high, low, cl)
            if traded_high != -math.inf and (
                    high > traded_high + PRICE_EPS
                    or low < traded_low - PRICE_EPS):
                findings.add(period, "UNTRADED_EXTENDS_DAILY_EXTREMA",
                             day, symbol)
            for field, actual in (("volume", vol), ("amount", amt)):
                if not math.isclose(actual, reference[field], rel_tol=.03,
                                    abs_tol=200 if field == "volume" else 1000):
                    findings.add(period, "DAY_" + field.upper() + "_MISMATCH",
                                 day, symbol, {"actual": actual, "official": reference[field]})
        else:
            one = baseline.get(key)
            if one is None:
                findings.add(period, "MISSING_1MIN_STOCKDAY", day, symbol)
            elif any(abs(float(a) - float(b)) > PRICE_EPS
                     for a, b in zip((op, high, low, cl), one)):
                findings.add(period, "CROSS_CYCLE_DAILY_OHLC_DRIFT", day, symbol,
                             {"cycle": [op, high, low, cl],
                              "one_min": list(one)})
    missing = set(references) - observed
    for number, symbol in sorted(missing):
        day = date.fromordinal(EPOCH_ORDINAL + number).isoformat()
        findings.add(period, "MISSING_STOCKDAY", day, symbol)
    findings.per_period[period] = {
        "physical_stock_days": inspected, "official_stock_days": len(references),
        "missing_stock_days": len(missing),
        "row_count_expected_each": EXPECTED_ROWS[period]}


def audit(root, source_project, start, end):
    if not START <= start <= end <= END:
        raise ValueError("Only 2026-10-14..2026-11-18 historical audits allowed")
    project = Path(source_project).resolve()
    work = project / "ParquetLiveSync" / "work"
    workspace = work / "market_update"
    if not work.is_dir() or work.is_symlink() or workspace.is_symlink():
        raise ValueError("Original SHA-pinned project work directory invalid")
    minute_state = S.state_for(root, workspace=workspace)
    higher_state = D._ledger(root, workspace)
    calib_path = work / "qmt_1min_market" / "calibration" / "latest.json"
    calibration = S._json(calib_path)
    if P.sha_bytes(P.canonical(calibration)) != minute_state.get("qmt_calibration_sha256"):
        raise ValueError("Original purchased 1m calibration digest mismatch")
    paid_path = workspace / "four_cycle_paid_rules.json"
    rules_doc = S._json(paid_path)
    if (rules_doc.get("format") != D.FORMAT
            or rules_doc.get("root") != str(L.storage_root(root).resolve())
            or set(rules_doc.get("periods", {})) != set(D.PERIODS)):
        raise ValueError("Original higher-minute calibration identity invalid")
    references, day_counts = official_reference(project, start, end)
    findings = Findings()
    baseline = {}
    paths = {}
    for period in PERIODS:
        total_groups = {}
        snapshots = []
        for month in months_between(start, end):
            file, sha = check_month_identity(root, project, period, month,
                                             minute_state, higher_state)
            groups = scan_month(file, period, start, end, findings)
            # Reject mixed/colliding stock-days across physical month files.
            overlap = set(groups) & set(total_groups)
            if overlap:
                raise ValueError("Cross-month duplicate physical stock-day " + period)
            total_groups.update(groups)
            snapshots.append((file, sha))
        evaluate_groups(period, total_groups, references, calibration,
                        rules_doc["periods"], findings, baseline)
        # A scheduled writer is NOT paused. Detect concurrent source swaps
        # and refuse to certify a race-dependent snapshot.
        for file, sha in snapshots:
            if L.hash_file(file) != sha:
                raise ValueError("Physical source changed during readonly audit " + str(file))
        paths[period] = {p.name: digest for p, digest in snapshots}
        del total_groups
    return {
        "format": "five_cycle_ohlcva_history_readonly_v1",
        "range": [start.isoformat(), end.isoformat()],
        "official_day_stockdays": len(references),
        "official_day_counts": day_counts,
        "periods": findings.per_period,
        "findings": dict(sorted(findings.counts.items())),
        "examples_capped_to_8_per_issue": dict(sorted(findings.examples.items())),
        "physical_month_sha256": paths,
        "historical_repair_authorized": False,
        "production_market_modified": False,
        "qmt_download_called": False,
        "scheduled_task_modified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    args = parser.parse_args(argv)
    result = audit(args.root, args.source_project, args.start, args.end)
    print("MARKET_HISTORY_READONLY_AUDIT=" + json.dumps(
        result, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
