"""Synthetic bounded all16 private DAY coverage with real private Arrow/SQLite.

All fake data and scratch files live under H5ParquetReconciler/work.
"""
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"
s=importlib.util.spec_from_file_location(
    "synthetic_all16_private_coverage",
    TOOLS/"query-private-2011-2026-all16-coverage-readonly.py")
Q=importlib.util.module_from_spec(s)
s.loader.exec_module(Q)


def row(year,day,kind="purchased_parquet"):
    dt=datetime.fromisoformat(day+"T00:00:00+08:00")
    ts=int(dt.timestamp()*1000)
    return {"ts":ts,"trading_date":day,"symbol":"SH600000",
            "source_symbol":"600000.XSHG",
            "open":10.0,"high":11.0,"low":9.0,"close":10.5,
            "volume":100.0,"amount":1000.0,"value_source":kind}


class All16PrivateCoverageTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        t=HERE.parent/"work"/"_union_scratch"
        t.mkdir(parents=True,exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=t,prefix="query16-")
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.reports=self.root/"reports"
        self.reports.mkdir()
        self.work=self.root/"work"/"unified_parquet"
        self.years=self.work/"physical_years"
        self.years.mkdir(parents=True)
        self.schema=Q.PHYS.schema(pa)
        self.verpath=self.reports/"all16.json"
        self.annual={
            str(year):{
                "private_relative_directory":
                    f"work/unified_parquet/physical_years/physical_{year}_{year:012x}",
                "total_rows":0,
                "physical_manifest_sha256":"0"*64,
                "private_stockday_index_sha256":"0"*64,
            }
            for year in range(2011,2027)
        }
        self.version={
            "format":Q.V.FORMAT,
            "status":"all16_private_annual_physical_shards_sha_and_stockday_years_verified_not_activated",
            "year_count":16,
            "years":list(range(2011,2027)),
            "purchased_original_records":14115707,
            "verified_h5_only_gap_records":22274,
            "private_total_stockday_records":14137981,
            "per_year_private_manifest_sha_and_independent_audit_bound":True,
            "per_year_private_sqlite_index_integrity_rechecked_readonly":True,
            "cross_year_stockday_key_ranges_disjoint":True,
            "original_market_files_written":False,
            "private_physical_parquet_or_sqlite_written":False,
            "private_or_production_active_pointer_modified":False,
            "candidate_source_units_certified":False,
            "ready_for_production_query":False,
            "ready_for_automatic_market_merge":False,
            "ready_for_h5_mirror":False,
            "annual":self.annual,
        }
        self.data={}
        self.add_year(2016,[
            ("purchased","purchased/day.parquet",
             [row(2016,"2016-08-17")]),
            ("h5_gap_2016","candidate/h5-gap-2016.parquet",
             [row(2016,"2016-08-18","private_h5_mixed_stockday_candidate")])])
        self.add_year(2025,[
            ("purchased","purchased/day.parquet",
             [row(2025,"2025-12-31")])])
        parts=[]
        for m in range(1,10):
            day=f"2026-{m:02d}-02"
            parts.append((f"2026-{m:02d}.parquet",
                          f"purchased/month={m:02d}/day.parquet",
                          [row(2026,day)]))
        parts.append(("h5_gap_2026","candidate/h5-gap-2026.parquet",
                      [row(2026,"2026-01-05",
                           "private_h5_whole_date_candidate")]))
        self.add_year(2026,parts)
        self.annual["2011"]["total_rows"]=14137981-2-1-10
        self.saved_sha=self.save_version()

    def add_year(self,year,parts):
        import pyarrow as pa
        import pyarrow.parquet as pq
        rel=self.annual[str(year)]["private_relative_directory"]
        folder=self.root/rel
        folder.mkdir(parents=True,exist_ok=False)
        expected={}
        all_rows=[]
        for key,relative,rows in parts:
            file=folder/relative
            file.parent.mkdir(parents=True,exist_ok=True)
            pq.write_table(pa.Table.from_pylist(rows,schema=self.schema),file,
                           compression="zstd")
            kind=("purchased_parquet" if key=="purchased" or key.startswith("2026-")
                  else "private_h5_mixed_stockday_candidate" if year==2016
                  else "mixed_whole_h5_candidates")
            expected[key]={
                "relative_file":relative,
                "source_kind":kind,
                "rows":len(rows),
                "sha256":Q.M.ST.sha(file),
            }
            all_rows.extend(rows)
        db=folder/"stockday-unique.sqlite3"
        con=sqlite3.connect(db)
        con.execute("CREATE TABLE stockday(year INTEGER,symbol TEXT,trading_date TEXT,"
                    "kind TEXT,PRIMARY KEY(year,symbol,trading_date)) WITHOUT ROWID")
        for r in all_rows:
            con.execute("INSERT INTO stockday VALUES(?,?,?,?)",
                        (year,r["symbol"],r["trading_date"],r["value_source"]))
        con.commit()
        con.close()
        manifest={"year":year,"partition_files":expected,
                  "total_private_physical_rows":len(all_rows)}
        mf=folder/"manifest.json"
        mf.write_text(json.dumps(manifest,sort_keys=True)+"\n",encoding="utf-8")
        self.annual[str(year)].update({
            "total_rows":len(all_rows),
            "physical_manifest_sha256":Q.M.ST.sha(mf),
            "private_stockday_index_sha256":Q.M.ST.sha(db),
        })
        self.data[year]=(folder,mf,db)

    def save_version(self):
        self.verpath.write_text(json.dumps(self.version,sort_keys=True)+"\n",
                                encoding="utf-8")
        return Q.M.ST.sha(self.verpath)

    def patched(self):
        from contextlib import ExitStack
        s=ExitStack()
        for name,value in (
            ("MODULE",self.root),
            ("REPORTS",self.reports),
            ("WORK",self.work),
            ("ROOT",self.years),
        ):
            s.enter_context(patch.object(Q.M,name,value))
        return s

    def run_query(self,start,end,budget=1200000):
        with self.patched():
            doc=Q.version(self.verpath,self.saved_sha)
            return Q.query(doc,self.saved_sha,"SH600000",start,end,budget)

    def test_2016_mixed_h5_purchased_query_only_returns_aggregate_counts(self):
        r=self.run_query("2016-08-17","2016-08-19")
        self.assertEqual(r["matched_stockday_rows"],2)
        self.assertEqual(r["sqlite_rows_matched"],2)
        self.assertEqual(r["by_source_counts"],{
            "purchased_parquet":1,
            "private_h5_mixed_stockday_candidate":1,
        })
        self.assertFalse(r["all_original_licensed_OHLCVA_values_read"])
        self.assertTrue(r["private_query_symbol_and_exact_dates_not_exported"])
        self.assertNotIn("SH600000",json.dumps(r))
        self.assertNotIn("2016-08-17",json.dumps(r))
        self.assertFalse(r["ready_for_h5_mirror"])

    def test_query_cross_2025_and_2026_uses_sha_pinned_monthly_partitions(self):
        r=self.run_query("2025-12-31","2026-01-06")
        self.assertEqual(r["query_years"],[2025,2026])
        self.assertEqual(r["matched_stockday_rows"],3)
        self.assertEqual(r["by_source_counts"]["purchased_parquet"],2)
        self.assertEqual(r["by_source_counts"]["private_h5_whole_date_candidate"],1)
        self.assertEqual(r["sha_checked_private_partitions"],11)
        self.assertEqual(r["sqlite_rows_matched"],3)

    def test_wrong_version_sha_fails_before_private_partition_probe(self):
        with self.patched():
            with self.assertRaisesRegex(ValueError,"version SAFE SHA differs"):
                Q.version(self.verpath,"0"*64)

    def test_modified_year_manifest_sha_refused(self):
        f,manifest,db=self.data[2016]
        manifest.write_bytes(manifest.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"manifest/SQLite SHA changed"):
            self.run_query("2016-08-17","2016-08-18")

    def test_modified_normalized_parquet_sha_refused_before_row_decode(self):
        f,m,db=self.data[2016]
        p=f/"purchased"/"day.parquet"
        p.write_bytes(p.read_bytes()+b"change")
        with self.assertRaisesRegex(ValueError,"partition bytes differ"):
            self.run_query("2016-08-17","2016-08-18")

    def test_sqlite_extra_stockday_fails_parquet_crosscheck(self):
        f,m,db=self.data[2016]
        con=sqlite3.connect(db)
        con.execute("INSERT INTO stockday VALUES(?,?,?,?)",
                    (2016,"SH600000","2016-08-19","purchased_parquet"))
        con.commit()
        con.close()
        self.annual["2016"]["private_stockday_index_sha256"]=Q.M.ST.sha(db)
        self.saved_sha=self.save_version()
        with self.assertRaisesRegex(ValueError,"coverage and SHA-bound SQLite"):
            self.run_query("2016-08-17","2016-08-19")

    def test_32_day_window_and_oversized_candidate_budget_refused(self):
        with self.patched():
            with self.assertRaisesRegex(ValueError,"<=31 days"):
                Q.parameters("SH600000","2016-08-01","2016-09-01",1200000)
        with self.assertRaisesRegex(ValueError,"bounded read budget"):
            self.run_query("2016-08-17","2016-08-18",1)

    def test_noncanonical_symbol_and_out_of_scope_year_fail_closed(self):
        with self.assertRaises(ValueError):
            self.run_query("2010-01-01","2010-01-02")
        with self.patched():
            with self.assertRaises(ValueError):
                Q.parameters("not-a-symbol","2016-08-17","2016-08-18",100)


if __name__=="__main__":
    unittest.main(verbosity=2)
