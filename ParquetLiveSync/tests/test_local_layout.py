"""Offline eight-period original stock layout, native real Arrow and backups."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))

import pyarrow as pa
import pyarrow.parquet as pq
import local_layout as L
import live_sync as S

CN=timezone(timedelta(hours=8))

def ts(y,m,d):
    return int(datetime(y,m,d,9,30,tzinfo=CN).timestamp()*1000)

def table(rows):
    v={k:[] for k in L.COLS}
    for time,sym,value in rows:
        v["ts"].append(time)
        v["symbol"].append(sym)
        for key in L.COLS[2:]:
            v[key].append(float(value))
    schema=pa.schema([pa.field("ts",pa.int64()),pa.field("symbol",pa.string())]
                     +[pa.field(k,pa.float64()) for k in L.COLS[2:]])
    return pa.table(v,schema=schema)

def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    pq.write_table(table(rows),path,compression="zstd")

class ActualYearMonthEightPeriodLayout(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/"stock"
        self.work=Path(tmp.name)/"work"
        self.work.mkdir()
        for period in L.PERIODS:
            folder=self.root/"AllCycleAStockData"/period
            folder.mkdir(parents=True)
            write(folder/"2025.parquet",[(ts(2025,9,1),"SH600000",5)])
            write(folder/"2026-09.parquet",[(ts(2026,9,30),"SH600000",7)])
        self.day=self.root/"AllCycleAStockData"/"day"

    def test_auto_detect_stock_root_or_allcycle_root(self):
        actual=self.root/"AllCycleAStockData"
        self.assertEqual(L.storage_root(self.root),actual)
        self.assertEqual(L.storage_root(actual),actual)
        self.assertEqual(len([p for p in L.PERIODS if (actual/p).is_dir()]),8)

    def test_screenshot_layout_prior_annual_and_current_monthly(self):
        scan=L.inventory(self.root,current_year=2026)
        self.assertEqual(scan["root"],str(self.root/"AllCycleAStockData"))
        self.assertTrue(scan["layout_valid"])
        for period in L.PERIODS:
            item=scan["periods"][period]
            self.assertEqual(item["annual_files"],1)
            self.assertEqual(item["monthly_files"],1)
            self.assertEqual(item["current_year_monthly_files"],["2026-09.parquet"])
        self.assertEqual(L.target_for_date(
            self.root,"day",date(2026,11,11),current_year=2026),
            self.day/"2026-11.parquet")
        self.assertEqual(L.target_for_date(
            self.root,"1min",date(2025,6,1),current_year=2026),
            self.root/"AllCycleAStockData"/"1min"/"2025.parquet")

    def test_actual_day_month_new_file_and_sha_receipt(self):
        supplied=table([(ts(2026,11,11),"SH600000",11)])
        out=L.write_month(self.root,"day",2026,11,supplied,self.work,
                          current_year=2026)
        self.assertEqual(out["added"],1)
        self.assertEqual(out["total_rows"],1)
        self.assertEqual(out["target"],str(self.day/"2026-11.parquet"))
        self.assertEqual(L.hash_file(out["target"]),out["sha256"])
        report=json.loads((self.work/"transactions/day/2026-11.json").read_bytes())
        self.assertEqual(report["new_sha256"],out["sha256"])
        self.assertEqual(report["old_sha256"],None)

    def test_monthly_merge_preserves_old_and_only_adds_unique_new(self):
        target=self.day/"2026-11.parquet"
        write(target,[(ts(2026,11,10),"SH600000",12),
                      (ts(2026,11,11),"SH600001",13)])
        origin=L.hash_file(target)
        new=table([(ts(2026,11,11),"SH600001",999),
                   (ts(2026,11,12),"SZ000001",20)])
        first=L.write_month(self.root,"day",2026,11,new,self.work,
                            current_year=2026)
        self.assertEqual(first["added"],1)
        self.assertEqual(first["same_key"],1)
        got=pq.read_table(target)
        self.assertEqual(got.num_rows,3)
        self.assertEqual(got["close"].to_pylist(),[12.,13.,20.])
        backup=Path(first["original_backup"]["path"])
        self.assertTrue(backup.exists())
        self.assertEqual(L.hash_file(backup),origin)
        self.assertNotEqual(L.hash_file(target),origin)
        self.assertTrue((self.work/"transactions/day/2026-11.json").exists())
        retry=L.write_month(self.root,"day",2026,11,new,self.work,
                            current_year=2026)
        self.assertTrue(retry["unchanged"])
        self.assertEqual(retry["added"],0)
        self.assertEqual(retry["same_key"],2)
        self.assertEqual(L.hash_file(target),first["sha256"])

    def test_second_day_same_month_rewrites_once_with_versioned_backup(self):
        first=L.write_month(self.root,"day",2026,11,
                            table([(ts(2026,11,9),"SH600000",11)]),self.work,
                            current_year=2026)
        second=L.write_month(self.root,"day",2026,11,
                             table([(ts(2026,11,10),"SH600000",12)]),self.work,
                             current_year=2026)
        self.assertEqual(pq.read_table(self.day/"2026-11.parquet").num_rows,2)
        self.assertNotEqual(first["sha256"],second["sha256"])
        self.assertEqual(second["original_backup"]["sha256"],first["sha256"])

    def test_monthly_parquet_bad_trading_month_rejected_before_write(self):
        with self.assertRaisesRegex(ValueError,"outside target"):
            L.write_month(self.root,"day",2026,11,
                          table([(ts(2026,10,30),"SH600000",2)]),
                          self.work,current_year=2026)
        self.assertFalse((self.day/"2026-11.parquet").exists())

    def test_same_stock_ts_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError,"Duplicate normalized"):
            L.write_month(self.root,"day",2026,11,
                          table([(ts(2026,11,10),"SH600000",1),
                                 (ts(2026,11,10),"600000.SH",2)]),
                          self.work,current_year=2026)

    def test_purchased_suffix_security_codes_are_preserved(self):
        target=self.day/"2026-11.parquet"
        write(target,[(ts(2026,11,9),"600000.SH",10)])
        outcome=L.write_month(self.root,"day",2026,11,
                              table([(ts(2026,11,10),"SH600000",20)]),
                              self.work,current_year=2026)
        self.assertEqual(outcome["added"],1)
        self.assertEqual(pq.read_table(target)["symbol"].to_pylist(),
                         ["600000.SH","600000.SH"])

    def test_external_mutated_market_journal_rejects_next_write(self):
        L.write_month(self.root,"day",2026,11,
                      table([(ts(2026,11,9),"SH600000",1)]),
                      self.work,current_year=2026)
        target=self.day/"2026-11.parquet"
        write(target,[(ts(2026,11,9),"SH600000",100)])
        with self.assertRaisesRegex(ValueError,"differs from previous protected"):
            L.write_month(self.root,"day",2026,11,
                          table([(ts(2026,11,10),"SH600000",2)]),
                          self.work,current_year=2026)

    def test_annual_preview_all_eight_does_not_mutate_existing_previous_year(self):
        year=L.rollover_all_periods(
            self.root,2025,self.work,current_year=2026,apply=False)
        self.assertEqual(year["ready_periods"],8)
        self.assertEqual(year["periods"]["day"]["action"],
                         "ALREADY_ANNUAL_NO_CHANGES")
        self.assertTrue((self.day/"2025.parquet").exists())

    def test_actual_previous_year_12_month_archive_all_eight_and_replay(self):
        for period in L.PERIODS:
            folder=self.root/"AllCycleAStockData"/period
            (folder/"2025.parquet").unlink()
            for month in range(1,13):
                write(folder/f"2025-{month:02}.parquet",
                      [(ts(2025,month,1),"SH600000",month)])
        preview=L.rollover_all_periods(
            self.root,2025,self.work,current_year=2026,apply=False)
        self.assertEqual(preview["ready_periods"],8)
        archive=L.rollover_all_periods(
            self.root,2025,self.work,current_year=2026,apply=True)
        self.assertEqual(archive["archived_periods"],8)
        for period in L.PERIODS:
            folder=self.root/"AllCycleAStockData"/period
            self.assertEqual(pq.read_table(folder/"2025.parquet").num_rows,12)
            self.assertFalse((folder/"2025-01.parquet").exists())
            self.assertEqual(len(list(folder.glob("2025-??.parquet"))),0)
            self.assertTrue(
                (self.work/"rollover/2025"/
                 (period+"-annual-commit.json")).is_file())
            again=L.archive_year(
                self.root,period,2025,self.work,current_year=2026,apply=True)
            self.assertEqual(again["action"],"VERIFIED_PREVIOUS_ARCHIVE")

    def test_archive_refuses_incomplete_previous_year_for_any_period(self):
        for period in L.PERIODS:
            (self.root/"AllCycleAStockData"/period/"2025.parquet").unlink()
            for month in range(1,12):
                write(self.root/"AllCycleAStockData"/period/
                      f"2025-{month:02}.parquet",
                      [(ts(2025,month,1),"SH600000",month)])
        with self.assertRaisesRegex(ValueError,"twelve complete"):
            L.rollover_all_periods(
                self.root,2025,self.work,current_year=2026,apply=True)
        for period in L.PERIODS:
            self.assertFalse(
                (self.root/"AllCycleAStockData"/period/"2025.parquet").exists())

    def test_local_native_arrow_view_selects_existing_annual_and_monthly(self):
        dataset=L.open_local_layout_dataset(self.root,"day")
        self.assertEqual(dataset.count_rows(),2)
        self.assertEqual(set(dataset.to_table()["symbol"].to_pylist()),{"SH600000"})

class RecoverOctoberTrustedBeforeCutoff(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/"stock"
        self.work=Path(tmp.name)/"work"
        self.work.mkdir()
        for period in L.PERIODS:
            (self.root/"AllCycleAStockData"/period).mkdir(parents=True)
        self.day=self.root/"AllCycleAStockData"/"day"
        (self.day/"2026-09.parquet").parent.mkdir(parents=True,exist_ok=True)
        write(self.day/"2026-09.parquet",
              [(ts(2026,9,30),"SH600000",1)])
        for field,value in (("WORK",self.work),
                            ("STATE",self.work/"state.json")):
            p=patch.object(S,field,value)
            p.start()
            self.addCleanup(p.stop)

    def test_oct14_new_month_first_seeds_oct1_13_original_then_day(self):
        original=table([
            (ts(2026,10,13),f"SH{600000+i:06}",10)
            for i in range(1250)])
        source=self.work/"trusted-oct-original.parquet"
        pq.write_table(original,source)
        doc=S.initial_state()
        doc["calibration"]={
            "tdx_shares_to_local_volume":1,
            "tdx_yuan_to_local_amount":1,
            "local_day_ts_offset_ms":34200000}
        date14=date(2026,10,14)
        external=table([(ts(2026,10,14),"SH600000",11)])
        meta={"raw_zip_sha256":"a"*64,"origin_url":"https://tdx.example/test",
              "a_share_by_market":{"sh":1,"sz":0,"bj":0}}
        S.put_day(date14,external,meta,doc)
        with patch.object(S,"baseline_day_files",return_value=[source]):
            outcome=S.materialize_day_in_original_layout(
                self.root,date14,doc,{},lambda _message:None)
        self.assertEqual(outcome["added"],1251)
        self.assertEqual(
            pq.read_table(self.day/"2026-10.parquet").num_rows,1251)
        self.assertEqual(S.read_state()["local_month_materializations"][
            "day/2026-10.parquet"]["row_count"],1251)
        date15=date(2026,10,15)
        S.put_day(date15,table([(ts(2026,10,15),"SH600000",12)]),meta,doc)
        # October 1..13 physical seed is already on disk after the first
        # accepted commit; repeat downloads must NOT rescan all 16 years.
        with patch.object(S,"baseline_day_files",
                          side_effect=AssertionError("Old baseline should not rescan")):
            again=S.materialize_day_in_original_layout(
                self.root,date15,doc,{},lambda _message:None)
        self.assertEqual(again["added"],1)
        self.assertEqual(again["same_key"],0)
        self.assertEqual(pq.read_table(self.day/"2026-10.parquet").num_rows,
                         1252)
        self.assertEqual(pq.read_table(self.day/"2026-09.parquet").num_rows,1)

if __name__=="__main__":
    unittest.main()
