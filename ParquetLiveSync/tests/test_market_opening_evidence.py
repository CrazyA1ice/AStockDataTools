"""Read-only opening evidence classification with synthetic SHA-bound days."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audit_market_opening_evidence as E
import audit_market_history_readonly as A
import local_layout as L


DAY = date(2026, 11, 18)
NUMBER = A.day_number(DAY)


def cases():
    present = ["SH" + str(600000 + i) for i in range(21)]
    missing = ["SH" + str(600100 + i) for i in range(11)]
    issues = {(str(DAY), sym): {"DAY_OPEN_MISMATCH"} for sym in present[:19]}
    for sym in present[19:]:
        issues[(str(DAY), sym)] = set()
    for sym in present[:3] + present[19:]:
        issues[(str(DAY), sym)].add("PRICE_OUTSIDE_OFFICIAL_DAY")
    for sym in missing:
        issues[(str(DAY), sym)] = {"MISSING_STOCKDAY"}
    assert len(issues) == 32
    return issues, present, missing


def physical_rows(present):
    rows = []
    for symbol in present:
        for i, (h, m) in enumerate(sorted(__import__("qmt_1m_pipeline").GRID - {(9, 30)})):
            value = 10.
            first = i == 0
            if first:
                value = 10.52 if int(symbol[2:]) in (
                    600000, 600001, 600002, 600019, 600020) else 10.02
            rows.append({
                "ts": int(datetime(DAY.year, DAY.month, DAY.day, h, m,
                                   tzinfo=L.UTC8).timestamp() * 1000),
                "symbol": symbol, "open": value, "high": value,
                "low": value, "close": value,
                "volume": 0. if first else 2.,
                "amount": 0. if first else 20.})
    return rows


class OpeningEvidenceTests(unittest.TestCase):
    def test_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "findings.jsonl"
            path.write_text('{"a":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                E.read_findings(path)

    def test_all_32_cases_classified_without_market_writes(self):
        issues, present, missing = cases()
        rows = physical_rows(present)
        references = {(NUMBER, sym): {
            "open": 10., "high": 10.5, "low": 10.,
            "close": 10., "volume": 478., "amount": 4780.}
            for sym in present + missing}
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "2026-11.parquet"
            source.write_bytes(b"synthetic-placeholder-only")
            actual_sha = L.hash_file(source)
            with patch.object(E, "read_findings", return_value=(issues, "synthetic-sha")), (
                    patch.object(A, "official_reference",
                                 return_value=(references, {str(DAY): 32}))), (
                    patch.object(E.S, "state_for", return_value={})), (
                    patch.object(A, "check_month_identity",
                                 return_value=(source, actual_sha))), (
                    patch.object(E.pq, "read_table",
                                 return_value=pa.Table.from_pylist(rows))):
                report = E.examine("D:/stock", "D:/ChatGPT/AStockDataTools",
                                   "synthetic-findings.jsonl")
        self.assertEqual(len(report["cases"]), 32)
        self.assertEqual(report["counts"]["MISSING_SOURCE"], 11)
        self.assertEqual(report["counts"]["ZERO_PREFIX_DAY_ENVELOPE_CONFLICT"], 5)
        self.assertEqual(report["counts"]["ZERO_PREFIX_OPEN_CONFLICT"], 16)
        self.assertFalse(report["production_repair_authorized"])
        self.assertFalse(report["market_files_modified"])
        self.assertFalse(report["qmt_download_called"])


if __name__ == "__main__":
    unittest.main()
