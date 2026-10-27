"""Pure synthetic and Arrow checks for month-only Parquet minute key audit."""
import importlib.util
import tempfile
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

SOURCE=(Path(__file__).resolve().parents[1]/"tools"/
        "audit-parquet-month-minute-keys.py")
SPEC=importlib.util.spec_from_file_location("parquet_month_key_audit",SOURCE)
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ=timezone(timedelta(hours=8))


def ms(day,minute):
    dt=datetime(day.year,day.month,day.day,minute//60,minute%60,
                tzinfo=TZ)
    return int(dt.timestamp()*1000)


def stream(day=date(2026,8,24),symbol="600000.XSHG",period="1min"):
    return [(ms(day,t),symbol) for t in M.SLOTS[period]]


class ParquetMonthMinuteKeysTests(unittest.TestCase):
    def test_session_grid_241_48_special_opening(self):
        self.assertEqual(len(M.SLOTS["1min"]),241)
        self.assertEqual(len(M.SLOTS["5min"]),48)
        self.assertIn(570,M.SLOTS["1min"])
        self.assertIn(690,M.SLOTS["1min"])
        self.assertNotIn(780,M.SLOTS["1min"])
        self.assertIn(900,M.SLOTS["1min"])
        self.assertIn(780,M.SLOTS["5min"])

    def test_normal_day_both_periods_fully_complete(self):
        a,ca=M.group_key_statistics(stream(period="1min"),"1min",2026,8)
        b,cb=M.group_key_statistics(stream(period="5min"),"5min",2026,8)
        self.assertEqual(ca["valid_session_rows"],241)
        self.assertEqual(cb["valid_session_rows"],48)
        result=M.grade_month(a,b,2026,8)
        self.assertEqual(result["candidate_stock_day_universe_count"],1)
        self.assertEqual(result["stock_day_summary"][
            "complete_stock_days_in_both_periods"],1)
        self.assertEqual(result["sample_anomalous_stock_days"],[])

    def test_missing_single_minute_is_detected_even_with_full_5min(self):
        target=ms(date(2026,8,24),600)
        rows=[item for item in stream(period="1min") if item[0]!=target]
        a,_=M.group_key_statistics(rows,"1min",2026,8)
        b,_=M.group_key_statistics(stream(period="5min"),"5min",2026,8)
        result=M.grade_month(a,b,2026,8)
        detail=result["sample_anomalous_stock_days"][0]
        self.assertEqual(detail["symbol"],"SH600000")
        self.assertEqual(detail["one_minute"]["source_rows"],240)
        self.assertEqual(detail["one_minute"]["missing_expected_labels"],1)
        self.assertEqual(detail["five_minute"]["missing_expected_labels"],0)

    def test_hypothetical_81_1min_and_17_5min_partial_day(self):
        d=date(2026,2,13)
        a,_=M.group_key_statistics(stream(d,period="1min")[:81],
                                   "1min",2026,2)
        b,_=M.group_key_statistics(stream(d,period="5min")[:17],
                                   "5min",2026,2)
        result=M.grade_month(a,b,2026,2)
        row=result["sample_anomalous_stock_days"][0]
        self.assertEqual(row["one_minute"]["missing_expected_labels"],160)
        self.assertEqual(row["five_minute"]["missing_expected_labels"],31)
        self.assertFalse(result["examples_are_truncated"])

    def test_duplicate_and_unexpected_session_key_are_separate(self):
        d=date(2026,2,13)
        raw=stream(d,period="1min")
        raw.extend((raw[0],(ms(d,780),"600000.XSHG")))
        a,stats=M.group_key_statistics(raw,"1min",2026,2)
        b,_=M.group_key_statistics(stream(d,period="5min"),"5min",2026,2)
        self.assertEqual(stats["duplicate_session_labels"],1)
        self.assertEqual(stats["unexpected_session_labels"],1)
        row=M.grade_month(a,b,2026,2)["sample_anomalous_stock_days"][0]
        self.assertEqual(row["one_minute"]["duplicate_expected_labels"],1)
        self.assertEqual(row["one_minute"]["unexpected_session_labels"],1)

    def test_bad_timestamp_outside_month_symbol_filter(self):
        d=date(2026,8,24)
        raw=[(ms(d,570),"600000.XSHG"),
             (ms(date(2026,7,24),570),"600000.XSHG"),
             (ms(d,575),"bad"),
             (12345,"600000.XSHG"),
             (ms(d,570),"000001.XSHG")]
        a,c=M.group_key_statistics(raw,"5min",2026,8,"a-share-candidate")
        self.assertEqual(len(a),1)
        for name in ("outside_month","unrecognized_symbol","bad_timestamp",
                     "excluded_non_candidate_symbol"):
            self.assertEqual(c[name],1)

    def test_example_truncation_and_month_bounds(self):
        d=date(2026,8,24)
        a,_=M.group_key_statistics([
            (ms(d,570),"600000.XSHG"),(ms(d,570),"000001.XSHE")],
            "1min",2026,8)
        b,_=M.group_key_statistics([],"5min",2026,8)
        result=M.grade_month(a,b,2026,8,limit=1)
        self.assertEqual(result["candidate_stock_day_universe_count"],2)
        self.assertTrue(result["examples_are_truncated"])
        self.assertEqual(M.month_edges(2026,2)[1],date(2026,3,1))
        with self.assertRaises(ValueError):
            M.month_edges(2026,13)

    def test_real_synthetic_arrow_parquet_reads_key_columns_and_budget(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow missing")
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"stock"
            folder=root/"AllCycleAStockData"/"1min"
            folder.mkdir(parents=True)
            rows=[{"ts":ts,"symbol":symbol,"open":10.0,"volume":1.0}
                  for ts,symbol in stream(date(2026,2,13),period="1min")[:3]]
            pq.write_table(pa.Table.from_pylist(rows),
                           folder/"2026-02.parquet",row_group_size=2)
            with self.assertRaisesRegex(ValueError,"exceeds --max-candidate-rows"):
                M.scan_period(root,2026,2,"1min","all",2,1000)
            a,stats=M.scan_period(root,2026,2,"1min","all",10,1000)
            self.assertEqual(stats["projected_key_rows_read"],3)
            self.assertEqual(stats["key_classification"]["valid_session_rows"],3)
            self.assertFalse(stats["prices_volumes_amounts_read"])
            self.assertEqual(len(a),1)


if __name__=="__main__":
    unittest.main()
