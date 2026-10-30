"""Actual synthetic HDF5 datetime projections + every purchased Parquet footer."""
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
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


A=load("pre2011_h5_parquet_inventory_test",
       HERE.parent/"tools"/"inventory-pre2011-h5-parquet-day-readonly.py")


def make_h5(root,sh=None,sz=None,extra=None):
    import h5py
    import numpy as np
    folder=root/"HikyuuData"
    folder.mkdir(parents=True,exist_ok=True)
    dtype=np.dtype([("datetime","<u8"),("openPrice","<u4"),
        ("highPrice","<u4"),("lowPrice","<u4"),
        ("closePrice","<u4"),("transCount","<u8"),("transAmount","<u8")])
    markets={
        "sh":{"SH600000": sh if sh is not None else
              (199911100000,200101020000,201101040000),
              "SH900901":(199911100000,200101020000)},
        "sz":{"SZ000001":sz if sz is not None else
              (199101020000,200101020000,200912310000,201101040000)}
    }
    if extra is not None:
        markets["sh"].update(extra)
    for venue,records in markets.items():
        with h5py.File(folder/(venue+"_day.h5"),"w") as f:
            g=f.create_group("data")
            for symbol,keys in records.items():
                arr=np.zeros(len(keys),dtype=dtype)
                arr["datetime"]=list(keys)
                arr["openPrice"]=10000
                arr["highPrice"]=11000
                arr["lowPrice"]=9000
                arr["closePrice"]=10500
                arr["transCount"]=100
                arr["transAmount"]=1000
                g.create_dataset(symbol,data=arr)


def stamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone(
        timedelta(hours=8))).timestamp()*1000)


def make_pq(root,days=("2011-01-04","2011-02-05"),stats=True,name="2011.parquet"):
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder=root/"AllCycleAStockData"/"day"
    folder.mkdir(parents=True,exist_ok=True)
    if days:
        rows=[{"ts":stamp(d),"symbol":"600000.XSHG",
               "open":10.0,"high":11.0,"low":9.0,
               "close":10.5,"volume":100.0,"amount":1000.0}
              for d in days]
        file=folder/name
        file.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows),file,
                       row_group_size=1,write_statistics=stats)
        return file
    return None


@contextmanager
def fresh():
    work=HERE.parent/"work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work,prefix="pre2011-h5pq-test-") as t:
        home=Path(t)
        market=home/"market"
        market.mkdir()
        reports=home/"reports"
        reports.mkdir()
        safe=reports/"pre2011-safe.json"
        make_h5(market)
        original=make_pq(market)
        with patch.object(A,"MODULE",home), \
             patch.object(A,"REPORTS",reports):
            yield market,safe,original


