"""Synthetic staged Parquet daily-tail integration; never reads user's market data."""
import hashlib
import json
import importlib.util
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "stage-h5-only-day-to-parquet.py")
SPEC = importlib.util.spec_from_file_location("h5_daily_staging_tool", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

DTYPE = np.dtype([
    ("datetime", "<u8"), ("openPrice", "<i4"),
    ("highPrice", "<i4"), ("lowPrice", "<i4"), ("closePrice", "<i4"),
    ("transCount", "<u8"), ("transAmount", "<u8")
])


def stamp_ms(d):
    return int(datetime(d.year, d.month, d.day,
                        tzinfo=M.core.UTC8).timestamp() * 1000)


@contextmanager
def small_sources():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise unittest.SkipTest("pyarrow not installed in synthetic test environment")
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        module = base / "module"
        reports = module / "reports"
        reports.mkdir(parents=True)
        stock = base / "stock"
        h5_dir = stock / "HikyuuData"
        h5_dir.mkdir(parents=True)
        pq_dir = stock / "AllCycleAStockData" / "day"
        pq_dir.mkdir(parents=True)
        for market in ("sh", "sz", "bj"):
            with h5py.File(h5_dir / (market + "_day.h5"), "w") as f:
                data = f.create_group("data")
                if market == "sh":
                    data.create_dataset("SH600000", data=np.array([
                        (202609300000, 12000, 12100, 11900, 12050, 120, 1500),
                        (202610080000, 12300, 12500, 12200, 12400, 150, 1800),
                    ], dtype=DTYPE))
        source_pq = pq_dir / "2026-09.parquet"
        base_row = {
            "ts": stamp_ms(date(2026, 9, 30)),
            "symbol": "600000.XSHG",
            "open": 12.0, "high": 12.1, "low": 11.9, "close": 12.05,
            "volume": 12000.0, "amount": 1500000.0, "source": "purchased"}
        pq.write_table(pa.Table.from_pylist([base_row]), source_pq)
        report = reports / "source.json"
        work = module / "work"
        raw = M.core.run(
            stock, report, work / "audit", [2026], ["day"], 8192, False,
            "a-share-candidate", "2026-09-30", "2026-10-08", False)
        if raw["status"] != "complete":
            raise AssertionError("synthetic source must complete")
        gate = M.gate_tool.analyze(raw)
        gate["source_report_basename"] = report.name
        gate["source_report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
        gate_path = reports / "gate.json"
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        with patch.object(M, "MODULE", module), \
                patch.object(M, "REPORTS", reports), \
                patch.object(M, "STAGING", work / "unified_parquet" / "staging"):
            yield (stock, module, report, gate_path, source_pq)


class H5DailyStageTests(unittest.TestCase):
    def test_real_generated_h5_and_parquet_end_to_end_stage(self):
        import pyarrow.parquet as pq
        with small_sources() as (stock, module, report, gate, purchased):
            prior = M.file_digest(purchased)
            stage_dir = module / "work" / "unified_parquet" / "staging" / "batch1"
            result = M.stage(stock, gate, report, date(2026, 10, 8),
                             stage_dir, 200)
            self.assertEqual(result["staged_bars"], 1)
            self.assertEqual(result["market_prefix_counts"], {"SH": 1})
            self.assertFalse(result["purchased_parquet_overwritten"])
            self.assertFalse(result["ready_for_production_promotion"])
            self.assertFalse(result["safe_to_automatically_union"])
            self.assertEqual(M.file_digest(purchased), prior)
            rows = pq.read_table(stage_dir / "day.parquet").to_pylist()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "600000.XSHG")
            self.assertEqual(rows[0]["ts"], stamp_ms(date(2026, 10, 8)))
            self.assertEqual(rows[0]["open"], 12.3)
            self.assertEqual(rows[0]["volume"], 15000.0)
            self.assertEqual(rows[0]["amount"], 1800000.0)
            self.assertEqual(result["staged_parquet_sha256"],
                             M.file_digest(stage_dir / "day.parquet"))
            self.assertTrue((stage_dir / "manifest.json").is_file())
            with self.assertRaisesRegex(ValueError, "already exists"):
                M.stage(stock, gate, report, date(2026, 10, 8),
                        stage_dir, 200)

    def test_staging_overlap_date_is_rejected(self):
        with small_sources() as (stock, module, report, gate, pq_file):
            path = module / "work" / "unified_parquet" / "staging" / "overlap"
            with self.assertRaisesRegex(ValueError, "H5-only"):
                M.stage(stock, gate, report, date(2026, 9, 30), path, 200)
            self.assertFalse(path.exists())

    def test_modified_report_sha_or_gate_counts_fail_closed(self):
        with small_sources() as (stock, module, report, gate, pq_file):
            data = json.loads(gate.read_text(encoding="utf-8"))
            data["source_report_sha256"] = "0" * 64
            gate.write_text(json.dumps(data), encoding="utf-8")
            path = module / "work" / "unified_parquet" / "staging" / "bad_gate"
            with self.assertRaisesRegex(ValueError, "Gate mismatch"):
                M.stage(stock, gate, report, date(2026, 10, 8), path, 200)
            self.assertFalse(path.exists())

    def test_fresh_parquet_day_record_blocks_stale_h5_only_gate(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with small_sources() as (stock, module, report, gate, pq_file):
            newer = pq_file.parent / "2026-10.parquet"
            pq.write_table(pa.Table.from_pylist([{
                "ts": stamp_ms(date(2026, 10, 8)), "symbol": "600000.XSHG",
                "open": 12.3, "high": 12.5, "low": 12.2, "close": 12.4,
                "volume": 15000.0, "amount": 1800000.0, "source": "new_purchased",
            }]), newer)
            out = module / "work" / "unified_parquet" / "staging" / "stale"
            with self.assertRaisesRegex(ValueError, "Live source recheck"):
                M.stage(stock, gate, report, date(2026, 10, 8), out, 200)
            self.assertFalse(out.exists())

    def test_corrupt_h5_ohlc_geometry_and_duplicate_day_rejected(self):
        with small_sources() as (stock, module, report, gate, pq_file):
            h5 = stock / "HikyuuData" / "sh_day.h5"
            with h5py.File(h5, "r+") as f:
                record = f["data/SH600000"][:]
                record[1]["highPrice"] = 10000
                f["data/SH600000"][:] = record
            with self.assertRaisesRegex(ValueError, "geometry"):
                M.read_h5_day(stock, date(2026, 10, 8), 200)
        with small_sources() as (stock, module, report, gate, pq_file):
            h5 = stock / "HikyuuData" / "sh_day.h5"
            with h5py.File(h5, "r+") as f:
                raw = f["data/SH600000"][:]
                del f["data/SH600000"]
                f["data"].create_dataset("SH600000", data=np.concatenate((raw, raw[-1:])))
            with self.assertRaisesRegex(ValueError, "Duplicate H5"):
                M.read_h5_day(stock, date(2026, 10, 8), 200)

    def test_missing_market_source_or_oversize_gate_blocks_stage(self):
        with small_sources() as (stock, module, report, gate, pq_file):
            (stock / "HikyuuData" / "bj_day.h5").unlink()
            with self.assertRaisesRegex(ValueError, "All three H5"):
                M.stage(stock, gate, report, date(2026, 10, 8),
                        module / "work" / "unified_parquet" / "staging" / "missing", 200)
        with small_sources() as (stock, module, report, gate, pq_file):
            with self.assertRaisesRegex(ValueError, "Audited number"):
                M.stage(stock, gate, report, date(2026, 10, 8),
                        module / "work" / "unified_parquet" / "staging" / "too_small", 0)

    def test_stage_path_must_stay_in_module(self):
        with small_sources() as (stock, module, report, gate, pq_file):
            with self.assertRaisesRegex(ValueError, "Reports must"):
                M.stage(stock, gate, report, date(2026, 10, 8),
                        stock / "AllCycleAStockData" / "day" / "overlap", 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
