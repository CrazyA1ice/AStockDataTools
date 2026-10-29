"""Only small fictional Parquet/H5 with two held-out days; no commercial files."""
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
    "real_holdout_day_unit_probe",
    HERE.parent/"tools"/"probe-real-h5-parquet-heldout-day-factors-readonly.py")
T=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


class HeldoutSyntheticDaysTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        import h5py
        import numpy as np
        self.pa,self.pq,self.h5py,self.np=pa,pq,h5py,np
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.pqroot=self.base/"AllCycleAStockData"
        self.source=self.pqroot/"day"/"2026-09.parquet"
        self.source.parent.mkdir(parents=True)
        self.h5root=self.base/"HikyuuData"
        self.h5root.mkdir()
        self.reports=self.base/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.raw=self.reports/"raw-stock-day-v1.json"
        self.native=self.reports/"real-native-v3.json"
        self.output=self.reports/"heldout-v1.json"
        p=patch.object(T.AUDIT,"REPORTS",self.reports)
        p.start();self.addCleanup(p.stop)
        self.make_sources()
        self.raw.write_text(json.dumps({
            "format":T.PAIR.FORMAT,
            "sample_day":"2026-09-30",
            "two_selected_stock_days_compared":2,
            "h5_raw_day_records_read":2,
            "sources_read_only_no_h5_or_parquet_writes":True,
            "original_market_files_modified":False,
            "ready_for_full_market_mirror":False,
            "parquet_vendor_physical_amount_unit_certified":False,
            "parquet_vendor_physical_volume_unit_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "comparison":{
                "candidate_factor_multiply_raw_h5_record_to_parquet_value":{
                    "volume":{"100":2},"amount":{"1000":2}},
                "raw_h5_price_divided_1000_within_0p005_count":{
                    "open":2,"high":2,"low":2,"close":2},
            }
        }),encoding="utf-8")
        self.native.write_text(json.dumps({
            "format":T.NATIVE.FORMAT,
            "target_day":"2026-09-30",
            "native_status":"native_complete",
            "native_final_phase":"finished",
            "native_last_work_phase":"native_complete",
            "native_matching_stock_day_count":2,
            "all_two_native_h5_real_daily_records_match":True,
            "native_h5_raw_record_decode_evidence_for_two_stock_days":True,
            "native_get_kdata_called":True,
            "original_h5_stat_before_after_unchanged":True,
            "source_h5_or_parquet_modified":False,
            "original_parquet_or_market_sqlite_accessed":False,
            "raw_market_ohlcva_or_timestamp_recorded_in_safe":False,
            "hmac_key_or_digest_recorded_in_safe":False,
            "parquet_vendor_amount_physical_unit_certified":False,
            "parquet_vendor_volume_physical_unit_certified":False,
            "parquet_to_hikyuu_native_units_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
        }),encoding="utf-8")

    def make_sources(self,amount_discrepancy=False,zero_volume=False):
        np,h5py=self.np,self.h5py
        dtype=np.dtype([
            ("datetime","<u8"),("openPrice","<u4"),
            ("highPrice","<u4"),("lowPrice","<u4"),
            ("closePrice","<u4"),("transCount","<u8"),
            ("transAmount","<u8")
        ])
        rows=[]
        for symbol,s in (("SH600000",1),("SZ000001",2)):
            raw=np.zeros(4,dtype=dtype)
            raw["datetime"]=[202609280000,202609290000,
                             202609300000,202610080000]
            for i,day in enumerate(T.DAYS):
                raw["openPrice"][i]=10000+s*100+i*50
                raw["highPrice"][i]=10100+s*100+i*50
                raw["lowPrice"][i]=9900+s*100+i*50
                raw["closePrice"][i]=10050+s*100+i*50
                raw["transCount"][i]=200+s*20+i*10
                raw["transAmount"][i]=400+s*20+i*10
                if zero_volume and i==1 and s==2:
                    raw["transCount"][i]=0
                pq_amount=float(raw["transAmount"][i])*1000
                if amount_discrepancy and i==1 and s==2:
                    pq_amount+=float(raw["transAmount"][i])*150
                rows.append({
                    "ts":int(datetime.fromisoformat(day).replace(
                        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000),
                    "symbol":"600000.XSHG" if s==1 else "000001.XSHE",
                    "open":float(raw["openPrice"][i])/1000,
                    "high":float(raw["highPrice"][i])/1000,
                    "low":float(raw["lowPrice"][i])/1000,
                    "close":float(raw["closePrice"][i])/1000,
                    "volume":float(raw["transCount"][i])*100,
                    "amount":pq_amount,
                })
            path=self.h5root/(symbol[:2].lower()+"_day.h5")
            with h5py.File(path,"w") as file:
                file.create_group("data").create_dataset(symbol,data=raw)
        data={
            "ts":self.pa.array([row["ts"] for row in rows],
                               type=self.pa.int64()),
            "symbol":self.pa.array([row["symbol"] for row in rows],
                                   type=self.pa.string()),
        }
        for field in ("open","high","low","close","volume","amount"):
            data[field]=self.pa.array([row[field] for row in rows],
                                      type=self.pa.float64())
        self.pq.write_table(self.pa.table(data),self.source)

    def run_it(self):
        return T.run(self.pqroot,self.h5root,self.raw,self.native,self.output)

    def test_four_out_of_sample_stock_days_match_without_certifying_units(self):
        sources=[self.source,*self.h5root.glob("*.h5")]
        hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        result=self.run_it()
        self.assertEqual(result["holdout_days"],list(T.DAYS))
        self.assertNotIn("2026-09-30",result["holdout_days"])
        self.assertEqual(result["aggregate"]["heldout_stock_days_compared"],4)
        self.assertEqual(result["aggregate"]["volume_candidate_factor100_matched"],4)
        self.assertEqual(result["aggregate"]["amount_candidate_factor1000_matched"],4)
        self.assertEqual(result["aggregate"]["price_fields_within_tolerance"],
                         {"open":4,"high":4,"low":4,"close":4})
        self.assertEqual(result["h5_raw_day_records_read"],4)
        self.assertEqual(result["source_parquet_month_files_read"],1)
        self.assertFalse(result["holdout_native_cpp_kdata_executed"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertFalse(result["sample_factor_generalization_certified"])
        self.assertEqual(hashes,{p:hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources})
        text=self.output.read_text(encoding="utf-8")
        for excluded in ("SH600000","SZ000001","600000.XSHG","000001.XSHE",
                         "202609280000","202609290000","HikyuuData",
                         "AllCycleAStockData","400000.0"):
            self.assertNotIn(excluded,text)

    def test_other_date_mismatch_is_counted_not_hid(self):
        self.make_sources(amount_discrepancy=True)
        report=self.run_it()
        self.assertEqual(report["aggregate"]["volume_candidate_factor100_matched"],4)
        self.assertEqual(report["aggregate"]["amount_candidate_factor1000_matched"],3)
        self.assertEqual(report["per_holdout_date_diagnostic"]["2026-09-28"]
                         ["candidate_amount_raw_h5_times1000_matched"],2)
        self.assertEqual(report["per_holdout_date_diagnostic"]["2026-09-29"]
                         ["candidate_amount_raw_h5_times1000_matched"],1)
        self.assertFalse(report["licensed_parquet_to_h5_mapping_certified"])

    def test_zero_pair_does_not_create_false_factor_evidence(self):
        self.make_sources(zero_volume=True)
        report=self.run_it()
        self.assertEqual(report["aggregate"]["volume_candidate_factor100_matched"],3)
        self.assertEqual(report["aggregate"]["nonzero_positive_pairs"]["volume"],3)
        self.assertEqual(report["aggregate"]["zero_pairs"]["volume"],1)

    def test_prior_native_must_prove_real_2_of_2_not_merely_called(self):
        doc=json.loads(self.native.read_text(encoding="utf-8"))
        for key,val in (("all_two_native_h5_real_daily_records_match",False),
                        ("native_matching_stock_day_count",1),
                        ("native_status","runtime_unavailable"),
                        ("parquet_to_hikyuu_native_units_certified",True)):
            with self.subTest(key=key):
                altered=dict(doc);altered[key]=val
                self.native.write_text(json.dumps(altered),encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"previous real native"):
                    self.run_it()
                self.assertFalse(self.output.exists())

    def test_previous_raw_h5_factor_must_have_two_positive_hits(self):
        doc=json.loads(self.raw.read_text(encoding="utf-8"))
        doc["comparison"][
            "candidate_factor_multiply_raw_h5_record_to_parquet_value"][
            "volume"]["100"]=1
        self.raw.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Previous real two-source"):
            self.run_it()

    def test_previous_safe_must_be_direct_module_json(self):
        away=self.base/"other.json"
        away.write_text(self.native.read_text(encoding="utf-8"),encoding="utf-8")
        with self.assertRaises(ValueError):
            T.run(self.pqroot,self.h5root,self.raw,away,self.output)
        self.native.write_text("not-json",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Malformed previous"):
            self.run_it()

    def test_missing_real_h5_cannot_claim_heldout_success(self):
        (self.h5root/"sz_day.h5").unlink()
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.output.exists())

    def test_duplicate_purchased_source_day_rejected(self):
        table=self.pq.read_table(self.source)
        duplicate=self.pa.concat_tables([table,table.slice(0,1)])
        self.pq.write_table(duplicate,self.source)
        with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
            self.run_it()
        self.assertFalse(self.output.exists())

    def test_invalid_monthly_float64_schema_rejected(self):
        t=self.pq.read_table(self.source)
        idx=t.schema.get_field_index("volume")
        converted=self.pa.array(t["volume"].to_pylist(),type=self.pa.int64())
        t=t.set_column(idx,"volume",converted)
        self.pq.write_table(t,self.source)
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.output.exists())

    def test_safe_output_must_be_new_json_inside_reports(self):
        self.output.write_text("do not overwrite",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.output.read_text(encoding="utf-8"),"do not overwrite")
        outside=self.base/"outside.json"
        with self.assertRaises(ValueError):
            T.run(self.pqroot,self.h5root,self.raw,self.native,outside)

    def test_cannot_reuse_discovery_date_as_new_heldout_evidence(self):
        self.assertEqual(set(T.DAYS),{"2026-09-28","2026-09-29"})
        self.assertNotIn(T.PAIR.DAY_DATE,T.DAYS)
        original=T.DAYS
        with patch.object(T,"DAYS",("2026-09-28","2026-09-30")):
            with self.assertRaisesRegex(ValueError,"overlaps"):
                self.run_it()
        self.assertFalse(self.output.exists())
        self.assertEqual(T.DAYS,original)

    def test_strict_two_date_bounded_h5_and_parquet_no_writer(self):
        import inspect
        body=inspect.getsource(T.run)
        self.assertIn("DAY._read_bounded_daily",body)
        self.assertIn("PAIR._read_single_h5",body)
        self.assertIn("MAX_TOTAL_SCANNED_ROWS",body)
        self.assertNotIn("h5py.File(",body)
        self.assertNotIn("create_dataset(",body)
        self.assertNotIn("sqlite3.connect(",body)
        self.assertNotIn("write_table(",body)


if __name__=="__main__":
    unittest.main(verbosity=2)
