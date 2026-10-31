"""Fictional-only contracts for 83 private H5-only mixed stockday read audit."""
import importlib.util
import unittest
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "private_mixed_83_readonce_test",
    HERE.parent / "tools" / "audit-private-combined-83-mixed-query-once-readonly.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def sample():
    """One 2016 + 82 2026 fictional keys with identical private stage layout."""
    selected=set()
    rows=[]
    for symbol, day in (
        [("SH600000", "2016-09-30")] +
        [(f"SH600{i:03d}", "2026-04-08") for i in range(1, 83)]):
        d=date.fromisoformat(day)
        selected.add((symbol, int(day.replace("-", ""))*10000))
        stamp=int(datetime(d.year,d.month,d.day,tzinfo=A.PRE.MIXED.CORE.UTC8).timestamp()*1000)
        rows.append({"ts":stamp,"symbol":symbol[2:]+".XSHG",
                     "open":10.0,"high":11.0,"low":9.0,"close":10.0,
                     "volume":100.0,"amount":1200.0,
                     "source":"hikyuu_h5_mixed_day_candidate"})
    return selected,rows


class PrivateMixedOnePassTests(unittest.TestCase):
    def test_all_83_local_candidate_reads_and_year_counts(self):
        expected, rows=sample()
        self.assertEqual(A.audit_mixed_rows(expected,rows),{"2016":1,"2026":82})

    def test_reject_missing_private_stage_row(self):
        expected,rows=sample()
        with self.assertRaisesRegex(ValueError,"83-row"):
            A.audit_mixed_rows(expected,rows[:-1])

    def test_reject_missing_expected_private_key(self):
        expected,rows=sample()
        expected.pop()
        with self.assertRaisesRegex(ValueError,"83-key"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_duplicate_stage_stockday(self):
        expected,rows=sample()
        rows[1]=dict(rows[0])
        with self.assertRaisesRegex(ValueError,"duplicate"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_wrong_stage_source(self):
        expected,rows=sample()
        rows[0]["source"]="wrong"
        with self.assertRaisesRegex(ValueError,"Bad/duplicate"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_stage_wrong_ohlc_geometry(self):
        expected,rows=sample()
        rows[0]["high"]=1.0
        with self.assertRaisesRegex(ValueError,"geometry"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_staged_wrong_date(self):
        expected,rows=sample()
        rows[0]["ts"]+=86400000
        with self.assertRaisesRegex(ValueError,"exact selected key"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_expected_quarantined_date(self):
        expected,rows=sample()
        expected.remove(("SH600001",202604080000))
        expected.add(("SH600001",202607160000))
        with self.assertRaisesRegex(ValueError,"quarantined"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_expected_whole_date_overlap(self):
        expected,rows=sample()
        expected.remove(("SH600001",202604080000))
        expected.add(("SH600001",202610080000))
        with self.assertRaisesRegex(ValueError,"Full-day overlap"):
            A.audit_mixed_rows(expected,rows)

    def test_reject_bad_native_timestamp_suffix(self):
        with self.assertRaisesRegex(ValueError,"Noncanonical"):
            A.key_date(202604081234)

    def test_reject_mixed_year_distribution_change(self):
        expected,rows=sample()
        # Rewrite one 2026 candidate to a new 2016 date, keep 83 distinct keys
        before=("SH600002",202604080000)
        expected.remove(before)
        expected.add(("SH600002",201609290000))
        for item in rows:
            if item["symbol"]=="600002.XSHG":
                d=date(2016,9,29)
                item["ts"]=int(datetime(d.year,d.month,d.day,
                          tzinfo=A.PRE.MIXED.CORE.UTC8).timestamp()*1000)
        with self.assertRaisesRegex(ValueError,"year distribution"):
            A.audit_mixed_rows(expected,rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