class FullPre2011DaySourceEvidenceTests(unittest.TestCase):
    def test_real_h5_datetime_fullscan_counts_1990_to_2010_while_parquet_2011_only(self):
        with fresh() as (root,safe,pq):
            r=A.inventory(root,safe)
            self.assertEqual(r["status"],
                 "pre2011_full_source_day_timestamp_coverage_inventory_not_staged")
            h=r["original_h5"]
            self.assertEqual(h["pre2011_candidate_h5_stockday_rows"],5)
            self.assertEqual(h["earliest_pre2011_candidate_h5_date"],"1991-01-02")
            self.assertEqual(h["latest_pre2011_candidate_h5_date"],"2009-12-31")
            self.assertEqual(h["yearly_source_key_inventory"]["1991"][
                "H5_candidate_stockday_rows"],1)
            self.assertEqual(h["yearly_source_key_inventory"]["1999"][
                "H5_candidate_stockday_rows"],1)
            self.assertEqual(h["yearly_source_key_inventory"]["2001"][
                "H5_candidate_stockday_rows"],2)
            self.assertEqual(h["yearly_source_key_inventory"]["2009"][
                "H5_candidate_stockday_rows"],1)
            self.assertEqual(h["excluded_non_candidate_symbol_datasets"],1)
            p=r["original_purchased_parquet"]
            self.assertEqual(p["source_day_parquet_files_scanned"],1)
            self.assertEqual(p["source_day_row_groups_scanned"],2)
            self.assertTrue(p[
                "no_pre2011_parquet_rows_proven_by_complete_footer_bounds"])
            self.assertEqual(p["earliest_all_stock_footer_candidate_day"],
                             "2011-01-04")
            self.assertFalse(r["pre2011_h5_to_new_private_parquet_authorized"])
            self.assertFalse(r["production_query_route_modified"])
            for key in ("SH600000","SZ000001","SH900901",
                        "600000.XSHG","AllCycleAStockData","1000.0"):
                self.assertNotIn(key,safe.read_text(encoding="utf-8"))

    def test_purchased_2011_named_file_can_contain_pre2011_data(self):
        with fresh() as (root,safe,pq):
            make_pq(root,days=("2010-12-30","2011-01-04"),
                    name="2011.parquet")
            r=A.inventory(root,safe)
            p=r["original_purchased_parquet"]
            self.assertEqual(p["row_groups_with_possible_pre2011_timestamp"],1)
            self.assertFalse(p[
                "no_pre2011_parquet_rows_proven_by_complete_footer_bounds"])
            self.assertEqual(p["pre2011_original_purchased_coverage_status"],
                             "pre2011_timestamp_ranges_possible_in_purchased_day_files")

    def test_filename_not_a_year_and_nested_day_files_are_inspected(self):
        with fresh() as (root,safe,pq):
            make_pq(root,days=("2002-01-04",),
                    name="nested/oddly-named.parquet")
            r=A.inventory(root,safe)
            self.assertEqual(r["original_purchased_parquet"][
                "source_day_parquet_files_scanned"],2)
            self.assertEqual(r["original_purchased_parquet"][
                "row_groups_with_possible_pre2011_timestamp"],1)

    def test_unknown_footer_stats_never_certify_pre2011_absence(self):
        with fresh() as (root,safe,pq):
            make_pq(root,stats=False)
            r=A.inventory(root,safe)
            p=r["original_purchased_parquet"]
            self.assertEqual(p["nonempty_row_groups_without_ts_stats"],2)
            self.assertFalse(p[
                "no_pre2011_parquet_rows_proven_by_complete_footer_bounds"])
            self.assertEqual(p["pre2011_original_purchased_coverage_status"],
                "unknown_pre2011_purchased_coverage_missing_row_group_stats")

    def test_h5_dataset_out_of_order_in_post2011_tail_also_refused(self):
        with fresh() as (root,safe,pq):
            make_h5(root,sh=(199911100000,201101040000,201001020000))
            with self.assertRaisesRegex(ValueError,"not strictly ascending"):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_h5_duplicate_historical_dates_refused(self):
        with fresh() as (root,safe,pq):
            make_h5(root,sh=(199911100000,199911100000,201101040000))
            with self.assertRaisesRegex(ValueError,"not strictly ascending"):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_h5_invalid_historical_date_refused(self):
        with fresh() as (root,safe,pq):
            make_h5(root,sh=(199913010000,201101040000))
            with self.assertRaisesRegex(ValueError,"calendar key"):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_h5_historical_nonmidnight_day_key_refused(self):
        with fresh() as (root,safe,pq):
            make_h5(root,sh=(199911101030,201101040000))
            with self.assertRaisesRegex(ValueError,"daily time key"):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_original_H5_changed_after_analysis_refused(self):
        with fresh() as (root,safe,pq):
            original=A.inspect_h5
            def modified(*a):
                result=original(*a)
                file=root/"HikyuuData"/"sh_day.h5"
                with file.open("ab") as f:
                    f.write(b"changed")
                return result
            with patch.object(A,"inspect_h5",side_effect=modified):
                with self.assertRaisesRegex(ValueError,"changed before SAFE"):
                    A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_parquet_modified_after_analysis_refused(self):
        with fresh() as (root,safe,pq):
            original=A.inspect_purchased
            def modified(*a):
                result=original(*a)
                with pq.open("ab") as f:
                    f.write(b"changed")
                return result
            with patch.object(A,"inspect_purchased",side_effect=modified):
                with self.assertRaisesRegex(ValueError,"changed before SAFE"):
                    A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_missing_purchased_day_folder_is_unknown_not_absence(self):
        with fresh() as (root,safe,pq):
            import shutil
            shutil.rmtree(root/"AllCycleAStockData"/"day")
            with self.assertRaisesRegex(ValueError,
                                        "Purchased day Parquet directory unavailable"):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_missing_h5_market_file_refused(self):
        with fresh() as (root,safe,pq):
            (root/"HikyuuData"/"sh_day.h5").unlink()
            with self.assertRaises(ValueError):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())

    def test_existing_safe_outside_reports_or_symlink_rejected(self):
        with fresh() as (root,safe,pq):
            with self.assertRaisesRegex(ValueError,"module reports JSON"):
                A.inventory(root,root/"unsafe.json")
            safe.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"module reports JSON"):
                A.inventory(root,safe)
            self.assertEqual(safe.read_text(encoding="utf-8"),"protected")

    def test_total_year_count_and_zero_years_are_explicit(self):
        with fresh() as (root,safe,pq):
            r=A.inventory(root,safe)
            years=r["original_h5"]["yearly_source_key_inventory"]
            self.assertEqual(len(years),21)
            self.assertEqual(years["1990"]["H5_candidate_stockday_rows"],0)
            self.assertEqual(years["2010"]["H5_candidate_stockday_rows"],0)
            self.assertTrue(r["original_h5"][
                "selected_dataset_datetime_keys_full_scan_strictly_increasing"])

    def test_missing_ts_column_is_not_silent_purchased_absence(self):
        with fresh() as (root,safe,pq):
            import pyarrow as pa,pyarrow.parquet as pqmod
            pqmod.write_table(pa.table({"close":[1.0]}),pq)
            with self.assertRaisesRegex(ValueError,"no ts column"):
                A.inventory(root,safe)
            self.assertFalse(safe.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
