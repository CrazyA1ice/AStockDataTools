"""Synthetic historical purchased DAY 2015 and 2016+one verified H5 gap."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(label,file):
    spec=importlib.util.spec_from_file_location(label,TOOLS/file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M=load("historical_purchased_day_builder_tests",
       "materialize-private-2011-2025-purchased-year.py")
V=load("historical_purchased_day_independent_tests",
       "verify-private-2011-2025-purchased-year.py")


def ts(day):
    return int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)


def paid(sym,day):
    return {"ts":ts(day),"symbol":sym,
            "open":10.0,"high":11.0,"low":9.0,"close":10.5,
            "volume":300.0,"amount":1000.0}


def h5(sym,day):
    return {**paid(sym,day),"trading_date":day,
            "value_source":"private_h5_mixed_stockday_candidate"}


class HistoricalPrivateAnnualTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        t=tempfile.TemporaryDirectory(prefix="hist_2016_phys_",dir=scratch)
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.work=self.root/"work"/"unified_parquet"
        self.private_root=self.work/"physical_years"
        self.reports=self.root/"reports"
        self.reports.mkdir()
        self.purchased=self.root/"purchased"
        self.day=self.purchased/"day"
        self.day.mkdir(parents=True)
        self.readme=self.purchased/"【先看我】数据说明.txt"
        self.readme.write_bytes(b"synthetic README")
        self.qdc=self.purchased/"文件校验清单.txt"
        self.qdc.write_bytes(b"synthetic full manifest")
        self.readme_sha=hashlib.sha256(self.readme.read_bytes()).hexdigest()
        self.qdc_sha=hashlib.sha256(self.qdc.read_bytes()).hexdigest()
        purchased_schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(f,pa.float64()) for f in M.PHYS.F),
        ])
        self.record={}
        self.sources={}
        for year,rows in [
            (2015,[paid("600001.XSHG","2015-08-17")]),
            (2016,[paid("600001.XSHG","2016-08-17"),
                   paid("000002.XSHE","2016-08-17")]),
        ]:
            p=self.day/f"{year}.parquet"
            pq.write_table(pa.Table.from_pylist(rows,schema=purchased_schema),p)
            self.record[year]={"size":p.stat().st_size,
                               "rows":len(rows),"sha":M.ST.sha(p)}
            self.sources[year]=p
        self.h5_dir=self.root/"source_candidates"/"year=2016"
        self.h5_dir.mkdir(parents=True)
        self.h5_file=self.h5_dir/"day.parquet"
        pq.write_table(pa.Table.from_pylist([
            h5("SH600002","2016-08-18")
        ],schema=M.ST.candidate_schema(pa)),self.h5_file)
        self.candidate_safe=self.reports/"source-safe.json"
        self.candidate_safe.write_bytes(b'{"source":"private_only"}\n')
        self.source_manifest=self.h5_dir.parent/"manifest.json"
        self.source_manifest.write_bytes(b'{"synthetic":true}\n')
        self.candidate_doc={
            "source_version_sha256":M.SOURCE_VERSION,
            "candidate_year_rows":{"2016":1,"2026":22273},
            "partition_sha256":{"2016":M.ST.sha(self.h5_file)},
            "manifest_sha256":M.ST.sha(self.source_manifest),
        }
        self.candidate_sha=hashlib.sha256(self.candidate_safe.read_bytes()).hexdigest()
        self.dir_for_year={}
        self.safes={}

    def mock_input(self,source,year,readme_sha,manifest_sha):
        self.assertEqual(Path(source),self.purchased)
        self.assertEqual(readme_sha,self.readme_sha)
        self.assertEqual(manifest_sha,self.qdc_sha)
        p=self.sources[year]
        return p,self.record[year],self.readme,self.qdc

    def source(self,path):
        self.assertEqual(Path(path),self.candidate_safe)
        return self.candidate_doc,self.candidate_sha,self.h5_dir.parent,self.source_manifest

    def full_gap(self,source,out):
        if getattr(self,"current_year",None)!=2016:
            raise AssertionError("Full 22,274-row H5 audit may only run for 2016")
        Path(out).write_bytes(b'{"all":22274,"offline":true}\n')
        return {"total_h5_only_day_candidates_verified":22274,
                "mixed_date_candidate_rows_verified":83,
                "partition_year_rows_verified":{"2016":1,"2026":22273},
                "candidate_source_units_certified":False}

    def build(self,year):
        self.current_year=year
        folder=self.private_root/f"physical_{year}_{year:012x}"
        gate=self.reports/f"history-gate-{year}.json"
        safe=self.reports/f"history-safe-{year}.json"
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"WORK",self.work),\
             patch.object(M,"ROOT",self.private_root),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M,"purchased_input",side_effect=self.mock_input),\
             patch.object(M.V,"source",side_effect=self.source),\
             patch.object(M.V,"verify",side_effect=self.full_gap):
            result=M.materialize(
                year,self.purchased,self.candidate_safe,self.readme_sha,
                self.qdc_sha,folder,gate,safe)
        self.dir_for_year[year]=folder
        self.safes[year]=safe
        return result

    def check(self,year,out=None):
        target=out or self.reports/f"verified-{year}.json"
        with patch.object(V.M,"MODULE",self.root),\
             patch.object(V.M,"WORK",self.work),\
             patch.object(V.M,"ROOT",self.private_root),\
             patch.object(V.M,"REPORTS",self.reports):
            return V.verify(self.safes[year],target)

    def test_2016_purchased_two_and_one_h5_gap_exact_float64(self):
        r=self.build(2016)
        self.assertEqual(r["purchased_original_rows"],2)
        self.assertEqual(r["h5_mixed_candidate_rows"],1)
        self.assertEqual(r["total_private_physical_rows"],3)
        self.assertEqual(set(r["physical_partition_sha256"]),{"purchased","h5_gap_2016"})
        a=self.check(2016)
        self.assertEqual(a["private_purchased_rows_verified"],2)
        self.assertEqual(a["private_h5_mixed_candidate_rows_verified"],1)
        self.assertEqual(a["private_partition_files_verified"],2)
        self.assertTrue(a["original_float64_roundtrip_fingerprint_verified"])

    def test_2015_purchased_only_does_not_require_full_22274_decode(self):
        r=self.build(2015)
        self.assertEqual(r["total_private_physical_rows"],1)
        self.assertEqual(r["h5_mixed_candidate_rows"],0)
        self.assertEqual(set(r["physical_partition_sha256"]),{"purchased"})
        a=self.check(2015)
        self.assertEqual(a["private_total_rows_verified"],1)
        self.assertEqual(a["private_partition_files_verified"],1)
        self.assertFalse(a["original_h5_source_reopened"])

    def test_duplicate_2016_purchased_and_h5_stockday_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist([
            h5("SH600001","2016-08-17")
        ],schema=M.ST.candidate_schema(pa)),self.h5_file)
        self.candidate_doc["partition_sha256"]["2016"]=M.ST.sha(self.h5_file)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            self.build(2016)
        self.assertFalse((self.reports/"history-safe-2016.json").exists())

    def test_modified_original_purchased_SHA_fails_before_writes(self):
        self.sources[2015].write_bytes(
            self.sources[2015].read_bytes()+b"modified")
        # Exercise actual source hash gate, not synthetic data import.
        with self.assertRaisesRegex(ValueError,"Original"):
            with patch.object(M.QDC,"parse_manifest",return_value={
                "2015.parquet":self.record[2015]}):
                M.purchased_input(self.purchased,2015,
                                  self.readme_sha,self.qdc_sha)
        self.assertFalse(self.private_root.exists())

    def test_private_written_partition_sha_tamper_rejected(self):
        self.build(2015)
        p=self.dir_for_year[2015]/"purchased"/"day.parquet"
        p.write_bytes(p.read_bytes()+b"modified")
        with self.assertRaisesRegex(ValueError,"SHA"):
            self.check(2015)
        self.assertFalse((self.reports/"verified-2015.json").exists())

    def test_fake_production_ready_safe_rejected(self):
        self.build(2015)
        safe=self.safes[2015]
        payload=json.loads(safe.read_bytes())
        payload["ready_for_h5_mirror"]=True
        safe.write_bytes(json.dumps(payload).encode())
        with self.assertRaisesRegex(ValueError,"Incomplete"):
            self.check(2015)

    def test_historical_unsafe_output_folder_rejected(self):
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"ROOT",self.private_root),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M,"WORK",self.work):
            with self.assertRaisesRegex(ValueError,"fresh private"):
                M.locations(2016,self.root/"outside"/"physical_2016_abcdefabcdef",
                            self.reports/"gate.json",self.reports/"safe.json")

    def test_history_year_outside_received_bundle_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"2011..2025"):
            M.locations(2026,self.root/"x",self.root/"y",self.root/"z")

    def test_original_source_symbol_and_timestamp_preserved(self):
        x=M.PHYS.normalise(paid("600001.XSHG","2015-08-17"),
                           "purchased_parquet",year=2015)
        self.assertEqual(x["symbol"],"SH600001")
        self.assertEqual(x["source_symbol"],"600001.XSHG")
        self.assertEqual(x["ts"],ts("2015-08-17"))

    def test_repeated_private_year_never_overwritten(self):
        self.build(2015)
        with self.assertRaisesRegex(ValueError,"fresh private"):
            self.build(2015)


if __name__=="__main__":
    unittest.main(verbosity=2)
