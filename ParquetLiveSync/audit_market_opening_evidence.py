#!/usr/bin/env python3
"""Immutable evidence classification for 2026-10-14..11-18 stock-day anomalies.

Only reads the previous complete SHA-pinned finding inventory, official
TDX DAY overlay, and accepted physical 1m months. It does not fabricate
zero-volume K-lines, fetch QMT, or modify AllCycleAStockData / task state.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

import audit_market_history_readonly as A
import local_layout as L
import market_month_storage as S


EXPECTED_FINDINGS_SHA = "cab71d7a08f30ce6b601c75607ecefeb69a31211385d60c13e444389e80d6847"
EPS = 0.005
FIELDS = tuple(L.COLS)


def aliases(symbol):
    exchange = symbol[:2]
    code = symbol[2:]
    return [symbol, code + "." + exchange,
            code + "." + {"SH": "XSHG", "SZ": "XSHE"}[exchange]]


def read_findings(path, sha=EXPECTED_FINDINGS_SHA):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or redirected immutable finding inventory")
    digest = L.hash_file(path)
    if digest != sha:
        raise ValueError("Historic full finding inventory SHA mismatch")
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    if len(entries) != 180:
        raise ValueError("Expected exactly 180 prior five-cycle findings")
    issues = {}
    for item in entries:
        day, sym, period, issue = (item[k] for k in ("date", "symbol", "period", "issue"))
        if not (str(A.START) <= day <= str(A.END) and
                len(sym) == 8 and sym[:2] in ("SH", "SZ")
                and sym[2:].isdigit() and period in A.PERIODS):
            raise ValueError("Finding outside independently audited scope")
        if period == "1min":
            issues.setdefault((day, sym), set()).add(issue)
    if len(issues) != 32:
        raise ValueError("Previously audited 32 stock-days changed")
    if sum("MISSING_STOCKDAY" in v for v in issues.values()) != 11:
        raise ValueError("Previously audited missing stock-day count changed")
    if sum("DAY_OPEN_MISMATCH" in v for v in issues.values()) != 19:
        raise ValueError("Previously audited opening mismatch count changed")
    if sum("PRICE_OUTSIDE_OFFICIAL_DAY" in v for v in issues.values()) != 5:
        raise ValueError("Previously audited day-envelope count changed")
    return issues, digest


def examine(root, project, findings_file):
    issues, digest = read_findings(findings_file)
    project = Path(project).resolve()
    root = Path(root)
    refs, _ = A.official_reference(project, A.START, A.END)
    workspace = project / "ParquetLiveSync" / "work" / "market_update"
    minute_state = S.state_for(root, workspace=workspace)
    months = sorted(set(day[:7] for day, _ in issues))
    physical_sources = {}
    groups = {}
    cases = {(day, sym) for (day, sym), problems in issues.items()
             if "MISSING_STOCKDAY" not in problems}
    for month in months:
        path, sha = A.check_month_identity(root, project, "1min", month,
                                            minute_state, None)
        physical_sources[month] = sha
        month_cases = {(day, sym) for day, sym in cases if day[:7] == month}
        if not month_cases:
            continue
        symbols = sorted({alias for _, sym in month_cases for alias in aliases(sym)})
        beginning = min(day for day, _ in month_cases)
        ending = max(day for day, _ in month_cases)
        from datetime import datetime, timedelta
        start = int(datetime.fromisoformat(beginning).replace(
            tzinfo=L.UTC8).timestamp() * 1000)
        end = int((datetime.fromisoformat(ending).replace(
            tzinfo=L.UTC8) + timedelta(days=1)).timestamp() * 1000)
        table = pq.read_table(path, columns=list(FIELDS),
                              filters=[("symbol", "in", symbols),
                                       ("ts", ">=", start), ("ts", "<", end)])
        for row in table.to_pylist():
            key = (str(L.market_ts_day(int(row["ts"]))),
                   L.normal_symbol(row["symbol"]))
            if key in month_cases:
                groups.setdefault(key, []).append(row)
        if L.hash_file(path) != sha:
            raise ValueError("Minute physical file changed during evidence lookup")
    counts = Counter()
    observed = []
    for (day, sym), problem_set in sorted(issues.items()):
        reference = refs.get((A.day_number(date.fromisoformat(day)), sym))
        if reference is None:
            raise ValueError("Missing SHA-verified official DAY case " + day + " " + sym)
        if "MISSING_STOCKDAY" in problem_set:
            if (day, sym) in groups:
                raise ValueError("Missing stock-day unexpectedly has physical data")
            counts["MISSING_SOURCE"] += 1
            observed.append({"date": day, "symbol": sym,
                             "issues": sorted(problem_set),
                             "category": "MISSING_SOURCE",
                             "independent_minute_evidence_required": True})
            continue
        rows = sorted(groups.get((day, sym), []), key=lambda x: x["ts"])
        if len(rows) != 240 or len({x["ts"] for x in rows}) != 240:
            raise ValueError("Unexpected physical 240-grid " + day + " " + sym)
        first = next((i for i, x in enumerate(rows)
                      if float(x["volume"]) > 0), None)
        if first is None:
            raise ValueError("No traded minute in audited stock-day")
        zero_prefix = rows[:first]
        if any(float(x["volume"]) != 0 or float(x["amount"]) != 0
               for x in zero_prefix):
            raise ValueError("Zero opening prefix amount/volume mismatch")
        open_match = math.isclose(float(rows[first]["open"]), reference["open"],
                                  abs_tol=EPS, rel_tol=0)
        full_high = max(float(x["high"]) for x in rows)
        full_low = min(float(x["low"]) for x in rows)
        traded_high = max(float(x["high"]) for x in rows if x["volume"] > 0)
        traded_low = min(float(x["low"]) for x in rows if x["volume"] > 0)
        # These source comparisons are evidence, NOT permission to edit.
        traded_range_within_day = (
            traded_high <= reference["high"] + EPS and
            traded_low >= reference["low"] - EPS)
        traded_range_exact = (abs(traded_high - reference["high"]) <= EPS and
                              abs(traded_low - reference["low"]) <= EPS)
        outside = "PRICE_OUTSIDE_OFFICIAL_DAY" in problem_set
        opening_disagrees = "DAY_OPEN_MISMATCH" in problem_set
        first_zero = bool(zero_prefix)
        if (first_zero and open_match and traded_range_within_day):
            category = ("ZERO_PREFIX_DAY_ENVELOPE_CONFLICT" if outside else
                        "ZERO_PREFIX_OPEN_CONFLICT")
        else:
            category = "INDEPENDENT_SOURCE_REVIEW_REQUIRED"
        counts[category] += 1
        observed.append({
            "date": day, "symbol": sym, "issues": sorted(problem_set),
            "category": category, "leading_zero_minutes": first,
            "first_minute_open": float(rows[0]["open"]),
            "first_minute_volume": float(rows[0]["volume"]),
            "first_traded_local_time": __import__("datetime").datetime.fromtimestamp(
                rows[first]["ts"] / 1000, L.UTC8).strftime("%H:%M"),
            "first_traded_open": float(rows[first]["open"]),
            "official_open": reference["open"],
            "first_traded_open_matches_official": open_match,
            "full_high": full_high, "full_low": full_low,
            "official_high": reference["high"], "official_low": reference["low"],
            "traded_high": traded_high, "traded_low": traded_low,
            "traded_range_within_official_day": traded_range_within_day,
            "traded_range_exact_official": traded_range_exact,
            "independent_minute_evidence_required": True,
        })
    if len(observed) != 32 or sum(counts.values()) != 32:
        raise ValueError("Incomplete historical evidence classification")
    return {"format": "sha_bound_opening_evidence_readonly_v1",
            "findings_sha256": digest, "market_1min_month_sha256": physical_sources,
            "counts": dict(sorted(counts.items())),
            "cases": observed, "production_repair_authorized": False,
            "market_files_modified": False, "qmt_download_called": False,
            "scheduled_task_modified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--findings", type=Path, required=True)
    args = parser.parse_args(argv)
    report = examine(args.root, args.source_project, args.findings)
    print("MARKET_OPENING_EVIDENCE_READONLY=" + json.dumps(
        report, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
