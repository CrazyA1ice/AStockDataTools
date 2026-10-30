"""No live market data: synthetic immutable private Parquet snapshot reader tests."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "test_private_unified_snapshot_verified_reader",
    HERE.parent/"tools"/"read-private-unified-day-parquet-snapshot.py")
R=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def stamp(month,day):
    return int(datetime(2026,month,day,tzinfo=R.UTC8).timestamp()*1000)


def fake_rows():
    return [
      {"ts":stamp(9,30),"trading_date":"2026-09-30","symbol":"SH600000",
       "open":10.1,"high":10.2,"low":10.0,"close":10.15,
       "volume":1300.0,"amount":150000.25,"value_source":"purchased_parquet"},
      {"ts":stamp(10,8),"trading_date":"2026-10-08","symbol":"SH600000",
       "open":10.2,"high":10.3,"low":10.1,"close":10.25,
       "volume":1600.0,"amount":155000.0,
       "value_source":"private_hikyuu_h5_gap_candidate"},
      {"ts":stamp(10,8),"trading_date":"2026-10-08","symbol":"SZ000001",
       "open":20.2,"high":20.3,"low":20.1,"close":20.25,
       "volume":2300.0,"amount":320000.75,
       "value_source":"private_hikyuu_h5_gap_candidate"},
    ]


class VerifiedPrivateSnapshotTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa,self.pq=pa,pq
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.module=Path(self.temp.name)/"H5ParquetReconciler"
        self.work=self.module/"work"
        self.snapshots=self.work/"unified_parquet"/"snapshots"
        self.reports=self.module/"reports"
        self.folder=self.snapshots/"snapshot_012345abcdef"
        self.folder.mkdir(parents=True)
        self.reports.mkdir()
        self.pqfile=self.folder/"day.parquet"
        self.manifest_file=self.folder/"manifest.json"
        self.safe_file=self.reports/"private-unified-day-snapshot.json"
        self.out=self.reports/"read-safe.json"
        for obj,attr,value in (
            (R,"MODULE",self.module),(R,"WORK",self.work),
            (R,"ROOT",self.snapshots),(R,"REPORTS",self.reports)):
            p=patch.object(obj,attr,value)
            p.start()
            self.addCleanup(p.stop)
        self.rows=fake_rows()
        self._write_good()

    def _write_good(self):
        self.pq.write_table(
            self.pa.Table.from_pylist(self.rows,schema=R.expected_schema(self.pa)),
            self.pqfile,compression="zstd")
        self.manifest={
            "format":R.FORMAT,"state":R.PRIVATE_STATE,
            "period":"day","private_file":"day.parquet",
            "date_window":["2026-09-30","2026-10-08"],
            "origin_private_version_sha256":"a"*64,
            "rows":3,"symbol_count":2,"purchased_rows":1,
            "h5_gap_candidate_rows":2,
            "private_parquet_sha256":R.sha256_file(self.pqfile),
            "all_written_values_roundtrip_exactly":True,
            "private_h5_gap_units_remain_unverified_candidate":True,
            "licensed_parquet_to_native_h5_amount_lossless_certified":False,
            "source_market_files_written":False,
            "production_query_route_switched":False,
            "production_h5_mirror_created":False,
            "private_active_overlay_pointer_changed":False,
            "per_symbol_counts":{
              "SH600000":{"purchased_bars":1,"private_bars":1,"returned_bars":2},
              "SZ000001":{"purchased_bars":0,"private_bars":1,"returned_bars":1},
            },
        }
        self.manifest_file.write_text(json.dumps(self.manifest),encoding="utf-8")
        self.safe={
            "format":R.FORMAT,"state":R.PRIVATE_STATE,"period":"day",
            "snapshot_relative_path":"work/unified_parquet/snapshots/snapshot_012345abcdef",
            "manifest_sha256":R.sha256_file(self.manifest_file),
            "private_parquet_sha256":R.sha256_file(self.pqfile),
            "origin_private_version_sha256":"a"*64,
            "all_written_values_roundtrip_exactly":True,
            "h5_gap_units_unverified_candidate":True,
            "purchased_parquet_priority_verified":True,
            "original_market_files_modified":False,
            "original_hikyuu_h5_modified":False,
            "production_query_route_switched":False,
            "ready_for_full_market_mirror":False,
            "raw_ohlcva_or_original_source_paths_exported_in_safe":False,
            "row_count":3,"symbol_count":2,
            "purchased_rows":1,"h5_gap_candidate_rows":2,
        }
        self.safe_file.write_text(json.dumps(self.safe),encoding="utf-8")

    def _resign(self):
        self.manifest_file.write_text(json.dumps(self.manifest),encoding="utf-8")
        self.safe["manifest_sha256"]=R.sha256_file(self.manifest_file)
        self.safe["private_parquet_sha256"]=R.sha256_file(self.pqfile)
        self.safe_file.write_text(json.dumps(self.safe),encoding="utf-8")

    def run_it(self,symbols=("SH600000","SZ000001"),first="2026-09-30",last="2026-10-08"):
        return R.read_verified(self.safe_file,list(symbols),first,last,self.out)

    def test_real_arrow_synthetic_parquet_verified_end_to_end_without_original_market(self):
        original={p:R.sha256_file(p) for p in (
            self.pqfile,self.manifest_file,self.safe_file)}
        result=self.run_it()
        safe=result["safe_summary"]
        self.assertEqual(safe["selected_row_count"],3)
        self.assertEqual(safe["selected_purchased_row_count"],1)
        self.assertEqual(safe["selected_h5_gap_candidate_row_count"],2)
        self.assertTrue(safe["snapshot_full_schema_keys_source_counts_and_sha_verified"])
        self.assertTrue(safe["no_live_market_source_freshness_recheck"])
        self.assertTrue(safe["no_raw_ohlcva_in_safe_summary"])
        self.assertTrue(safe["h5_gap_units_remain_unverified_candidate"])
        self.assertEqual(original,{p:R.sha256_file(p) for p in original})
        self.assertEqual(result["bars_by_symbol"]["SH600000"][0]["amount"],150000.25)
        for forbidden in ("150000.25","320000.75","SH600000","SZ000001",
                          "AllCycleAStockData","HikyuuData",str(stamp(9,30))):
            self.assertNotIn(forbidden,self.out.read_text(encoding="utf-8"))
        self.assertFalse((self.work/"unified_parquet"/"active-day-overlay.json").exists())

    def test_selected_subset_is_counted_and_not_exported_as_raw_market(self):
        result=self.run_it(("SZ000001",),"2026-10-08","2026-10-08")
        self.assertEqual(result["safe_summary"]["selected_stock_count"],1)
        self.assertEqual(result["safe_summary"]["selected_row_count"],1)
        self.assertEqual(result["safe_summary"]["selected_purchased_row_count"],0)
        self.assertEqual(result["safe_summary"]["selected_h5_gap_candidate_row_count"],1)
        self.assertEqual(list(result["bars_by_symbol"]),["SZ000001"])

    def test_tampered_parquet_bytes_fail_before_decode(self):
        with self.pqfile.open("ab") as stream:
            stream.write(b"broken append")
        with patch.object(self.pq,"ParquetFile",
                          side_effect=AssertionError("must not decode")):
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_tampered_manifest_bytes_fail_before_decode(self):
        with self.manifest_file.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError,"SHA mismatch"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_rehashed_forged_manifest_counts_still_fail(self):
        self.manifest["purchased_rows"]=2
        self._resign()
        with self.assertRaisesRegex(ValueError,"provenance disagree"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_duplicate_stock_day_detected_even_if_resigned(self):
        self.rows[2]["symbol"]="SH600000"
        self.pq.write_table(
            self.pa.Table.from_pylist(self.rows,schema=R.expected_schema(self.pa)),
            self.pqfile)
        self.manifest["private_parquet_sha256"]=R.sha256_file(self.pqfile)
        self._resign()
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_wrong_source_label_detected_even_if_resigned(self):
        self.rows[1]["value_source"]="faked_unverified_source"
        self.pq.write_table(
            self.pa.Table.from_pylist(self.rows,schema=R.expected_schema(self.pa)),
            self.pqfile)
        self.manifest["private_parquet_sha256"]=R.sha256_file(self.pqfile)
        self._resign()
        with self.assertRaisesRegex(ValueError,"Untrusted private snapshot"):
            self.run_it()

    def test_wrong_date_in_original_source_detected_even_if_resigned(self):
        self.rows[1]["trading_date"]="2026-10-07"
        self.pq.write_table(
            self.pa.Table.from_pylist(self.rows,schema=R.expected_schema(self.pa)),
            self.pqfile)
        self.manifest["private_parquet_sha256"]=R.sha256_file(self.pqfile)
        self._resign()
        with self.assertRaisesRegex(ValueError,"timestamp"):
            self.run_it()

    def test_wrong_arrow_column_type_refused_with_valid_hash(self):
        data=self.pa.Table.from_pylist(
            self.rows,schema=R.expected_schema(self.pa))
        index=data.schema.get_field_index("volume")
        bad=self.pa.array([int(row["volume"]) for row in self.rows],
                          type=self.pa.int64())
        data=data.set_column(index,"volume",bad)
        self.pq.write_table(data,self.pqfile)
        self.manifest["private_parquet_sha256"]=R.sha256_file(self.pqfile)
        self._resign()
        with self.assertRaisesRegex(ValueError,"schema or bounded decode"):
            self.run_it()

    def test_source_drift_during_decode_fails_without_output(self):
        original=R.inspect_rows
        def mutate_after(rows,manifest):
            out=original(rows,manifest)
            with self.pqfile.open("ab") as f:
                f.write(b"after read corruption")
            return out
        with patch.object(R,"inspect_rows",side_effect=mutate_after):
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_malicious_path_or_certified_mirror_safe_refused(self):
        for relative in ("../../outside","work/unified_parquet/snapshots/../outside",
                         "work/unified_parquet/snapshots/snapshot_fake",
                         "work/unified_parquet/snapshots/snapshot_012345abcdef/extra"):
            with self.subTest(relative=relative):
                self.safe["snapshot_relative_path"]=relative
                self.safe_file.write_text(json.dumps(self.safe),encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.run_it()
        self.safe["snapshot_relative_path"]=(
            "work/unified_parquet/snapshots/snapshot_012345abcdef")
        self.safe["ready_for_full_market_mirror"]=True
        self.safe_file.write_text(json.dumps(self.safe),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unqualified"):
            self.run_it()

    def test_external_or_existing_report_and_noncanonical_stock_blocked(self):
        self.out.write_text("existing",encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertEqual(self.out.read_text(),"existing")
        self.out.unlink()
        with self.assertRaises(ValueError):
            R.read_verified(self.safe_file,["SH600000"],"2026-09-30","2026-10-08",
                            Path(self.temp.name)/"unsafe.json")
        for names in (["sh600000"],["SH600000","SH600000"],["AB123456"],[]):
            with self.subTest(names=names):
                with self.assertRaises(ValueError):
                    self.run_it(names)
        with self.assertRaisesRegex(ValueError,"beyond verified"):
            self.run_it(("SH600000",),"2026-09-29","2026-10-08")
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
