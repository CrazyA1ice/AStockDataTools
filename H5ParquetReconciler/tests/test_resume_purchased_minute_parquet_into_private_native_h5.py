"""Disk-backed crash-recovery tests for ongoing purchased-first native minute H5.

Use real PyTables 40-byte stock TABLEs and SQLite, but ONLY temporary data.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tables

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "resumable_private_native_minutes_real_temp_h5_sqlite",
    HERE.parent/"tools"/"resume-purchased-minute-parquet-into-private-native-h5.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DT=M.MERGE.canonical_dtype(np)
SYMBOL="SH600000"

def rows(stamps,prices):
    arr=np.zeros(len(stamps),dtype=DT)
    for i,(stamp,price) in enumerate(zip(stamps,prices)):
        arr[i]["datetime"]=stamp
        for k in ("openPrice","highPrice","lowPrice","closePrice"):
            arr[i][k]=price
        arr[i]["transAmount"]=100
        arr[i]["transCount"]=10
    return arr

class ResumableMinuteStockTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.root.mkdir(exist_ok=True)
        self.h5=self.root/"sh_1min.h5"
        self.sqlite=sqlite3.connect(str(self.root/"progress.sqlite3"))
        self.addCleanup(self.sqlite.close)
        self.sqlite.execute(
            "CREATE TABLE stock_progress (period TEXT NOT NULL,"
            " symbol TEXT NOT NULL,state TEXT NOT NULL,existed INTEGER NOT NULL,"
            " target_sha TEXT,original_only INTEGER,replacements INTEGER,"
            " PRIMARY KEY(period,symbol)) WITHOUT ROWID")
        self.sqlite.commit()
        with tables.open_file(str(self.h5),"w") as h5:
            h5.create_group("/","data")
            table=h5.create_table("/data",SYMBOL,description=DT)
            table.append(rows([202609230931,202609230932],[888,333]))
            table.flush()

    def old(self):
        with tables.open_file(str(self.h5),"r") as h5:
            return h5.get_node("/data/"+SYMBOL).read()

    def progress(self,state,existed=1,sha="bad"):
        self.sqlite.execute(
            "INSERT INTO stock_progress "
            "(period,symbol,state,existed,target_sha,original_only,replacements)"
            " VALUES(?,?,?,?,?,?,?)",
            ("1min",SYMBOL,state,existed,sha,0,0))
        self.sqlite.commit()

    def test_atomic_stock_h5_native_integer_purchase_priority_original_only_preserved(self):
        with tables.open_file(str(self.h5),"a") as h5:
            self.assertTrue(M.commit_stock(
                h5,self.sqlite,"1min",SYMBOL,
                rows([202609230931,202609230933],[11125,444]),
                tables,np,DT))
            self.assertFalse(M.commit_stock(
                h5,self.sqlite,"1min",SYMBOL,
                rows([202609230931,202609230933],[11125,444]),
                tables,np,DT))
            self.assertNotIn("/data/__undo_"+SYMBOL,h5)
            self.assertNotIn("/data/__next_"+SYMBOL,h5)
        result=self.old()
        self.assertEqual(result["datetime"].tolist(),
                         [202609230931,202609230932,202609230933])
        self.assertEqual(result["closePrice"].tolist(),[11125,333,444])
        self.assertEqual(self.sqlite.execute(
            "SELECT state FROM stock_progress").fetchone()[0],"done")

    def test_crash_during_staging_restores_old_and_removes_temp(self):
        original=self.old().tobytes()
        self.progress("pending")
        with tables.open_file(str(self.h5),"a") as h5:
            newer=h5.create_table("/data","__next_"+SYMBOL,description=DT)
            newer.append(rows([202609230931],[999]))
            newer.flush()
            self.assertFalse(M.reset_pending(
                h5,self.sqlite,"1min",SYMBOL,tables))
            self.assertNotIn("/data/__next_"+SYMBOL,h5)
        self.assertEqual(self.old().tobytes(),original)
        self.assertEqual(self.sqlite.execute(
            "SELECT COUNT(*) FROM stock_progress").fetchone()[0],0)

    def test_crash_after_backup_rename_restores_original_data_and_key(self):
        original=self.old().tobytes()
        self.progress("pending")
        with tables.open_file(str(self.h5),"a") as h5:
            h5.rename_node(h5.get_node("/data/"+SYMBOL),"__undo_"+SYMBOL)
            scratch=h5.create_table("/data","__next_"+SYMBOL,description=DT)
            scratch.append(rows([202609230931],[11125]))
            scratch.flush()
            self.assertFalse(M.reset_pending(
                h5,self.sqlite,"1min",SYMBOL,tables))
        self.assertEqual(self.old().tobytes(),original)

    def test_crash_after_new_table_installed_rolls_back_pending(self):
        original=self.old().tobytes()
        self.progress("pending")
        with tables.open_file(str(self.h5),"a") as h5:
            h5.rename_node(h5.get_node("/data/"+SYMBOL),"__undo_"+SYMBOL)
            new=h5.create_table("/data",SYMBOL,description=DT)
            new.append(rows([202609230931],[999]))
            new.flush()
            self.assertFalse(M.reset_pending(
                h5,self.sqlite,"1min",SYMBOL,tables))
        self.assertEqual(self.old().tobytes(),original)

    def test_after_commit_corrupted_h5_stock_refused(self):
        with tables.open_file(str(self.h5),"a") as h5:
            M.commit_stock(
                h5,self.sqlite,"1min",SYMBOL,
                rows([202609230931],[11125]),tables,np,DT)
            h5.get_node("/data/"+SYMBOL).append(
                rows([202609240931],[666]))
            with self.assertRaisesRegex(ValueError,"no longer match"):
                M.reset_pending(h5,self.sqlite,"1min",SYMBOL,tables)

    def test_unjournaled_stock_scratch_node_refused(self):
        with tables.open_file(str(self.h5),"a") as h5:
            h5.create_table("/data","__next_"+SYMBOL,description=DT)
            with self.assertRaisesRegex(ValueError,"Unjournaled"):
                M.reset_pending(h5,self.sqlite,"1min",SYMBOL,tables)

    def test_one_time_copy_does_not_replace_previously_modified_private_h5(self):
        accepted=self.root/"accepted"
        accepted.mkdir()
        live=self.root/"live"
        expected={}
        for filename in M.H5_NAMES:
            f=accepted/filename
            f.write_bytes(b"fixed source "+filename.encode())
            expected[filename]=M.sha(f)
        for field,val in (("MIRRORS",self.root),("BASE_DIR",accepted),("LIVE",live)):
            patcher=patch.object(M,field,val)
            patcher.start()
            self.addCleanup(patcher.stop)
        baseline_sha="e"*64
        with patch.object(M.shutil,"disk_usage",
                          return_value=type("Disk",(),{"free":10**12})()):
            M.initialize_live(expected,baseline_sha)
        target=live/"sh_1min.h5"
        target.write_bytes(b"CHANGED private ongoing candidate")
        M.initialize_live(expected,baseline_sha)
        self.assertEqual(target.read_bytes(),b"CHANGED private ongoing candidate")

    def test_real_five_day_native_h5_stock_960_bars_in_single_commit(self):
        # 960 genuine minute end-label records across four trading days:
        # > prior 3*241 ceiling, <= new five-day bounded calendar ceiling.
        from datetime import date,timedelta
        self.sqlite.execute(
            "CREATE TABLE bars (period TEXT NOT NULL,symbol TEXT NOT NULL,"
            " stamp INTEGER NOT NULL,record BLOB NOT NULL,"
            " PRIMARY KEY(period,symbol,stamp)) WITHOUT ROWID")
        imported=0
        for day in (14,15,16,17):
            for begin,end in ((9*60+31,11*60+30),
                              (13*60+1,15*60)):
                for minute in range(begin,end+1):
                    key=202609000000+day*10000+(minute//60)*100+minute%60
                    raw=rows([key],[11125]).tobytes()
                    self.sqlite.execute(
                        "INSERT INTO bars(period,symbol,stamp,record)"
                        " VALUES(?,?,?,?)",
                        ("1min",SYMBOL,key,raw))
                    imported+=1
        self.sqlite.commit()
        self.assertEqual(imported,960)
        outcome=M.process_stock_batch(
            self.sqlite,"1min","sh",self.h5,days=5,
            dtype=DT,np=np,tables=tables)
        self.assertEqual(outcome["purchased_rows_checked"],960)
        self.assertEqual(outcome["stock_tables_updated"],1)
        result=self.old()
        self.assertEqual(len(result),962)
        self.assertEqual(int(result["datetime"][-1]),202609230932)
        self.assertEqual(len(set(result["datetime"].tolist())),962)

    def test_week_batch_per_stock_overflow_rejected_before_h5_change(self):
        self.sqlite.execute(
            "CREATE TABLE bars (period TEXT NOT NULL,symbol TEXT NOT NULL,"
            " stamp INTEGER NOT NULL,record BLOB NOT NULL,"
            " PRIMARY KEY(period,symbol,stamp)) WITHOUT ROWID")
        # 2*241 exceeds a two-day 5-minute max (2*48).
        for ix in range(97):
            key=202609140000+ix
            self.sqlite.execute(
                "INSERT INTO bars(period,symbol,stamp,record) VALUES(?,?,?,?)",
                ("5min",SYMBOL,key,rows([key],[20]).tobytes()))
        self.sqlite.commit()
        original=M.sha_array(self.old())
        with self.assertRaisesRegex(ValueError,"Unexpected stock/week"):
            M.process_stock_batch(
                self.sqlite,"5min","sh",self.h5,days=2,
                dtype=DT,np=np,tables=tables)
        self.assertEqual(M.sha_array(self.old()),original)

    def test_timestamp_bounds_reject_future_and_crossing_accepted_date(self):
        self.assertEqual(
            tuple(str(x) for x in M.batch_dates("2026-09-23","2026-09-23")),
            ("2026-09-23","2026-09-23"))
        self.assertEqual(
            tuple(str(x) for x in M.batch_dates("2011-01-04","2011-01-04")),
            ("2011-01-04","2011-01-04"))
        self.assertEqual(
            tuple(str(x) for x in M.batch_dates("2025-09-01","2025-09-03")),
            ("2025-09-01","2025-09-03"))
        self.assertEqual(
            tuple(str(x) for x in M.batch_dates("2026-09-14","2026-09-18")),
            ("2026-09-14","2026-09-18"))
        self.assertEqual(
            tuple(str(x) for x in M.batch_dates("2026-09-07","2026-09-11")),
            ("2026-09-07","2026-09-11"))
        for first,last in (("2026-09-24","2026-09-24"),
                           ("2026-10-14","2026-10-14"),
                           ("2010-12-31","2010-12-31"),
                           ("2026-09-01","2026-09-08")):
            with self.subTest(first),self.assertRaises(ValueError):
                M.batch_dates(first,last)

if __name__=="__main__":
    unittest.main()
