"""Offline counting tests: mock SHA-qualified workers; never open paid data."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOL=Path(__file__).resolve().parent.parent/"tools"/"report-verified-unified-minute-progress.py"
spec=importlib.util.spec_from_file_location("safe_minute_progress_unit",TOOL)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ExistingMinuteProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.report=Path(self.tmp.name)
        self.patcher=patch.object(mod,"REPORTS",self.report)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def receipt(self,yyyymmdd,child):
        (self.report/f"minute-batch-unified-{yyyymmdd}-{child}.json").write_text(
            "{}",encoding="utf-8")

    def worker(self,records):
        def verify(day):
            item=records.get(day)
            if isinstance(item,Exception):
                raise item
            return item
        return SimpleNamespace(verified_existing_batch=verify)

    def test_duplicate_receipts_one_day_counted_once(self):
        self.receipt("20260901","aaaaaaaaaaaa")
        self.receipt("20260901","bbbbbbbbbbbb")
        self.receipt("20260902","cccccccccccc")
        result=mod.build(self.worker({
            "2026-09-01":{"1min":240,"5min":48},
            "2026-09-02":{"1min":480,"5min":96},
        }))
        self.assertEqual(result["unique_nonempty_date_count"],2)
        self.assertEqual(result["verified_physical_rows_by_period"],{"1min":720,"5min":144})
        self.assertEqual(result["verified_physical_rows_total"],864)
        self.assertFalse(result["all_historical_minute_days_completed"])

    def test_corrected_oct13_only_and_empty_weekday_not_coverage(self):
        self.receipt("20261014","aaaaaaaaaaaa")
        (self.report/"real-unified-minute-parquet-20261013-end-key-11127c8d60ba.json").write_text(
            "{}",encoding="utf-8")
        result=mod.build(self.worker({
            "2026-10-13":{"1min":1331760,"5min":266352},
            "2026-10-14":None,
        }))
        self.assertEqual(result["unique_nonempty_date_count"],1)
        self.assertEqual(result["verified_physical_rows_total"],1598112)
        self.assertEqual(result["zero_market_source_days_not_certified"],["2026-10-14"])

    def test_sha_conflict_fails_closed(self):
        self.receipt("20260901","aaaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError,"conflicting"):
            mod.build(self.worker({"2026-09-01":ValueError("conflicting same-date accepted SHA")}))

    def test_invalid_filename_fails_closed(self):
        (self.report/"minute-batch-unified-bogus.json").write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            mod.build(self.worker({}))

    def test_no_receipts_cannot_claim_progress(self):
        with self.assertRaisesRegex(ValueError,"No daily"):
            mod.build(self.worker({}))

if __name__=="__main__":
    unittest.main()
