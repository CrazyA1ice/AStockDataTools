"""Synthetic Parquet-only direct query regressions; no purchased files."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

SRC=(Path(__file__).resolve().parents[1]/"tools"/
     "query-parquet-primary-readonly.py")
SPEC=importlib.util.spec_from_file_location("query_purchased_parquet",SRC)
Q=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)
TZ=timezone(timedelta(hours=8))


def timestamp(stamp):
    return int(datetime.strptime(stamp,"%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp()*1000)


class DirectPurchasedParquetQueryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)/"stock"
        (self.root/"AllCycleAStockData").mkdir(parents=True)

    def write(self,period,name,rows,row_group_size=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable")
        dest=self.root/"AllCycleAStockData"/period/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows),str(dest),
                       row_group_size=row_group_size)
        return dest

    def row(self,stamp,symbol="600000.XSHG",volume=2.0,high=10.5):
        return {"ts":timestamp(stamp),"symbol":symbol,
                "open":10.0,"high":high,"low":9.0,"close":10.2,
                "volume":volume,"amount":volume*10.1}

    def test_daily_0800_is_preserved_and_day_label_is_correct(self):
        self.write("day","2026-09.parquet",[
            self.row("2026-09-30 08:00"),self.row("2026-09-29 08:00")])
        report=Q.query_bars(self.root,"SH600000","day",
                            "2026-09-30","2026-09-30")
        self.assertEqual(len(report["bars"]),1)
        row=report["bars"][0]
        self.assertEqual(row["source_beijing_time"],"2026-09-30 08:00")
        self.assertEqual(row["normalized_query_label"],"2026-09-30")
        self.assertEqual(row["amount"],20.2)
        self.assertEqual(row["period"],"day")
        self.assertIn("2026-09.parquet",row["source_file_relative_path"])

    def test_one_minute_0930_special_source_timestamp_preserved(self):
        self.write("1min","2026-09.parquet",[
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:31"),
            self.row("2026-09-30 15:00"),
            self.row("2026-09-29 09:30")])
        report=Q.query_bars(self.root,"SH600000","1min",
                            "2026-09-30","2026-09-30")
        self.assertEqual([b["source_beijing_time"][-5:] for b in
                          report["bars"]],["09:30","09:31","15:00"])
        self.assertIn("separate_0930",report["safe_summary"][
            "time_label_policy"])

    def test_five_minute_labels_not_artificially_shifted(self):
        self.write("5min","2026-09.parquet",[
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 14:55")])
        report=Q.query_bars(self.root,"SH600000","5min",
                            "2026-09-30","2026-09-30")
        self.assertEqual(report["bars"][0]["source_beijing_time"][-5:],
                         "09:30")
        self.assertEqual(report["bars"][-1]["source_beijing_time"][-5:],
                         "14:55")
        self.assertEqual(report["safe_summary"]["time_label_policy"],
                         "five_minute_start_label")

    def test_per_period_preflight_budget_fails_before_bar_read(self):
        self.write("1min","2026-09.parquet",[
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:31"),
            self.row("2026-09-30 09:32")],row_group_size=2)
        with self.assertRaisesRegex(ValueError,
                                    "exceeds --max-candidate-rows"):
            Q.query_bars(self.root,"SH600000","1min",
                         "2026-09-30","2026-09-30",
                         max_candidate_rows=1)

    def test_duplicate_source_timestamp_for_target_stock_fails_closed(self):
        self.write("1min","2026-09.parquet",[
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:30")],row_group_size=1)
        with self.assertRaisesRegex(ValueError,"Duplicate source timestamp"):
            Q.query_bars(self.root,"SH600000","1min",
                         "2026-09-30","2026-09-30")

    def test_missing_symbol_is_empty_not_fabricated(self):
        self.write("5min","2026-09.parquet",[
            self.row("2026-09-30 09:30",symbol="000001.XSHE")])
        report=Q.query_bars(self.root,"SH600000","5min",
                            "2026-09-30","2026-09-30")
        self.assertEqual(report["bars"],[])
        self.assertEqual(report["safe_summary"]["matching_bar_count"],0)
        self.assertIsNone(report["safe_summary"][
            "first_matching_raw_beijing_label"])

    def test_invalid_geometry_fails_not_silently_fixed(self):
        self.write("day","2026-09.parquet",[
            self.row("2026-09-30 08:00",high=9.3)])
        with self.assertRaisesRegex(ValueError,"Invalid source OHLCVA"):
            Q.query_bars(self.root,"SH600000","day",
                         "2026-09-30","2026-09-30")

    def test_guard_bshare_range_and_result_count(self):
        for sym in ("SZ200019","SH000001","bad","SZ200706"):
            with self.subTest(symbol=sym),self.assertRaises(ValueError):
                Q.request_dates(sym,"1min","2026-09-30","2026-09-30",
                                100,100)
        with self.assertRaisesRegex(ValueError,"1..31 days"):
            Q.request_dates("SH600000","day","2026-08-01",
                            "2026-09-30",100,100)
        self.write("1min","2026-09.parquet",[
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:31")])
        with self.assertRaisesRegex(ValueError,"exceed --max-result-bars"):
            Q.query_bars(self.root,"SH600000","1min",
                         "2026-09-30","2026-09-30",
                         max_result_bars=1)

    def test_safe_summary_omits_licensed_ohlcva(self):
        self.write("day","2026-09.parquet",[
            self.row("2026-09-30 08:00")])
        import json
        report=Q.query_bars(self.root,"SH600000","day",
                            "2026-09-30","2026-09-30")
        serial=json.dumps(report["safe_summary"])
        self.assertNotIn('"open": 10',serial)
        self.assertNotIn('"volume": 2',serial)
        self.assertNotIn('"amount": 20.2',serial)
        self.assertIn('"source_market_files_modified": false',serial)
        self.assertIn('"no_raw_ohlcva_in_safe_summary": true',serial)
        self.assertEqual(report["safe_summary"]["matching_bar_count"],1)


if __name__=="__main__":
    unittest.main()
