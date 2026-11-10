"""Physical eight-cycle Arrow dataset: no-source-copy, SHA/stat and cutoff tests.

All synthetic Parquet values are fictional and temporary; no market data.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "actual_asof_eight_cycle_physical_arrow_dataset",
    HERE.parent/"tools"/"build-asof20261013-unified-eight-cycle-parquet-dataset.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
UTC8=timezone(timedelta(hours=8))
ROOT=Path("market")

def create_source(path,day="2026-10-13",*,invalid=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    t=int(datetime.fromisoformat(day).replace(tzinfo=UTC8).timestamp()*1000)
    table=pa.table({
        "ts":pa.array([t],type=pa.int64()),
        "symbol":pa.array(["SH600000"]),
        "open":pa.array([1.0],type=pa.float64()),
        "high":pa.array([1.2],type=pa.float64()),
        "low":pa.array([0.8],type=pa.float64()),
        "close":pa.array([1.1],type=pa.float64()),
        "volume":pa.array([100.0],type=pa.float64()),
        "amount":pa.array(["100.0"] if invalid else [100.0]),
    })
    pq.write_table(table,path)
    return path

class PhysicalEightCycleParquetDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name)
        self.module=base/"H5ParquetReconciler"
        self.module.mkdir()
        self.work=self.module/"work"/"unified_parquet"
        self.work.mkdir(parents=True)
        self.market=base/"market"
        self.market.mkdir()
        self.paths={}
        self.patches=[
            patch.object(M,"MODULE",self.module),
            patch.object(M,"WORK",self.work),
            patch.object(M,"DATASETS",self.work/"datasets"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        for period in M.PERIODS:
            file=create_source(
                self.market/"AllCycleAStockData"/period/"2026.parquet")
            self.paths[period]=file
        self.paid_file=self.paths["5min"]
        self.private=create_source(
            self.module/"work"/"unified_parquet"/"h5_only"/"15min.parquet")
        self.dataset=None
        self.catalog="a"*64

    def pseudo_payload(self):
        entries={}
        for p,file in self.paths.items():
            st=file.stat()
            entries[p]=[M._item(
                "purchased_root",file.relative_to(self.market).as_posix(),
                "purchased_original",
                stat={"size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns})]
        return {
            "format":M.MANIFEST_VERSION,
            "source_catalog_sha256":self.catalog,
            "asof_inclusive":"2026-10-13",
            "periods":list(M.PERIODS),
            "period_physical_files":entries,
            "ready_for_production_query":False,
            "no_purchased_parquet_copy":True,
        }

    def write_version(self,payload=None):
        payload=self.pseudo_payload() if payload is None else payload
        file,_=M.write_manifest(payload)
        return file,M.fingerprint(payload)

    def test_deterministic_manifest_hash_and_no_market_copy(self):
        payload=self.pseudo_payload()
        path,first=M.write_manifest(payload)
        self.assertTrue(first)
        again,created=M.write_manifest(payload)
        self.assertEqual(path,again)
        self.assertFalse(created)
        self.assertEqual(len(list(path.parent.iterdir())),1)
        self.assertEqual(
            len(list((self.market/"AllCycleAStockData"/"5min").iterdir())),1)

    def test_original_purchased_file_stat_drift_fails_closed(self):
        file=self.paid_file
        st=file.stat()
        ref={"size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns}
        M.checked("purchased_root",file.relative_to(self.market).as_posix(),
                  self.market,self.module,purchased_stat=ref)
        file.write_bytes(file.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"stat changed"):
            M.checked("purchased_root",file.relative_to(self.market).as_posix(),
                      self.market,self.module,purchased_stat=ref)

    def test_private_content_sha_drift_fails_closed(self):
        rel=self.private.relative_to(self.module).as_posix()
        digest=M.sha(self.private)
        M.checked("private_module",rel,self.market,self.module,digest)
        self.private.write_bytes(self.private.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"SHA mismatch"):
            M.checked("private_module",rel,self.market,self.module,digest)

    def test_outside_path_and_non_parquet_refused(self):
        for path in ("../secrets.parquet","/etc/hosts.parquet",
                     "dir//bad.parquet","foo.json","dir\\evil.parquet"):
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,"Unsafe"):
                M.checked("private_module",path,self.market,self.module)

    def test_manifest_byte_tampering_rejected(self):
        file,digest=self.write_version()
        file.write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Immutable Parquet dataset"):
            M.write_manifest(self.pseudo_payload())
        with self.assertRaisesRegex(ValueError,"Wrong dataset manifest"):
            M.load_manifest(file,self.market,expected_sha=digest,
                            verify_sources=False)

    def test_wrong_source_version_sha_rejected(self):
        file,digest=self.write_version()
        with self.assertRaisesRegex(ValueError,"SHA or canonical"):
            M.load_manifest(file,self.market,expected_sha="f"*64,
                            verify_sources=False)

    def test_all_eight_periods_are_real_pyarrow_datasets(self):
        file,digest=self.write_version()
        with patch.object(M,"load_manifest",
                          return_value=(self.pseudo_payload(),digest)):
            for period in M.PERIODS:
                with self.subTest(period=period):
                    dataset=M.open_period_dataset(
                        file,self.market,period,expected_sha=digest,
                        allow_research_unverified_units=True)
                    table=dataset.to_table(columns=["ts","symbol","close"])
                    self.assertEqual(table.num_rows,1)
                    self.assertEqual(table["close"].to_pylist(),[1.1])
        self.assertFalse(list((self.work/"datasets").glob("*.parquet")))

    def test_scanner_hard_asof_date_excludes_newer_physical_bar(self):
        self.paths["1min"].unlink()
        t1=create_source(self.paths["1min"],"2026-10-13")
        t2=create_source(
            self.market/"AllCycleAStockData"/"1min"/"2026-late.parquet",
            "2026-10-15")
        p=self.pseudo_payload()
        stat=t2.stat()
        p["period_physical_files"]["1min"].append(M._item(
            "purchased_root",t2.relative_to(self.market).as_posix(),
            "purchased_original",stat={
                "size_bytes":stat.st_size,"mtime_ns":stat.st_mtime_ns}))
        file,digest=self.write_version(p)
        with patch.object(M,"load_manifest",return_value=(p,digest)):
            stream=M.scan_period_asof(
                file,self.market,"1min",expected_sha=digest,
                allow_research_unverified_units=True)
            self.assertEqual(stream.to_table().num_rows,1)

    def test_research_unit_opt_in_is_mandatory(self):
        file,digest=self.write_version()
        with self.assertRaisesRegex(ValueError,"Research source-unit opt-in"):
            M.open_period_dataset(file,self.market,"day",
                                  expected_sha=digest)
        self.assertTrue(file.is_file())

    def test_source_catalog_change_prevents_manifest_use(self):
        file,digest=self.write_version()
        with patch.object(M,"assemble",return_value={
            **self.pseudo_payload(),"source_catalog_sha256":"b"*64}):
            with self.assertRaisesRegex(ValueError,"stale underlying"):
                M.load_manifest(file,self.market,expected_sha=digest,
                                verify_sources=True)

    def test_cutoff_is_fixed_not_october_end(self):
        self.assertEqual(M.DATE_CUTOFF,"2026-10-13")
        self.assertEqual(M.ASOF.isoformat(),"2026-10-13")
        self.assertEqual(M.MODERN_ROWS,14137981)
        self.assertEqual(M.PRIVATE_DAY_ROWS,22274)

if __name__=="__main__":
    unittest.main()
