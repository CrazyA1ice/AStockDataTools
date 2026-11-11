"""Real synthetic purchased Parquet -> original-H5 COPY minute merge test."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import tables

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "actual_purchased_original_h5_minute_copy_merge_synthetic",
    HERE.parent/"tools"/"mirror-asof20261013-purchased-minute-parquet-into-copied-native-h5.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DT=M.MERGE.canonical_dtype(np)
UTC8=timezone(timedelta(hours=8))

def bar(day,time,sym,value=11.125):
    d=datetime.fromisoformat(day+"T"+time).replace(tzinfo=UTC8)
    return (int(d.timestamp()*1000),sym,value)

def parquet(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    arr={
        "ts":pa.array([r[0] for r in rows],type=pa.int64()),
        "symbol":pa.array([r[1] for r in rows],type=pa.string()),
        **{k:pa.array([r[2] for r in rows],type=pa.float64())
           for k in ("open","high","low","close")},
        "volume":pa.array([100.0]*len(rows),type=pa.float64()),
        "amount":pa.array([1000.0]*len(rows),type=pa.float64()),
    }
    pq.write_table(pa.table(arr),path,write_statistics=True,row_group_size=3)
    return path

def native(stamps,prices):
    arr=np.zeros(len(stamps),dtype=DT)
    for idx,(ts,v) in enumerate(zip(stamps,prices)):
        arr[idx]["datetime"]=ts
        for k in ("openPrice","highPrice","lowPrice","closePrice"):
            arr[idx][k]=v
        arr[idx]["transCount"]=1
        arr[idx]["transAmount"]=1
    return arr

def h5(path,stocks):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tables.open_file(str(path),"w") as db:
        db.create_group("/","data")
        db.create_group("/","non_data_metadata")
        db.create_array("/non_data_metadata","sentinel",
                        np.array([17],dtype=np.int32))
        for sym,rows in stocks.items():
            t=db.create_table("/data",sym,description=DT,
                              expectedrows=max(1,len(rows)))
            t.append(rows)
            t.flush()

class PurchasedMinuteIntoCopiedOriginalH5(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base=Path(tmp.name)
        self.root=base/"stock"
        self.root.mkdir()
        self.module=base/"H5ParquetReconciler"
        self.reports=self.module/"reports"
        self.reports.mkdir(parents=True)
        self.mirrors=self.module/"work"/"h5_mirror"
        self.mirrors.mkdir(parents=True)
        for field,value in (("REPORTS",self.reports),("MIRRORS",self.mirrors)):
            p=patch.object(M,field,value)
            p.start()
            self.addCleanup(p.stop)
        self.refs={}
        self.payload={"period_physical_files":{}}
        for period in M.PERIODS:
            ref=parquet(
                self.root/"AllCycleAStockData"/period/"2026-09.parquet",
                [bar("2026-09-24","09:31" if period=="1min" else "09:30",
                     "SH600000")])
            st=ref.stat()
            entry=M.D._item("purchased_root",ref.relative_to(self.root).as_posix(),
                 "purchased_original",
                 stat={"size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns})
            self.refs[period]=[(ref,entry)]
            self.payload["period_physical_files"][period]=[entry]
        self.sourceH5={}
        for period in M.PERIODS:
            for market in M.MARKETS:
                path=self.root/"HikyuuData"/(market+"_"+period+".h5")
                stocks={}
                if market=="sh":
                    stamp=202609240931 if period=="1min" else 202609240935
                    # Purchased must override same source key; raw-only 09:32
                    # must remain and old stock not in purchased must survive.
                    stocks={
                        "SH600000":native(
                            [stamp,202609240932 if period=="1min" else 202609240940],
                            [1000,3333]),
                        "SH600001":native([202609240931],[4444]),
                    }
                h5(path,stocks)
                self.sourceH5[path.name]=M.MERGE.sha(path)

    def test_bounded_day_must_not_process_future_or_large_batches(self):
        self.assertEqual(M.validate_days("2026-09-24","2026-09-24"),
                         (date(2026,9,24),date(2026,9,24)))
        for start,end in (("2026-10-14","2026-10-14"),
                          ("2026-09-01","2026-09-07"),
                          ("2025-09-24","2025-09-24")):
            with self.subTest((start,end)),self.assertRaisesRegex(ValueError,"Bound"):
                M.validate_days(start,end)

    def test_actual_purchased_native_keys_sqlite_no_ohlcva_copies(self):
        db=self.mirrors/"one.sqlite3"
        store,receipt=M.stage_sqlite(
            db,self.refs,self.root,date(2026,9,24),date(2026,9,24))
        try:
            one=store.execute("SELECT stamp,record FROM bars WHERE period='1min'").fetchone()
            five=store.execute("SELECT stamp,record FROM bars WHERE period='5min'").fetchone()
            self.assertEqual(one[0],202609240931)
            self.assertEqual(five[0],202609240935)
            parsed=np.frombuffer(one[1],dtype=DT)
            self.assertEqual(parsed["closePrice"].tolist(),[11125])
            self.assertEqual(receipt["purchased_canonical_a_share_rows"],
                             {"1min":1,"5min":1})
            self.assertEqual(receipt["source_parquet_rowgroups_with_requested_time_scanned"],
                             {"1min":1,"5min":1})
        finally:
            store.close()

    def test_duplicate_original_parquet_source_key_fails_closed(self):
        p=self.refs["1min"][0][0]
        p=parquet(p,[bar("2026-09-24","09:31","SH600000"),
                     bar("2026-09-24","09:31","SH600000")])
        st=p.stat()
        self.refs["1min"][0][1]["source_stat"]={
            "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns}
        with self.assertRaisesRegex(ValueError,"Duplicate normalized purchased"):
            M.stage_sqlite(self.mirrors/"duplicates.sqlite3",self.refs,
                           self.root,date(2026,9,24),date(2026,9,24))

    def test_real_six_copied_h5_merged_and_original_only_keys_retained(self):
        safe=self.reports/"synthetic-minute-safe.json"
        with patch.object(M,"src_input",return_value=self.payload):
            result=M.merge_wave(
                self.root,self.reports/"not_real_manifest.json",M.SOURCE_SHA,
                "2026-09-24","2026-09-24","f00d00000001",safe)
        self.assertTrue(safe.exists())
        self.assertEqual(result["native_h5_files"],6)
        self.assertEqual(result["purchased_parquet_source_rows_written_as_native_h5"],
                         {"1min":1,"5min":1})
        dest=self.mirrors/"minute_purchased_wave_f00d00000001"
        with tables.open_file(str(dest/"sh_1min.h5"),"r") as db:
            rows=db.get_node("/data/SH600000").read()
            self.assertEqual(rows["datetime"].tolist(),[202609240931,202609240932])
            self.assertEqual(rows["closePrice"].tolist(),[11125,3333])
            self.assertEqual(db.get_node("/data/SH600001").read()["closePrice"].tolist(),
                             [4444])
            self.assertEqual(int(db.get_node("/non_data_metadata/sentinel")[0]),17)
        with tables.open_file(str(dest/"sh_5min.h5"),"r") as db:
            rows=db.get_node("/data/SH600000").read()
            self.assertEqual(rows["datetime"].tolist(),[202609240935,202609240940])
            self.assertEqual(rows["closePrice"].tolist(),[11125,3333])
        for name,digest in self.sourceH5.items():
            self.assertEqual(M.MERGE.sha(self.root/"HikyuuData"/name),digest)
        self.assertFalse(result["production_H5_activated"])
        self.assertFalse(result["purchase_numeric_units_and_time_labels_vendor_certified"])
        self.assertTrue(result[
            "native_minute_table_40byte_all_changed_stock_integer_readback_verified"])

    def make_prior_four_day_native(self):
        folder=self.mirrors/("minute_union_"+M.PRIOR_RUN)
        paths={}
        for period in M.PERIODS:
            for market in M.MARKETS:
                name=market+"_"+period+".h5"
                tables_for_market={}
                if market=="sh":
                    ts=202609280931 if period=="1min" else 202609280935
                    tables_for_market["SH600000"]=native([ts],[9999])
                file=folder/name
                h5(file,tables_for_market)
                paths[name]=M.MERGE.sha(file)
        safe=self.reports/(
            "mixed-purchased-h5-native-minute-4days-"+M.PRIOR_RUN+".json")
        safe.write_text(json.dumps({
            "status":"private_purchased_plus_h5_minute_40byte_native_h5_written_full_integer_readback",
            "native_bar_counts":{"1min":1,"5min":1},
            "source_days":sorted(M.PRIOR_DAYS),
            "native_h5_files_sha256":paths,
            "native_40byte_pytables_integer_full_readback_verified":True,
            "original_purchased_parquet_or_original_h5_modified":False,
            "production_pointer_modified":False,
        }),encoding="utf-8")
        return safe,folder

    def test_prior_native_four_day_sources_sha_verified_and_exact_keys_reused(self):
        safe,folder=self.make_prior_four_day_native()
        with patch.object(M,"PRIOR_ROWS",{"1min":1,"5min":1}):
            files=M.prior_native_files(safe,folder)
            self.assertEqual(len(files),6)
            result=self.reports/"merged-with-prior.json"
            with patch.object(M,"src_input",return_value=self.payload):
                doc=M.merge_wave(
                    self.root,self.reports/"not_real.json",M.SOURCE_SHA,
                    "2026-09-24","2026-09-24","f00d00000003",result,
                    prior_safe=safe,prior_root=folder)
        self.assertEqual(
            doc["already_written_prior_four_day_native_rows_reused"],
            {"1min":1,"5min":1})
        self.assertTrue(doc["prior_four_day_native_mirror_reused_not_reconverted"])
        output=self.mirrors/"minute_purchased_wave_f00d00000003"
        with tables.open_file(str(output/"sh_1min.h5"),"r") as db:
            old=db.get_node("/data/SH600000").read()
            self.assertEqual(old["datetime"].tolist(),
                             [202609240931,202609240932,202609280931])
            self.assertEqual(old["closePrice"].tolist(),[11125,3333,9999])
        for name,source_sha in self.sourceH5.items():
            self.assertEqual(M.MERGE.sha(self.root/"HikyuuData"/name),source_sha)

    def test_prior_native_mirror_sha_tamper_blocks_before_copy(self):
        safe,folder=self.make_prior_four_day_native()
        prior=folder/"sh_1min.h5"
        prior.write_bytes(prior.read_bytes()+b"changed")
        with patch.object(M,"PRIOR_ROWS",{"1min":1,"5min":1}):
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                M.prior_native_files(safe,folder)
        self.assertFalse((self.mirrors/"minute_purchased_wave_f00d00000004").exists())

    def test_original_market_file_does_not_change_when_no_purchased_minute(self):
        p=self.refs["5min"][0][0]
        parquet(p,[bar("2026-09-23","09:30","SH600000")])
        st=p.stat()
        self.refs["5min"][0][1]["source_stat"]={
            "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns}
        with patch.object(M,"src_input",return_value=self.payload):
            with self.assertRaisesRegex(ValueError,"not conserved"):
                M.merge_wave(self.root,self.reports/"not_real.json",M.SOURCE_SHA,
                             "2026-09-24","2026-09-24","f00d00000002",
                             self.reports/"no-bars.json")
        self.assertFalse((self.reports/"no-bars.json").exists())
        for name,digest in self.sourceH5.items():
            self.assertEqual(M.MERGE.sha(self.root/"HikyuuData"/name),digest)

if __name__=="__main__":
    unittest.main()
