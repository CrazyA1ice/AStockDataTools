"""Synthetic-only original-purchased Parquet bar-count audit regression tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_purchased_1min_bars_readonly as A

CN = timezone(timedelta(hours=8))
DAY = date(2026, 9, 30)
BASE = datetime(2026, 9, 30, 9, 30, tzinfo=CN)
REGULAR = ([BASE + timedelta(minutes=i) for i in range(1, 121)] +
           [BASE.replace(hour=13,minute=1) + timedelta(minutes=i)
            for i in range(120)])


class PurchasedMinuteBarCountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "2026-09.parquet"

    def _write(self, data):
        pq.write_table(pa.table({
            "ts": pa.array([int(ts.timestamp()*1000) for _,ts,_,_ in data],
                           type=pa.int64()),
            "symbol": pa.array([s for s,_,_,_ in data], type=pa.string()),
            "volume": pa.array([v for _,_,v,_ in data], type=pa.float64()),
            "amount": pa.array([v for _,_,_,v in data], type=pa.float64()),
        }),self.path)

    def test_01_240_without_0930_is_not_proof_of_auction_absence(self):
        self.assertEqual(len(REGULAR),240)
        self._write([("SH600000",ts,1.,20.) for ts in REGULAR])
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["stock_days_240_bars"],1)
        self.assertEqual(out["stocks_with_0930_label"],0)
        self.assertEqual(out["stocks_with_0931_label"],1)
        self.assertFalse(out["auction_trades_included_in_first_bar_certified"])
        self.assertFalse(out["purchased_parquet_modified"])

    def test_02_241_with_nonzero_0930_record(self):
        self._write([("SH600000",BASE,3.,30.)]+
                    [("SH600000",ts,1.,20.) for ts in REGULAR])
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["stock_days_241_bars"],1)
        self.assertEqual(out["0930_rows_with_positive_volume_and_amount"],1)
        self.assertFalse(out["auction_raw_bids_or_ticks_observed"])

    def test_03_241_zero_placeholder_is_not_positive_auction(self):
        self._write([("SH600000",BASE,0.,0.)]+
                    [("SH600000",ts,1.,20.) for ts in REGULAR])
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["stock_days_241_bars"],1)
        self.assertEqual(out["0930_rows_with_zero_volume_and_amount"],1)

    def test_04_two_stock_histogram_is_not_file_average(self):
        rows=[("SH600000",t,1.,20.) for t in REGULAR]
        rows += [("SZ000001",BASE,2.,20.)]+[
            ("SZ000001",t,1.,20.) for t in REGULAR]
        self._write(rows)
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["per_stock_day_bar_count_histogram"],
                         {240:1,241:1})
        self.assertEqual(out["matching_rows_for_day"],481)
        self.assertEqual(out["stock_days_observed"],2)

    def test_05_only_requested_trading_day_and_no_source_mutation(self):
        self._write([("SH600000",BASE,2.,20.),
                     ("SH600000",BASE - timedelta(days=1),2.,20.)])
        before=sha256(self.path.read_bytes()).hexdigest()
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["matching_rows_for_day"],1)
        self.assertEqual(out["stock_days_other_bar_counts"],1)
        self.assertEqual(before,sha256(self.path.read_bytes()).hexdigest())

    def test_06_invalid_partition_name_refused(self):
        self._write([("SH600000",BASE,2.,20.)])
        with self.assertRaisesRegex(ValueError,"PURCHASED_MONTH_FILE_NAME"):
            A.inspect(self.path, date(2026,8,31))

    def test_07_nullable_0930_volume_pair_reported_unverified(self):
        self._write([("SH600000",BASE,None,10.)])
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["0930_rows_with_unknown_or_unpaired_volume_amount"],1)

    def test_08_timezone_outside_safe_bound_denied(self):
        self._write([("SH600000",BASE,2.,20.)])
        with self.assertRaisesRegex(ValueError,"TIMEZONE_OFFSET_INVALID"):
            A.inspect(self.path,DAY,timezone_hours=99)


    def test_09_duplicate_0930_key_is_reported_not_confused_with_auction(self):
        rows=[("SH600000",t,1.,10.) for t in REGULAR]
        rows.append(("SH600000",REGULAR[0],1.,10.))
        self._write(rows)
        out=A.inspect(self.path,DAY)
        self.assertEqual(out["stock_days_241_bars"],1)
        self.assertEqual(out["duplicate_stock_timestamp_rows"],1)
        self.assertFalse(out["all_symbol_timestamp_keys_unique"])
        self.assertEqual(out["stocks_with_0930_label"],0)

    def test_10_no_matching_day_fails_closed(self):
        self._write([("SH600000",BASE-timedelta(days=1),1.,10.)])
        with self.assertRaisesRegex(
                ValueError,"PURCHASED_DAY_NOT_OBSERVED_OR_TIMESTAMP_UNVERIFIED"):
            A.inspect(self.path,DAY)


if __name__ == "__main__":
    unittest.main()
