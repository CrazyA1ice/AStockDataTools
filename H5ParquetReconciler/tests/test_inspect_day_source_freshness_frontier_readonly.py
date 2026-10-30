"""Synthetic real HDF5 + PyArrow footer original day source frontier tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A=load("day_source_frontier_test",
       HERE.parent/"tools"/"inspect-day-source-freshness-frontier-readonly.py")
SYMS=("SH600000","SZ000001","SH600519")


def stamp(day):
    return int(datetime.fromisoformat(day).replace(
        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)


def make_h5(root,last_dates=None):
    import h5py,numpy as np
    root=root/"HikyuuData"
    root.mkdir(parents=True,exist_ok=True)
    dtype=np.dtype([("datetime","<u8"),("openPrice","<u4"),
                    ("highPrice","<u4"),("lowPrice","<u4"),
                    ("closePrice","<u4"),("transAmount","<u8"),
                    ("transCount","<u8")])
    selected=last_dates or {
        "SH600000":["2026-09-30","2026-10-13"],
        "SZ000001":["2026-09-30","2026-10-12"],
        "SH600519":["2026-09-30","2026-10-13"]}
    for market in ("sh","sz"):
        with h5py.File(root/(market+"_day.h5"),"w") as f:
            group=f.create_group("data")
            for sym,days in selected.items():
                if sym[:2].lower()!=market:
                    continue
                recs=np.zeros(len(days),dtype=dtype)
                for i,day in enumerate(days):
                    recs[i]=(
                        int(day.replace("-",""))*10000,
                        10000,10200,9800,10100,150000,1100)
                group.create_dataset(sym,data=recs)


def make_parquet(root,days=None,write_stats=True):
    import pyarrow as pa,pyarrow.parquet as pq
    path=root/"AllCycleAStockData"/"day"
    path.mkdir(parents=True,exist_ok=True)
    rows=[{"ts":stamp(day),"symbol":sym,
           "open":10.0,"high":10.2,"low":9.8,"close":10.1,
           "volume":1000.0,"amount":150000.25}
          for day,sym in (days if days is not None else [
              ("2026-09-30","SH600000"),
              ("2026-10-13","SH600519")])]
    tab=pa.Table.from_pylist(rows)
    file=path/"2026.parquet"
    pq.write_table(tab,file,write_statistics=write_stats,row_group_size=1)
    return file


@contextmanager
def fresh():
    work=HERE.parent/"work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work,prefix="frontier-synthetic-") as t:
        parent=Path(t)
        data=parent/"market"
        data.mkdir()
        reports=parent/"reports"
        reports.mkdir()
        make_h5(data)
        parquet=make_parquet(data)
        safe=reports/"frontier-safe.json"
        with patch.object(A,"REPORTS",reports):
            yield data,safe,parquet


def check(data,safe,syms=SYMS,year=2026):
    return A.inspect(data,list(syms),year,safe)


class ActualH5AndPurchasedFooterFrontierTests(unittest.TestCase):
    def test_actual_hdf5_stock_tails_and_actual_parquet_footer_bounds(self):
        with fresh() as (data,safe,parquet):
            result=check(data,safe)
            self.assertEqual(result["selected_stock_count"],3)
            self.assertEqual(result["observed_latest_selected_h5_tail_day"],
                             "2026-10-13")
            self.assertEqual(result["purchased_day_year_footer"][
                "purchased_footer_latest_candidate_date"],"2026-10-13")
            self.assertEqual(result["purchased_day_year_footer"][
                "matching_year_source_files"],1)
            self.assertEqual(result["purchased_day_year_footer"][
                "row_group_footers_examined"],2)
            self.assertTrue(result["stat_checks_not_content_hashes"])
            self.assertFalse(result["ready_for_full_h5_mirror_or_automatic_backfill"])
            self.assertFalse(result["production_query_route_modified"])
            self.assertFalse(result["purchased_day_year_footer"][
                "raw_purchased_parquet_ohlcva_rows_opened"])
            self.assertEqual([
                x["h5_last_positional_record_day"] for x in result[
                    "selected_original_h5_last_positional_days"]],
                ["2026-10-13","2026-10-12","2026-10-13"])
            for secret in ("SH600000","SZ000001","SH600519",
                           "150000.25","AllCycleAStockData",
                           "HikyuuData","market/"):
                self.assertNotIn(secret,safe.read_text(encoding="utf-8"))

    def test_older_h5_tails_and_later_global_purchased_footer_separated(self):
        with fresh() as (data,safe,parquet):
            make_h5(data,{
                "SH600000":["2026-09-30"],
                "SZ000001":["2026-09-30"],
                "SH600519":["2026-09-30"]})
            make_parquet(data,[("2026-10-23","SH600000")])
            result=check(data,safe)
            self.assertEqual(result["observed_latest_selected_h5_tail_day"],
                             "2026-09-30")
            self.assertEqual(result["purchased_day_year_footer"][
                "purchased_footer_latest_candidate_date"],"2026-10-23")
            self.assertTrue(result["purchased_footer_global_bound_not_stock_specific"])

    def test_h5_tail_duplicate_key_refused(self):
        with fresh() as (data,safe,parquet):
            make_h5(data,{"SH600000":["2026-10-13","2026-10-13"],
                          "SZ000001":["2026-10-12"],
                          "SH600519":["2026-10-13"]})
            with self.assertRaisesRegex(ValueError,"strictly increasing"):
                check(data,safe)
            self.assertFalse(safe.exists())

    def test_h5_invalid_tail_day_clock_refused(self):
        with fresh() as (data,safe,parquet):
            import h5py
            file=data/"HikyuuData"/"sh_day.h5"
            with h5py.File(file,"r+") as h:
                ds=h["data"]["SH600000"]
                v=ds[-1]
                v["datetime"]=202610130100
                ds[-1]=v
            with self.assertRaisesRegex(ValueError,"daily timestamp key"):
                check(data,safe)
            self.assertFalse(safe.exists())

    def test_h5_bad_struct_layout_refused(self):
        with fresh() as (data,safe,parquet):
            import h5py,numpy as np
            file=data/"HikyuuData"/"sz_day.h5"
            with h5py.File(file,"r+") as h:
                del h["data"]["SZ000001"]
                h["data"].create_dataset(
                    "SZ000001",data=np.array([202610120000],dtype="u8"))
            with self.assertRaisesRegex(ValueError,"H5 day layout"):
                check(data,safe)
            self.assertFalse(safe.exists())

    def test_purchased_missing_ts_column_refused(self):
        with fresh() as (data,safe,parquet):
            import pyarrow as pa,pyarrow.parquet as pq
            pq.write_table(pa.table({"symbol":["SH600000"],"close":[1.0]}),
                           parquet)
            with self.assertRaisesRegex(ValueError,"missing ts"):
                check(data,safe)
            self.assertFalse(safe.exists())

    def test_purchased_footer_missing_ts_stats_fails_certification_not_open(self):
        with fresh() as (data,safe,parquet):
            make_parquet(data,write_stats=False)
            result=check(data,safe)
            block=result["purchased_day_year_footer"]
            self.assertEqual(block["nonempty_row_groups_without_usable_ts_minmax"],2)
            self.assertIsNone(block["purchased_footer_latest_candidate_date"])
            self.assertFalse(block["latest_source_date_certified"])
            self.assertTrue(safe.exists())

    def test_original_purchased_source_changed_during_probe_refused(self):
        with fresh() as (data,safe,parquet):
            old=A.inspect_purchased
            def mutate(*a,**kw):
                obj=old(*a,**kw)
                with parquet.open("ab") as f:
                    f.write(b"changed-after-footer")
                return obj
            with patch.object(A,"inspect_purchased",side_effect=mutate):
                with self.assertRaisesRegex(ValueError,"metadata changed"):
                    check(data,safe)
            self.assertFalse(safe.exists())

    def test_h5_original_source_changed_during_probe_refused(self):
        with fresh() as (data,safe,parquet):
            old=A.inspect_h5
            def mutate(*a,**kw):
                obj=old(*a,**kw)
                path=data/"HikyuuData"/"sz_day.h5"
                with path.open("ab") as f:
                    f.write(b"changed-after-H5-read")
                return obj
            with patch.object(A,"inspect_h5",side_effect=mutate):
                with self.assertRaisesRegex(ValueError,"metadata changed"):
                    check(data,safe)
            self.assertFalse(safe.exists())

    def test_missing_h5_stock_dataset_refused(self):
        with fresh() as (data,safe,parquet):
            import h5py
            path=data/"HikyuuData"/"sz_day.h5"
            with h5py.File(path,"r+") as f:
                del f["data"]["SZ000001"]
            with self.assertRaisesRegex(ValueError,"stock dataset missing"):
                check(data,safe)
            self.assertFalse(safe.exists())

    def test_missing_2026_year_purchased_file_is_not_assumed_stale(self):
        with fresh() as (data,safe,parquet):
            parquet.unlink()
            with self.assertRaisesRegex(ValueError,"No matching purchased day year files"):
                check(data,safe)
            self.assertFalse(safe.exists())

    def test_source_selection_must_be_canonical_and_a_share(self):
        with fresh() as (data,safe,parquet):
            for syms in ([],["sh600000"],["SH600000","SH600000"],
                         ["BJ899999"],["BAD"],["SH600000"]*11):
                with self.subTest(syms=syms):
                    with self.assertRaises(ValueError):
                        check(data,safe,syms)
                    self.assertFalse(safe.exists())

    def test_year_and_out_of_module_report_refused(self):
        with fresh() as (data,safe,parquet):
            for year in (1990,2101,None,"2026"):
                with self.subTest(year=year):
                    with self.assertRaises(ValueError):
                        check(data,safe,year=year)
            with self.assertRaises(ValueError):
                check(data,data/"unsafe.json")
            self.assertFalse(safe.exists())

    def test_existing_safe_cannot_be_overwritten(self):
        with fresh() as (data,safe,parquet):
            safe.write_text("protected",encoding="utf-8")
            with self.assertRaises(ValueError):
                check(data,safe)
            self.assertEqual(safe.read_text(),"protected")


if __name__=="__main__":
    unittest.main(verbosity=2)
