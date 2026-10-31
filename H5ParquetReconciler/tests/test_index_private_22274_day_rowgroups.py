"""Synthetic 22,274-source-row SQLite rowgroup index and opt-in query tests."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(label,file):
    spec=importlib.util.spec_from_file_location(label,TOOLS/file)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


I=load("indexed_22274_synthetic_under_test",
       "index-private-22274-day-rowgroups.py")
Q=load("indexed_22274_join_under_test",
       "query-private-purchased-plus-22274-candidates.py")
SYMS=[f"SH{prefix}{i:03d}" for prefix in ("600","601","603","605","688","689")
      for i in range(1000)]
WHOLE_DAYS=(("2026-10-08",5546),("2026-10-09",5547),
            ("2026-10-12",5549),("2026-10-13",5549))


def row(symbol,day,kind):
    dt=datetime.fromisoformat(day+"T00:00:00+08:00")
    return {"ts":int(dt.timestamp()*1000),"trading_date":day,
            "symbol":symbol,"open":10.0,"high":11.0,"low":9.0,
            "close":10.5,"volume":100.0,"amount":1000.0,
            "value_source":kind}


class PrivateIndexedCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(prefix="indexed_22274_test_",dir=scratch)
        cls.root=Path(cls.tmp.name)
        cls.reports=cls.root/"reports"
        cls.reports.mkdir()
        cls.work=cls.root/"work"/"unified_parquet"
        cls.index_root=cls.work/"candidate_indexes"
        cls.src_dir=cls.work/"candidate_snapshots"/"candidates_abcdefabcdef"
        cls.src_dir.mkdir(parents=True)
        cls.source_safe=cls.reports/"source.json"
        cls.source_safe.write_bytes(b'{"private":true}\n')
        cls.source_safe_sha=hashlib.sha256(cls.source_safe.read_bytes()).hexdigest()
        cls.parts={}
        schema=I.S.candidate_schema(pa)
        cls.year_rows={
            2016:[row("SZ000001","2016-08-17",
                      "private_h5_mixed_stockday_candidate")],
            2026:[],
        }
        for day,count in WHOLE_DAYS:
            cls.year_rows[2026].extend(
                row(s,day,"private_h5_whole_date_candidate") for s in SYMS[:count])
        cls.year_rows[2026].extend(
            row(f"SZ000{n:03d}","2026-08-17",
                "private_h5_mixed_stockday_candidate") for n in range(82))
        cls.year_rows[2026].sort(key=lambda r:(r["trading_date"],r["symbol"],r["ts"]))
        for year,rows in cls.year_rows.items():
            path=cls.src_dir/f"year={year}"/"day.parquet"
            path.parent.mkdir()
            pq.write_table(pa.Table.from_pylist(rows,schema=schema),
                           path,row_group_size=4096,compression="zstd")
            cls.parts[str(year)]={
                "relative_file":f"year={year}/day.parquet",
                "rows":len(rows),"sha256":I.S.sha(path)}
        cls.manifest=cls.src_dir/"manifest.json"
        cls.manifest.write_text(json.dumps({
            "source_version_sha256":"e"*64,"partitions":cls.parts
        },sort_keys=True)+"\n",encoding="utf-8")
        cls.source={
            "source_version_sha256":"e"*64,
            "original_source_stat_sha256":"d"*64,
            "manifest_sha256":I.S.sha(cls.manifest),
            "candidate_year_rows":{"2016":1,"2026":22273},
            "partition_sha256":{y:x["sha256"] for y,x in cls.parts.items()},
        }
        cls.index_dir=cls.index_root/"index_abcdefabcdef"
        cls.gate=cls.reports/"source-verify.json"
        cls.index_safe=cls.reports/"index.json"
        cls.patches=[
            patch.object(I,"MODULE",cls.root),
            patch.object(I,"WORK",cls.work),
            patch.object(I,"INDEX_ROOT",cls.index_root),
            patch.object(I,"REPORTS",cls.reports),
            patch.object(I.V,"source",side_effect=lambda p:(
                cls.source,cls.source_safe_sha,cls.src_dir,cls.manifest)),
            patch.object(I.V,"verify",side_effect=cls.fake_full_verify),
        ]
        for p in cls.patches:
            p.start()
        try:
            cls.index_report=I.build(cls.source_safe,cls.index_dir,cls.gate,cls.index_safe)
        except Exception:
            for p in reversed(cls.patches):
                p.stop()
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches):
            p.stop()
        cls.tmp.cleanup()

    @classmethod
    def fake_full_verify(cls,source,out):
        Path(out).write_bytes(b'{"sha":true,"all":22274}\n')
        return {
            "total_h5_only_day_candidates_verified":22274,
            "whole_date_candidate_rows_verified":22191,
            "mixed_date_candidate_rows_verified":83,
            "candidate_source_units_certified":False,
        }

    def out(self,suffix):
        return self.reports/(self._testMethodName+"-"+suffix+".json")

    def test_builder_requires_one_full_prior_source_verify(self):
        self.assertTrue(self.gate.is_file())
        self.assertEqual(self.index_report["index_row_count"],22274)
        self.assertEqual(self.index_report["source_year_rows"],
                         {"2016":1,"2026":22273})
        self.assertEqual(self.index_report["source_kind_counts"],
                         {"private_h5_whole_date_candidate":22191,
                          "private_h5_mixed_stockday_candidate":83})
        self.assertFalse(self.index_report["ready_for_automatic_market_merge"])
        self.assertTrue(self.index_report["all_22274_source_rows_verified_at_index_build"])

    def test_symbol_rowgroup_selection_exact_four_dates(self):
        selected,src,sha,summary=I.select(
            self.index_safe,self.source_safe,["SH600000"],
            date(2026,9,30),date(2026,10,13),self.out("read"))
        self.assertEqual(len(selected["SH600000"]["private_h5_whole_date_candidate"]),4)
        self.assertEqual(summary["selected_candidate_rows"],4)
        self.assertGreater(summary["candidate_rowgroups_read"],0)
        self.assertFalse(summary["all_22274_source_rows_decoded_this_query"])
        self.assertFalse(summary["source_market_freshness_rechecked"])
        self.assertNotIn("SH600000",self.out("read").read_text())

    def test_mixed_year_2016_is_selectable_without_2026_scan(self):
        selected,_,_,summary=I.select(
            self.index_safe,self.source_safe,["SZ000001"],
            date(2016,8,17),date(2016,8,17),self.out("read"))
        self.assertEqual(len(selected["SZ000001"]["private_h5_mixed_stockday_candidate"]),1)
        self.assertEqual(summary["selected_candidate_rows"],1)

    def test_purchased_only_year_does_not_open_indexed_parquet(self):
        with patch("pyarrow.parquet.ParquetFile",
                   side_effect=AssertionError("unexpected year Parquet opened")) as p:
            rows,_,_,summary=I.select(
                self.index_safe,self.source_safe,["SH600000"],
                date(2025,8,1),date(2025,8,2),self.out("read"))
            p.assert_not_called()
        self.assertEqual(summary["selected_candidate_rows"],0)
        self.assertTrue(all(not any(x.values()) for x in rows.values()))

    def test_bad_index_sqlite_sha_rejected_before_sqlite_opens(self):
        path=self.index_dir/I.INDEX_SQL
        old=path.read_bytes()
        try:
            path.write_bytes(old+b"tampered")
            with self.assertRaisesRegex(ValueError,"changed"):
                I.select(self.index_safe,self.source_safe,["SH600000"],
                         date(2026,10,8),date(2026,10,13),self.out("read"))
        finally:
            path.write_bytes(old)
        self.assertFalse(self.out("read").exists())

    def test_bad_candidate_year_sha_rejected(self):
        path=self.src_dir/"year=2026"/"day.parquet"
        old=path.read_bytes()
        try:
            path.write_bytes(old+b"tampered")
            with self.assertRaisesRegex(ValueError,"changed"):
                I.select(self.index_safe,self.source_safe,["SH600000"],
                         date(2026,10,8),date(2026,10,13),self.out("read"))
        finally:
            path.write_bytes(old)
        self.assertFalse(self.out("read").exists())

    def test_manifest_tamper_rejected_before_sqlite(self):
        path=self.index_dir/"manifest.json"
        old=path.read_bytes()
        try:
            path.write_bytes(old+b"tampered")
            with self.assertRaisesRegex(ValueError,"changed"):
                I.indexed_source(self.index_safe,self.source_safe)
        finally:
            path.write_bytes(old)

    def test_crossyear_index_selection_refused(self):
        with self.assertRaisesRegex(ValueError,"same year"):
            I.select(self.index_safe,self.source_safe,["SZ000001"],
                     date(2016,12,31),date(2026,1,1),self.out("read"))

    def test_duplicate_indexed_symbol_request_refused(self):
        with self.assertRaisesRegex(ValueError,"distinct symbols"):
            I.select(self.index_safe,self.source_safe,["SH600000","SH600000"],
                     date(2026,10,8),date(2026,10,13),self.out("read"))

    def test_private_index_cannot_escape_work_root(self):
        with self.assertRaisesRegex(ValueError,"escaped"):
            I.index_folder(self.root/"elsewhere"/"index_abcdefabcdef",False)

    def test_duplicate_index_safe_cannot_overwrite(self):
        with self.assertRaisesRegex(ValueError,"overwrite"):
            I.report(self.index_safe,False)

    def test_index_root_is_private_and_no_data_leaves_safe(self):
        self.assertTrue(self.index_dir.relative_to(self.root/"work").as_posix())
        safe=self.index_safe.read_text()
        self.assertNotIn("SH600000",safe)
        self.assertNotIn("SZ000001",safe)
        self.assertNotIn("10.5",safe)
        self.assertNotIn(str(self.root),safe)

    def test_new_query_optin_index_avoids_full_source_redecode(self):
        with tempfile.TemporaryDirectory(prefix="query_",dir=self.root) as tmp:
            real_root=Path(tmp)
            queried_source=real_root/"stock"
            queried_source.mkdir()
            read_safe=self.out("view")
            gate=self.out("audit")
            full=Q.V.verify
            def purchase(root,symbol,period,first,last,**kwargs):
                self.assertFalse(kwargs["local_cache"])
                return {"bars":[{
                    "symbol":symbol,"period":"day","trading_date":"2026-09-30",
                    "source_timestamp_ms":int(datetime.fromisoformat(
                        "2026-09-30T00:00:00+08:00").timestamp()*1000),
                    "open":10.0,"high":11.0,"low":9.0,"close":10.5,
                    "volume":100.0,"amount":1000.0}],
                    "safe_summary":{
                        "source_rows_scanned":300,
                        "source_market_files_modified":False,
                        "no_h5_read":True,
                        "no_automatic_gaps_fill":True}}
            # Query loads its own nested module instance, so mock its
            # index source path and the original immutable candidate source.
            with patch.object(Q.V,"REPORTS",self.reports),\
                 patch.object(Q.V,"source",side_effect=lambda p:(
                     self.source,self.source_safe_sha,self.src_dir,self.manifest)),\
                 patch.object(Q.INDEX,"MODULE",self.root),\
                 patch.object(Q.INDEX,"INDEX_ROOT",self.index_root),\
                 patch.object(Q.INDEX,"REPORTS",self.reports),\
                 patch.object(Q.INDEX.V,"source",side_effect=lambda p:(
                     self.source,self.source_safe_sha,self.src_dir,self.manifest)),\
                 patch.object(Q.P.private_cache,"source_signature",
                              return_value={"stat":"same","file_count":2}),\
                 patch.object(Q.P,"query_bars",side_effect=purchase),\
                 patch.object(Q.STAGER.PRE.KEYS,"state_digest",return_value="d"*64),\
                 patch.object(Q.STAGER.REG,"load_version",return_value={
                     "original_source_stat_sha256":"d"*64}),\
                 patch.object(Q.STAGER.REG,"LOCK",self.root/"none"),\
                 patch.object(Q.V,"verify",side_effect=AssertionError(
                     "indexed query should not redo 22274-row source verification")):
                returned=Q.query(queried_source,self.source_safe,["SH600000"],
                    "2026-09-30","2026-10-13",gate,read_safe,
                    index_safe=self.index_safe)
            s=returned["safe_summary"]
            self.assertEqual(s["purchased_parquet_rows"],1)
            self.assertEqual(s["whole_h5_candidate_rows"],4)
            self.assertEqual(s["returned_stockday_rows"],5)
            self.assertIsNone(s["private_candidate_full_recheck_safe_sha256"])
            self.assertFalse(s["private_candidate_all_22274_rows_sha_schema_keys_verified"])
            self.assertTrue(s["private_candidate_index_built_from_all_22274_verified_source_rows"])
            self.assertTrue(s["private_index_candidate_source_and_sqlite_sha_verified_this_query"])
            self.assertFalse(s["private_candidate_full_rows_redecoded_this_query"])
            self.assertTrue(gate.is_file())
            self.assertTrue(read_safe.is_file())


if __name__=="__main__":
    unittest.main(verbosity=2)
