#!/usr/bin/env python3
"""Read-only coverage audit of one QMT supplementary financial security.

No QMT connection or download; no Parquet, scheduler, H5 or cursor writes.
The provider's raw m_timetag markers are NOT automatically verified report dates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import qmt_extra_data as E


def audit(root, symbol, asof, *, workspace=E.WORK):
    symbol = E.valid_code(symbol)
    if not E.re.fullmatch(r"\d{4}-\d{2}-\d{2}", asof):
        raise ValueError("Audit asof must be YYYY-MM-DD")
    E.date.fromisoformat(asof)
    extra = E._storage(Path(root))
    state = E._state(extra, workspace)
    pending = E._pending_financial(state)
    summary = {}
    for name in E.FIN_TABLES:
        rows = E._verified_financial_snapshot(extra, symbol, name, asof)
        if rows is None:
            summary[name] = {"rows": None, "status": "NO_SNAPSHOT",
                             "raw_m_timetag_min": None,
                             "raw_m_timetag_max": None}
            continue
        folder = extra / "financial" / name / symbol / "snapshots"
        path = next(folder.glob(asof + "-*.parquet"))
        table = E._read_closed_parquet(path)
        raw = []
        for record in table.column("payload_json").to_pylist():
            value = json.loads(record)
            if not isinstance(value, dict):
                raise ValueError("Invalid QMT financial row payload: " + str(path))
            token = value.get("m_timetag")
            if token is not None:
                raw.append(str(token))
        summary[name] = {
            "rows": rows,
            "status": "SPARSE_RECORDS_NEED_REVIEW" if rows < 20 else "SNAPSHOT_VERIFIED",
            "raw_m_timetag_min": min(raw) if raw else None,
            "raw_m_timetag_max": max(raw) if raw else None}
    return {
        "status": "READONLY_FINANCIAL_COVERAGE_UNVERIFIED",
        "symbol": symbol, "asof": asof,
        "dataset": str(extra),
        "financial_scan_cursor": state.get("cursor", {}).get("financial", ""),
        "pending_retry": pending.get(symbol),
        "tables": summary,
        "snapshot_tables": sum(1 for v in summary.values() if v["rows"] is not None),
        "source_report_dates_validated": False,
        "data_files_modified": False,
        "progress_modified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--asof", required=True)
    args = parser.parse_args(argv)
    print("QMT_FINANCIAL_COVERAGE_AUDIT=" + E.canonical_json(
        audit(args.root, args.symbol, args.asof)))


if __name__ == "__main__":
    main()
