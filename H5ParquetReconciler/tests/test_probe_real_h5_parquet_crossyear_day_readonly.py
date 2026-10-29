"""Two fictional H5/Parquet months, four stock-days, source read-only."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "real_crossyear_daily_probe_under_test",
    HERE.parent/"tools"/"probe-real-h5-parquet-crossyear-day-readonly.py")
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


class CrossyearSyntheticStockDayTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        import h5py
        import numpy as np
        self.pa,self.pq,self.h5py,self.np=pa,pq,h5py,np
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.pqroot=self.root/"AllCycleAStockData"
        self.daypath=self.pqroot/"day"
        self.daypath.mkdir(parents=True)
        self.h5root=self.root/"HikyuuData"
        self.h5root.mkdir()
        self.reports=self.root/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.raw=self.reports/"prior-raw-day.json"
        self.native=self.reports/"prior-native-day.json"
        self.heldout=self.reports/"prior-sep28-29.json"
        self.dest=self.reports/"crossyear-day-v1.json"
        p=patch.object(T.AUDIT,"REPORTS",self.reports)
        p.start();self.addCleanup(p.stop)
        self.write_sources()
        self.write_priors()

    def write_priors(self):
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
            "format":T.HELD.NATIVE.FORMAT,
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
        self.heldout.write_text(json.dumps({
            "format":T.HELD.FORMAT,
            "holdout_days":list(T.HELD.DAYS),
            "prior_discovery_date_excluded":"2026-09-30",
            "observations_independent_of_discovery_date":True,
            "previous_SAFE_sha256":T.HELD.verify_chain(self.raw,self.native),
            "h5_raw_day_records_read":4,
            "original_parquet_or_h5_modified":False,
            "raw_ohlcva_or_h5_integer_values_exported":False,
            "native_decoder_consistency_not_retested_on_heldout_dates":True,
            "holdout_native_cpp_kdata_executed":False,
            "vendor_volume_physical_unit_certified":False,
            "vendor_amount_physical_unit_certified":False,
            "sample_factor_generalization_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "aggregate":{
                "heldout_stock_days_compared":4,
                "volume_candidate_factor100_matched":4,
                "amount_candidate_factor1000_matched":4,
                "nonzero_positive_pairs":{"volume":4,"amount":4},
                "zero_pairs":{"volume":0,"amount":0},
                "price_fields_within_tolerance":{
                    "open":4,"high":4,"low":4,"close":4},
            },
            "per_holdout_date_diagnostic":{
                day:{
                    "stock_days_compared":2,
                    "candidate_volume_raw_h5_times100_matched":2,
                    "candidate_amount_raw_h5_times1000_matched":2,
                    "quantity_positive_nonzero_pairs":{"volume":2,"amount":2}
                } for day in T.HELD.DAYS
            }
        }),encoding="utf-8")

    def write_sources(self,wrong_amount=False,both_zero=False):
        pa,pq,h5py,np=self.pa,self.pq,self.h5py,self.np
        kind=np.dtype([
            ("datetime","<u8"),("openPrice","<u4"),("highPrice","<u4"),
            ("lowPrice","<u4"),("closePrice","<u4"),("transCount","<u8"),
            ("transAmount","<u8")
        ])
        monthly={name:[] for _,name in T.SAMPLES}
        for symbol,seed in (("SH600000",1),("SZ000001",2)):
            h5=np.zeros(4,dtype=kind)
            h5["datetime"]=[202509300000,202608240000,
                            202609300000,202610080000]
            for index,(day,month) in enumerate(T.SAMPLES):
                raw={
                    "openPrice":12000+seed*100+index*50,
                    "highPrice":12200+seed*100+index*50,
                    "lowPrice":11900+seed*100+index*50,
                    "closePrice":12100+seed*100+index*50,
                    "transCount":220+seed*10+index*20,
                    "transAmount":320+seed*20+index*50
                }
                if both_zero and index==1 and seed==2:
                    raw["transCount"]=0
                for field,val in raw.items():
                    h5[field][index]=val
                volume=float(raw["transCount"])*100
                amount=float(raw["transAmount"])*1000
                if wrong_amount and index==0 and seed==2:
                    amount*=1.25
                monthly[month].append({
                    "ts":int(datetime.fromisoformat(day).replace(
                        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000),
                    "symbol":"600000.XSHG" if seed==1 else "000001.XSHE",
                    "open":float(raw["openPrice"])/1000,
                    "high":float(raw["highPrice"])/1000,
                    "low":float(raw["lowPrice"])/1000,
                    "close":float(raw["closePrice"])/1000,
                    "volume":volume,"amount":amount
                })
            path=self.h5root/(symbol[:2].lower()+"_day.h5")
            with h5py.File(path,"w") as handle:
                handle.create_group("data").create_dataset(symbol,data=h5)
        for month,rows in monthly.items():
            if month=="day/2025.parquet":
                # Historic paid year is ONE 12-rowgroup annual file, not a
                # nonexistent day/2025-09.parquet monthly file. One small
                # synthetic rowgroup per calendar month tests footer pruning.
                for m in range(1,13):
                    if m==9:
                        continue
                    for alias in ("600000.XSHG","000001.XSHE"):
                        rows.append({
                            "ts":int(datetime(2025,m,15,tzinfo=timezone(
                                timedelta(hours=8))).timestamp()*1000),
                            "symbol":alias,
                            "open":10.0,"high":10.1,"low":9.9,
                            "close":10.05,"volume":200.0,"amount":5000.0
                        })
                rows.sort(key=lambda r:r["ts"])
            data={
                "ts":pa.array([row["ts"] for row in rows],type=pa.int64()),
                "symbol":pa.array([row["symbol"] for row in rows],type=pa.string())
            }
            for field in ("open","high","low","close","volume","amount"):
                data[field]=pa.array([row[field] for row in rows],
                                     type=pa.float64())
            pq.write_table(pa.table(data),self.pqroot/month,
                           row_group_size=2)

    def run_it(self):
        return T.run(self.pqroot,self.h5root,self.raw,
                     self.native,self.heldout,self.dest)

    def test_four_crossyear_out_of_sample_stock_days_all_match(self):
        sources=list(self.daypath.glob("*.parquet"))+list(self.h5root.glob("*.h5"))
        original={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        result=self.run_it()
        agg=result["crossyear_aggregate"]
        self.assertEqual(agg["stock_days_compared"],4)
        self.assertEqual(agg["volume_candidate_raw_h5_times100_matched"],4)
        self.assertEqual(agg["amount_candidate_raw_h5_times1000_matched"],4)
        self.assertEqual(agg["per_field_price_tolerance_matches"],
                         {"open":4,"high":4,"low":4,"close":4})
        self.assertEqual(result["source_parquet_files_read"],2)
        self.assertEqual(result["source_parquet_layouts"],
                         {"2025":"annual_footer_pruned","2026":"monthly"})
        self.assertEqual(result["annual_2025_source_total_rows_from_footer"],24)
        self.assertEqual(result["annual_2025_source_rowgroups_from_footer"],12)
        self.assertEqual(result["annual_2025_selected_rowgroups_scanned"],1)
        self.assertEqual(result["source_parquet_total_rows_scanned"],4)
        self.assertEqual(result["raw_h5_day_records_read"],4)
        self.assertFalse(result["native_cpp_h5_decoding_on_crossyear_samples_executed"])
        self.assertFalse(result["universal_factor_across_time_or_periods_certified"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertEqual(original,{p:hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sources})
        text=self.dest.read_text(encoding="utf-8")
        for forbidden in ("SH600000","SZ000001","600000.XSHG","000001.XSHE",
                          "202509300000","202608240000",
                          "HikyuuData","AllCycleAStockData","320000.0"):
            self.assertNotIn(forbidden,text)

    def test_one_date_one_symbol_amount_conflict_stays_visible(self):
        self.write_sources(wrong_amount=True)
        report=self.run_it()
        agg=report["crossyear_aggregate"]
        self.assertEqual(agg["amount_candidate_raw_h5_times1000_matched"],3)
        self.assertEqual(agg["volume_candidate_raw_h5_times100_matched"],4)
        self.assertEqual(report["per_sample_day"]["2025-09-30"]
                         ["candidate_amount_raw_h5_times1000_matched"],1)
        self.assertEqual(report["per_sample_day"]["2026-08-24"]
                         ["candidate_amount_raw_h5_times1000_matched"],2)

    def test_zero_pair_does_not_count_as_factor_support(self):
        self.write_sources(both_zero=True)
        result=self.run_it()["crossyear_aggregate"]
        self.assertEqual(result["volume_candidate_raw_h5_times100_matched"],3)
        self.assertEqual(result["nonzero_positive_pairs"]["volume"],3)
        self.assertEqual(result["both_zero_pairs"]["volume"],1)

    def test_invalid_previous_heldout_matching_claim_rejected(self):
        original=json.loads(self.heldout.read_text(encoding="utf-8"))
        cases=(("volume_candidate_factor100_matched",3),
               ("amount_candidate_factor1000_matched",3))
        for key,val in cases:
            with self.subTest(key=key):
                copy=json.loads(json.dumps(original))
                copy["aggregate"][key]=val
                self.heldout.write_text(json.dumps(copy),encoding="utf-8")
                try:
                    with self.assertRaisesRegex(
                            ValueError,"prerequisite heldout SAFE not qualified"):
                        self.run_it()
                    self.assertFalse(self.dest.exists())
                finally:
                    self.heldout.write_text(json.dumps(original),encoding="utf-8")
                self.assertEqual(
                    set(T.verified_sources(self.raw,self.native,self.heldout)),
                    {"real_raw_stock_day","real_native_stock_day","same_month_heldout"})

    def test_prior_native_must_be_real_complete_and_uncertified(self):
        proof=json.loads(self.native.read_text(encoding="utf-8"))
        for key,val in (("native_status","runtime_unavailable"),
                        ("ready_for_full_market_mirror",True)):
            with self.subTest(key=key):
                doc=dict(proof);doc[key]=val
                self.native.write_text(json.dumps(doc),encoding="utf-8")
                try:
                    with self.assertRaises(ValueError):
                        self.run_it()
                finally:
                    self.native.write_text(json.dumps(proof),encoding="utf-8")
        self.assertFalse(self.dest.exists())

    def test_malformed_prior_safe_or_outside_reports_refused(self):
        away=self.root/"outside.json"
        away.write_text(self.heldout.read_text(encoding="utf-8"),encoding="utf-8")
        with self.assertRaises(ValueError):
            T.run(self.pqroot,self.h5root,self.raw,self.native,away,self.dest)
        self.heldout.write_text("{not-json",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"invalid JSON"):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_duplicate_selected_2025_annual_key_across_rowgroups_rejected(self):
        # Annual 2025 Parquet is sorted by day. data.slice(0,1) would clone
        # January rather than the held-out September 30 target and MUST NOT
        # be treated as evidence of an invalid September target key.
        file=self.pqroot/"day"/"2025.parquet"
        data=self.pq.read_table(file)
        target=int(datetime(2025,9,30,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        indices=[i for i,(timestamp,symbol) in enumerate(zip(
                    data["ts"].to_pylist(),data["symbol"].to_pylist()))
                 if timestamp==target and symbol=="600000.XSHG"]
        self.assertEqual(len(indices),1)
        # Append the September row AFTER December and retain two-row
        # groups. Footer date pruning must select the original September
        # group AND the last additional September-only group; duplicate
        # detection must work across these two discontiguous groups.
        altered=self.pa.concat_tables([data,data.slice(indices[0],1)])
        self.pq.write_table(altered,file,row_group_size=2)
        reader=self.pq.ParquetFile(file)
        try:
            self.assertEqual(reader.metadata.num_row_groups,13)
            selected=[i for i in range(reader.metadata.num_row_groups)
                      if reader.metadata.row_group(i).column(
                          reader.schema_arrow.names.index("ts")
                      ).statistics.min<=target<=reader.metadata.row_group(i)
                          .column(reader.schema_arrow.names.index("ts")
                      ).statistics.max]
            self.assertEqual(len(selected),2)
        finally:
            reader.close()
        with self.assertRaisesRegex(
                ValueError,"Cannot safely inspect bounded annual 2025"):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_unrelated_2025_annual_duplicate_not_scanned_as_target(self):
        # Out-of-window duplicate is deliberately ignored by a date-bounded
        # probe, which must not silently expand to 1.33m annual rows.
        file=self.pqroot/"day"/"2025.parquet"
        data=self.pq.read_table(file)
        self.assertEqual(
            data["ts"][0].as_py(),
            int(datetime(2025,1,15,tzinfo=timezone(
                timedelta(hours=8))).timestamp()*1000))
        self.pq.write_table(
            self.pa.concat_tables([data,data.slice(0,1)]),
            file,row_group_size=2)
        report=self.run_it()
        self.assertEqual(report["crossyear_aggregate"]["stock_days_compared"],4)
        self.assertEqual(report["annual_2025_selected_rowgroups_scanned"],1)
        self.assertFalse(report["ready_for_full_market_mirror"])

    def test_duplicate_selected_2026_monthly_day_key_rejected(self):
        file=self.pqroot/"day"/"2026-08.parquet"
        data=self.pq.read_table(file)
        self.assertEqual(data.num_rows,2)
        self.pq.write_table(
            self.pa.concat_tables([data,data.slice(0,1)]),
            file,row_group_size=2)
        with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_missing_parquet_month_and_missing_h5_never_skipped(self):
        (self.pqroot/"day"/"2025.parquet").unlink()
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_original_h5_missing_rejected(self):
        (self.h5root/"sz_day.h5").unlink()
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_annual_2025_footer_missing_ts_stats_fails_without_scanning(self):
        file=self.pqroot/"day"/"2025.parquet"
        table=self.pq.read_table(file)
        self.pq.write_table(table,file,row_group_size=2,write_statistics=False)
        with self.assertRaisesRegex(
                ValueError,"Cannot safely inspect bounded annual 2025"):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_annual_2025_selected_group_budget_rejects_unprunable(self):
        with patch.object(T,"MAX_YEAR_READ_ROWS",1):
            with self.assertRaisesRegex(
                    ValueError,"Cannot safely inspect bounded annual 2025"):
                self.run_it()
        self.assertFalse(self.dest.exists())

    def test_annual_2025_wrong_year_footer_ts_range_rejected(self):
        file=self.pqroot/"day"/"2025.parquet"
        table=self.pq.read_table(file)
        idx=table.schema.get_field_index("ts")
        values=table["ts"].to_pylist()
        values[0]=int(datetime(2027,1,15,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        table=table.set_column(
            idx,"ts",self.pa.array(values,type=self.pa.int64()))
        self.pq.write_table(table,file,row_group_size=2)
        with self.assertRaisesRegex(
                ValueError,"Cannot safely inspect bounded annual 2025"):
            self.run_it()
        self.assertFalse(self.dest.exists())

    def test_only_new_output_inside_module_reports(self):
        self.dest.write_text("original",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.dest.read_text(encoding="utf-8"),"original")
        with self.assertRaises(ValueError):
            T.run(self.pqroot,self.h5root,self.raw,self.native,
                  self.heldout,self.root/"outside.json")

    def test_crossyear_sample_scope_cannot_include_discovery(self):
        with patch.object(T,"SAMPLES",(
                ("2025-09-30","day/2025.parquet"),
                ("2026-09-30","day/2026-09.parquet"))):
            with self.assertRaisesRegex(ValueError,"dates or months"):
                self.run_it()
        self.assertFalse(self.dest.exists())

    def test_total_scan_budget_guard(self):
        with patch.object(T,"MAX_SCANNED_TOTAL",1):
            with self.assertRaisesRegex(ValueError,"scan budget"):
                self.run_it()
        self.assertFalse(self.dest.exists())

    def test_no_native_or_source_writes_in_main_code(self):
        import inspect
        body=inspect.getsource(T.run)
        self.assertIn("DAY._read_bounded_daily",body)
        self.assertIn("PAIR._read_single_h5",body)
        self.assertNotIn("get_kdata(",body)
        self.assertNotIn("h5py.File(",body)
        self.assertNotIn("sqlite3.connect(",body)
        self.assertNotIn("create_dataset(",body)
        self.assertNotIn("pq.write_table(",body)


if __name__=="__main__":
    unittest.main(verbosity=2)
