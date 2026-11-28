"""Synthetic-only 241-vs-240 original paid/incremental contract diagnosis."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_incremental_vs_purchased_minute_count_readonly as G

CN = timezone(timedelta(hours=8))
DAY = date(2026, 9, 30)
NEW_DAY = date(2026, 11, 12)


def grid(day, *, include_0930):
    d = datetime(day.year, day.month, day.day, 9, 30, tzinfo=CN)
    morning = [d + timedelta(minutes=i) for i in range(0 if include_0930 else 1,121)]
    afternoon = [d.replace(hour=13,minute=1) + timedelta(minutes=i)
                 for i in range(120)]
    return morning + afternoon


class PaidIncrementalContractTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        self.paid = home / "paid" / "2026-09.parquet"
        self.inc = home / "generated" / "2026-11.parquet"
        self.paid.parent.mkdir()
        self.inc.parent.mkdir()

    def write(self,path,day,*,include_0930,duplicate=False):
        g=grid(day,include_0930=include_0930)
        if duplicate:
            g.append(g[-1])
        pq.write_table(pa.table({
            "ts":pa.array([int(t.timestamp()*1000) for t in g],type=pa.int64()),
            "symbol":pa.array(["SH600000"]*len(g),type=pa.string()),
            "volume":pa.array([1.]*len(g),type=pa.float64()),
            "amount":pa.array([100.]*len(g),type=pa.float64()),
        }),path)

    def test_01_real_paid_241_vs_incremental_240_is_conflict(self):
        self.write(self.paid,DAY,include_0930=True)
        self.write(self.inc,NEW_DAY,include_0930=False)
        result=G.compare(self.paid,DAY,self.inc,NEW_DAY,
                         expected_reference_stocks=1)
        self.assertEqual(result["status"],G.CONFLICT)
        self.assertFalse(result["bar_count_and_opening_label_profile_match"])
        self.assertEqual(result["purchased_reference_bar_count_histogram"],{241:1})
        self.assertEqual(result["incremental_bar_count_histogram"],{240:1})
        self.assertFalse(result["minute_business_compatibility_certified"])
        self.assertFalse(result["remediation_authorized"])

    def test_02_matching_241_shapes_are_not_provider_certification(self):
        self.write(self.paid,DAY,include_0930=True)
        self.write(self.inc,NEW_DAY,include_0930=True)
        result=G.compare(self.paid,DAY,self.inc,NEW_DAY)
        self.assertEqual(result["status"],G.MATCH)
        self.assertTrue(result["bar_count_and_opening_label_profile_match"])
        self.assertFalse(result["minute_business_compatibility_certified"])
        self.assertFalse(result["purchased_09_30_auction_trades_source_certified"])

    def test_03_unexpected_purchased_reference_stock_count_denied(self):
        self.write(self.paid,DAY,include_0930=True)
        self.write(self.inc,NEW_DAY,include_0930=False)
        with self.assertRaisesRegex(G.ContractError,"PREVIOUSLY_ACCEPTED_PAID_REFERENCE_CHANGED"):
            G.compare(self.paid,DAY,self.inc,NEW_DAY,
                      expected_reference_stocks=5650)

    def test_04_duplicate_candidate_minute_timestamp_denied(self):
        self.write(self.paid,DAY,include_0930=True)
        self.write(self.inc,NEW_DAY,include_0930=False,duplicate=True)
        with self.assertRaisesRegex(G.ContractError,"INCREMENTAL_REPEATED_MINUTE_KEYS"):
            G.compare(self.paid,DAY,self.inc,NEW_DAY)

    def test_05_same_file_denied(self):
        self.write(self.paid,DAY,include_0930=True)
        with self.assertRaisesRegex(G.ContractError,"MUST_BE_DIFFERENT_FILES"):
            G.compare(self.paid,DAY,self.paid,DAY)

    def test_06_missing_candidate_day_denied(self):
        self.write(self.paid,DAY,include_0930=True)
        self.write(self.inc,NEW_DAY,include_0930=False)
        with self.assertRaisesRegex(ValueError,"PURCHASED_MONTH_FILE_NAME_NOT_IN_DAY_SCOPE"):
            G.compare(self.paid,DAY,self.inc,date(2026,10,12))

    def test_07_no_file_changes(self):
        from hashlib import sha256
        self.write(self.paid,DAY,include_0930=True)
        self.write(self.inc,NEW_DAY,include_0930=False)
        before=[sha256(p.read_bytes()).hexdigest() for p in (self.paid,self.inc)]
        G.compare(self.paid,DAY,self.inc,NEW_DAY)
        after=[sha256(p.read_bytes()).hexdigest() for p in (self.paid,self.inc)]
        self.assertEqual(after,before)


if __name__ == "__main__":
    unittest.main()
