"""Synthetic 2026 private physical purchased-months + full H5 candidate gate."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,TOOLS/file)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M=load("physical_year_2026_builder_test",
       "materialize-private-2026-purchased-plus-h5-year.py")
VERIFY=load("physical_year_2026_independent_test",
            "verify-private-2026-purchased-plus-h5-year.py")
F=M.F


def stamp(day):
    return int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)


def paid(symbol,day):
    return {"ts":stamp(day),"symbol":symbol,"open":10.0,
            "high":11.0,"low":9.0,"close":10.5,
            "volume":100.0,"amount":1000.0}


def candidate(symbol,day,source):
    dt={**paid(symbol,day),"trading_date":day,"value_source":source}
    return dt


class Private2026PhysicalYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(prefix="physical_2026_synthetic_",dir=scratch)
        cls.root=Path(cls.tmp.name)
        cls.work=cls.root/"work"/"unified_parquet"
        cls.reports=cls.root/"reports"
        cls.reports.mkdir()
        cls.root_src=cls.root/"purchased"
        cls.day=cls.root_src/"day"
        cls.day.mkdir(parents=True)
        cls.readme=cls.root_src/"【先看我】数据说明.txt"
        cls.readme.write_bytes(b"fake signed-less readme")
        cls.vendor=cls.root_src/"文件校验清单.txt"
        cls.vendor.write_bytes(b"fake test-only file hashes")
        cls.vendor_sha=hashlib.sha256(cls.vendor.read_bytes()).hexdigest()
        cls.readme_sha=hashlib.sha256(cls.readme.read_bytes()).hexdigest()
        paid_schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(f,pa.float64()) for f in F),
        ])
        cls.sources={}
        cls.records={}
        for month in range(1,10):
            fn=f"2026-{month:02d}.parquet"
            path=cls.day/fn
            pq.write_table(pa.Table.from_pylist([
                paid(f"600{month:03d}.XSHG",f"2026-{month:02d}-15"),
            ],schema=paid_schema),path)
            cls.sources[fn]=path
            cls.records[fn]={
                "size":path.stat().st_size,"rows":1,"sha":M.ST.sha(path)}
        cls.candidate_dir=cls.root/"candidate_source"
        (cls.candidate_dir/"year=2026").mkdir(parents=True)
        symbols=[
            f"SH{prefix}{i:03d}" for prefix in
            ("600","601","603","605","688","689") for i in range(1000)
        ]
        months=[("2026-10-08",5546),("2026-10-09",5547),
                ("2026-10-12",5549),("2026-10-13",5549)]
        rows=[]
        for day,n in months:
            rows.extend(candidate(sym,day,"private_h5_whole_date_candidate")
                        for sym in symbols[:n])
        rows.extend(candidate(f"SZ000{i:03d}","2026-08-17",
                     "private_h5_mixed_stockday_candidate") for i in range(1,83))
        rows.sort(key=lambda x:(x["trading_date"],x["symbol"],x["ts"]))
        cls.candidate_source=cls.candidate_dir/"year=2026"/"day.parquet"
        pq.write_table(pa.Table.from_pylist(rows,schema=M.ST.candidate_schema(pa)),
                       cls.candidate_source,row_group_size=4096)
        cls.candidate_manifest=cls.candidate_dir/"manifest.json"
        cls.candidate_manifest.write_text('{"only_private":true}\n',encoding="utf-8")
        cls.candidate_safe=cls.reports/"h5-only.json"
        cls.candidate_safe.write_text('{"h5":true}\n',encoding="utf-8")
        cls.candidate_doc={
            "candidate_year_rows":{"2016":1,"2026":22273},
            "source_version_sha256":
                "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23",
            "manifest_sha256":M.ST.sha(cls.candidate_manifest),
            "partition_sha256":{"2026":M.ST.sha(cls.candidate_source)},
        }
        cls.path=cls.work/"physical_years"/"physical_2026_abcdefabcdef"
        cls.gate=cls.reports/"candidate-gate.json"
        cls.safe=cls.reports/"physical-safe.json"
        cls.verified=cls.reports/"physical-verified.json"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def fake_existing_source(cls,root,readme_sha,manifest_sha):
        if readme_sha!=cls.readme_sha or manifest_sha!=cls.vendor_sha:
            raise ValueError("Wrong test source hash")
        return cls.root_src,cls.readme,cls.vendor,cls.sources,cls.records

    @classmethod
    def fake_gap_check(cls,safe,report):
        Path(report).write_text('{"synthetic":true,"count":22274}\n')
        return {
            "total_h5_only_day_candidates_verified":22274,
            "whole_date_candidate_rows_verified":22191,
            "mixed_date_candidate_rows_verified":83,
            "candidate_source_units_certified":False,
        }

    def build(self):
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"WORK",self.work),\
             patch.object(M,"ROOT",self.path.parent),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M,"purchased_manifest",side_effect=self.fake_existing_source),\
             patch.object(M.V,"verify",side_effect=self.fake_gap_check),\
             patch.object(M.V,"source",return_value=(
                 self.candidate_doc,
                 hashlib.sha256(self.candidate_safe.read_bytes()).hexdigest(),
                 self.candidate_dir,self.candidate_manifest)):
            return M.materialize(self.root_src,self.candidate_safe,
                self.readme_sha,self.vendor_sha,self.path,self.gate,self.safe)

    def ensure_built(self):
        if not self.safe.exists():
            self.build()

    def test_private_year_synthetic_full_9_months_plus_22273_candidates(self):
        outcome=self.build() if not self.safe.exists() else json.loads(self.safe.read_bytes())
        self.assertEqual(outcome["purchased_original_rows"],9)
        self.assertEqual(outcome["h5_whole_candidate_rows"],22191)
        self.assertEqual(outcome["h5_mixed_candidate_rows"],82)
        self.assertEqual(outcome["total_private_physical_rows"],22282)
        self.assertEqual(len(outcome["physical_partition_sha256"]),10)
        self.assertFalse(outcome["original_market_files_written"])
        self.assertFalse(outcome["candidate_source_units_certified"])
        self.assertTrue(self.safe.is_file())

    def test_independent_full_2026_arrow_sqlite_and_sha(self):
        self.ensure_built()
        with patch.object(VERIFY.M,"MODULE",self.root),\
             patch.object(VERIFY.M,"WORK",self.work),\
             patch.object(VERIFY.M,"ROOT",self.path.parent),\
             patch.object(VERIFY.M,"REPORTS",self.reports):
            result=VERIFY.verify(self.safe,self.verified)
        self.assertEqual(result["private_total_stockday_rows_verified"],22282)
        self.assertEqual(result["private_h5_whole_candidate_rows_verified"],22191)
        self.assertEqual(result["private_h5_mixed_candidate_rows_verified"],82)
        self.assertEqual(result["purchased_month_files_verified"],9)
        self.assertFalse(result["original_market_files_opened"])
        self.assertFalse(result["ready_for_automatic_market_merge"])

    def test_stockday_overlap_purchased_and_candidate_is_rejected(self):
        import sqlite3
        with sqlite3.connect(":memory:") as con:
            con.execute("CREATE TABLE stockday (year INTEGER,symbol TEXT,"
                        "trading_date TEXT,kind TEXT,"
                        "PRIMARY KEY(year,symbol,trading_date)) WITHOUT ROWID")
            counts=__import__("collections").Counter()
            class Writer:
                def write_table(self,*a,**k): pass
            import pyarrow as pa
            M.write_source_rows([paid("600001.XSHG","2026-01-15")],
                "purchased_parquet",2026,1,Writer(),con,counts,M.schema(pa))
            with self.assertRaisesRegex(ValueError,"Duplicate"):
                M.write_source_rows([candidate("SH600001","2026-01-15",
                    "private_h5_mixed_stockday_candidate")],
                    "private_h5_mixed_stockday_candidate",2026,None,
                    Writer(),con,counts,M.schema(pa))

    def test_original_stock_symbol_preserved_while_key_is_canonical(self):
        result=M.normalise(paid("600001.XSHG","2026-01-15"),
                           "purchased_parquet",2026,1)
        self.assertEqual(result["symbol"],"SH600001")
        self.assertEqual(result["source_symbol"],"600001.XSHG")
        self.assertEqual(result["amount"],1000.0)

    def test_purchased_month_mislabelled_row_rejected(self):
        with self.assertRaisesRegex(ValueError,"escaped"):
            M.normalise(paid("600001.XSHG","2026-02-15"),
                        "purchased_parquet",2026,1)

    def test_purchased_negative_amount_rejected(self):
        broken=paid("600001.XSHG","2026-01-15")
        broken["amount"]=-1.0
        with self.assertRaisesRegex(ValueError,"OHLCVA"):
            M.normalise(broken,"purchased_parquet",2026,1)

    def test_malformed_candidate_date_and_label_rejected(self):
        x=candidate("SH600001","2026-07-16",
                    "private_h5_whole_date_candidate")
        with self.assertRaisesRegex(ValueError,"provenance"):
            M.normalise(x,"private_h5_whole_date_candidate")

    def test_manifest_and_privacy_writes_only_under_work(self):
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"WORK",self.work),\
             patch.object(M,"ROOT",self.path.parent),\
             patch.object(M,"REPORTS",self.reports):
            with self.assertRaisesRegex(ValueError,"Require new"):
                M.output_paths(self.root/"outside",self.gate,self.safe)

    def test_private_output_source_integrity_mutation_rejected(self):
        self.ensure_built()
        file=self.path/"purchased"/"month=01"/"day.parquet"
        old=file.read_bytes()
        try:
            file.write_bytes(old+b"tampered")
            with patch.object(VERIFY.M,"MODULE",self.root),\
                 patch.object(VERIFY.M,"WORK",self.work),\
                 patch.object(VERIFY.M,"ROOT",self.path.parent),\
                 patch.object(VERIFY.M,"REPORTS",self.reports):
                with self.assertRaisesRegex(ValueError,"hash invalid"):
                    VERIFY.verify(self.safe,self.reports/"tampered.json")
        finally:
            file.write_bytes(old)

    def test_untrusted_success_safe_cannot_claim_production(self):
        self.ensure_built()
        original=self.safe.read_bytes()
        try:
            doc=json.loads(original)
            doc["ready_for_automatic_market_merge"]=True
            self.safe.write_bytes(json.dumps(doc).encode())
            with patch.object(VERIFY.M,"MODULE",self.root),\
                 patch.object(VERIFY.M,"WORK",self.work),\
                 patch.object(VERIFY.M,"ROOT",self.path.parent),\
                 patch.object(VERIFY.M,"REPORTS",self.reports):
                with self.assertRaisesRegex(ValueError,"Incomplete"):
                    VERIFY.verify(self.safe,self.reports/"forged.json")
        finally:
            self.safe.write_bytes(original)


if __name__=="__main__":
    unittest.main(verbosity=2)
