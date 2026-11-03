"""Real H5->private Parquet write test for complete 1min and 5min stockdays.

Only synthetic data under H5ParquetReconciler/work, no purchased vendor data.
"""
import contextlib
import importlib.util
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "synthetic_minute_gap_stager",
    HERE.parent/"tools"/"write-h5-only-complete-minute-stockdays-to-private-parquet.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class RealMinuteGapWrites(unittest.TestCase):
    def setUp(self):
        import h5py
        import numpy as np
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch,prefix="minute-h5-stage-")
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.work=self.base/"work"/"unified_parquet"/"minute_gap_staging"
        self.day=date(2026,10,13)
        self.raw_dtype=np.dtype([
            ("datetime","<u8"),("openPrice","<u4"),
            ("highPrice","<u4"),("lowPrice","<u4"),
            ("closePrice","<u4"),("transCount","<u8"),
            ("transAmount","<u8"),
        ])
        for period in ("1min","5min"):
            folder=self.base/"AllCycleAStockData"/period/"2026"
            folder.mkdir(parents=True)
            dt=datetime(2026,10,13,9,30,tzinfo=timezone(timedelta(hours=8)))
            pq.write_table(pa.table({
                "ts":pa.array([int(dt.timestamp()*1000)],type=pa.int64()),
                "symbol":["000001.XSHE"],
                "open":[10.0],"high":[11.0],"low":[9.0],
                "close":[10.5],"volume":[100.0],"amount":[2000.0],
            }),folder/"sample.parquet")
            stamps=sorted(M.session_stamps(self.day,period))
            for market in ("sh","sz","bj"):
                file=self.base/"HikyuuData"/f"{market}_{period}.h5"
                file.parent.mkdir(parents=True,exist_ok=True)
                with h5py.File(file,"w") as h5:
                    group=h5.create_group("data")
                    sym={"sh":"SH600000","sz":"SZ000001","bj":"BJ920680"}[market]
                    # BJ not included; only two securities have H5 minutes.
                    if market=="bj":
                        continue
                    data=np.zeros(len(stamps),dtype=self.raw_dtype)
                    for i,stamp in enumerate(stamps):
                        data[i]=(stamp,10500,11000,10000,10700,100+i,2000+i)
                    group.create_dataset(sym,data=data)
        self.runid="123456789abc"

    def patched(self):
        ctx=contextlib.ExitStack()
        ctx.enter_context(patch.object(M,"MODULE",self.base))
        ctx.enter_context(patch.object(M,"WORK",self.work))
        ctx.enter_context(patch.object(M,"REPORTS",self.base/"reports"))
        return ctx

    def test_two_real_private_minute_parquet_files_created_and_read_back(self):
        import pyarrow.parquet as pq
        self.assertEqual(len(M.session_stamps(self.day,"1min")),240)
        self.assertEqual(len(M.session_stamps(self.day,"5min")),48)
        with self.patched():
            one=M.write_private_day(self.base,self.day,"1min",self.runid,
                                    max_purchased_rows=10000,max_h5_rows=10000)
            five=M.write_private_day(self.base,self.day,"5min",self.runid,
                                     max_purchased_rows=10000,max_h5_rows=10000)
        self.assertEqual(one["private_parquet_rows"],240)
        self.assertEqual(five["private_parquet_rows"],48)
        self.assertEqual(one["private_parquet_stockdays"],1)
        self.assertEqual(five["private_parquet_stockdays"],1)
        self.assertEqual(one["other_h5_counts"]["h5_datasets_not_probed_purchased_stockday"],1)
        self.assertEqual(five["other_h5_counts"]["h5_datasets_not_probed_purchased_stockday"],1)
        for period,result,num in (("1min",one,240),("5min",five,48)):
            path=self.base/result["private_parquet_relative_file"]
            table=pq.read_table(path)
            self.assertEqual(table.num_rows,num)
            self.assertEqual(set(table.column("symbol").to_pylist()),{"SH600000"})
            self.assertEqual(table.column("h5_native_datetime")[0].as_py(),
                min(M.session_stamps(self.day,period)))
            # Canonical purchased 1min timestamps are minute END, while
            # purchased 5min timestamps are the interval START.
            from datetime import datetime
            earliest=min(M.session_stamps(self.day,period))
            end=datetime.strptime(str(earliest),"%Y%m%d%H%M"
                ).replace(tzinfo=M.CORE.UTC8)
            minutes=0 if period=="1min" else 5
            self.assertEqual(table.column("ts")[0].as_py(),
                int((end-timedelta(minutes=minutes)).timestamp()*1000))
            self.assertFalse(result["ready_for_automatic_market_merge"])
            self.assertTrue(result["h5_raw_integer_fields_preserved"])
            self.assertEqual(result["quarantined_stockdays"],{})

    def test_purchased_day_shortcuts_h5_seeks_without_changing_h5_gap_rows(self):
        """The purchased SZ day must never binary-seek its H5 dataset."""
        original=M.CORE.h5_key_slice
        observed=[]
        def checked_slice(dataset,lower,upper):
            observed.append(dataset.name)
            if dataset.name.endswith("/SZ000001"):
                raise AssertionError("Purchased stockday improperly binary-searched in H5")
            return original(dataset,lower,upper)
        with self.patched(),patch.object(M.CORE,"h5_key_slice",
                                        side_effect=checked_slice):
            result=M.write_private_day(
                self.base,self.day,"1min",self.runid,
                max_purchased_rows=10000,max_h5_rows=10000)
        self.assertEqual(result["private_parquet_rows"],240)
        self.assertEqual(result["private_parquet_stockdays"],1)
        self.assertEqual(
            result["other_h5_counts"]["h5_datasets_not_probed_purchased_stockday"],1)
        self.assertEqual(result["other_h5_counts"]["h5_stockdays_seen"],1)
        self.assertEqual(observed,["/data/SH600000"])
        self.assertTrue(result["h5_raw_integer_fields_preserved"])
        self.assertFalse(result["ready_for_automatic_market_merge"])

    def test_incomplete_five_minute_stockday_is_quarantined_not_written_as_gap(self):
        import h5py
        file=self.base/"HikyuuData"/"sh_5min.h5"
        with h5py.File(file,"r+") as h5:
            ds=h5["data"]["SH600000"][:]
            del h5["data"]["SH600000"]
            h5["data"].create_dataset("SH600000",data=ds[:-1])
        with self.patched():
            result=M.write_private_day(self.base,self.day,"5min",self.runid,
                                       max_purchased_rows=10000,max_h5_rows=10000)
        self.assertEqual(result["private_parquet_rows"],0)
        self.assertEqual(result["quarantined_stockdays"],{
            "incomplete_5min_session":1,
        })


if __name__=="__main__":
    unittest.main(verbosity=2)
