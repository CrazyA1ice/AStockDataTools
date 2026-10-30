"""Synthetic-only seven historical real-H5 native core311 HMAC bridge tests.

Every original HDF5 in these tests is fictional, never licensed/source files.
The installed Hikyuu C++ runtime is NOT invoked: the subprocess response is
fully stubbed. Windows real-market native testing is an explicit separate gate.
"""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


N=load("pre2011_historical_seven_native_hmac_under_test",
       HERE.parent/"tools"/"verify-pre2011-historical-h5-native-core311-isolated.py")
F=load("pre2011_historical_seven_source_fixture",
       HERE/"test_qualify_pre2011_historical_native_h5_targets_readonly.py")


@contextmanager
def setup_source():
    with F.prepared() as (root,private,full,qualification,qualwork,originals):
        # F.prepared patches the Q imported by the fixture. N imports Q
        # independently, so bind all of its module-local constants to the
        # exact same fictional sandbox for this test.
        home=private.parents[2]
        native_work=home/"work"/"h5_mirror"/"historical_native_isolated"
        with (patch.object(N.P,"REPORTS",F.Q.P.REPORTS),
              patch.object(N.P,"TOTAL_ROWS",F.Q.P.TOTAL_ROWS),
              patch.object(N.SINGLE,"PRIVATE",private),
              patch.object(N.SINGLE,"MODULE",home),
              patch.object(N.Q,"MODULE",home),
              patch.object(N.Q,"WORK",qualwork),
              patch.object(N,"MODULE",home),
              patch.object(N,"WORK",native_work),
              patch.object(N.G.NATIVE.CHECK,"_explicit_python",
                           side_effect=lambda p:Path("/fictional/python311")),
              patch.object(N.G.NATIVE.CHECK,"_sandbox_env",
                           side_effect=lambda stage,exe:{"FAKE_TEST":"isolated"})):
            F.Q.run(root,full,"012345abcdef",qualification)
            final=F.Q.P.REPORTS/"historical-native-seven.json"
            yield root,private,full,qualification,final,native_work,originals


def return_success(**options):
    """Construct a trusted-looking test worker result with ephemeral MACs."""
    def worker(args,**kw):
        m=json.loads(Path(args[-3]).read_text(encoding="utf-8"))
        count=len(m["sample_selections"])
        assert count==7
        assert args[1]=="-I" and args[2]=="-c"
        assert kw["text"] is False and kw["capture_output"] is True
        key=bytes.fromhex(kw["env"]["ASTOCK_HISTORICAL_NATIVE_HMAC_SECRET"])
        # Test-only expected HMACs are computed from fictional source H5.
        root=Path(args[-2]).parents[1]
        selected=[]
        import h5py
        for t in m["sample_selections"]:
            file=Path(args[-2] if t["market"]=="SH" else args[-1])
            with h5py.File(file,"r") as h:
                r=h["data"][t["symbol"]][t["source_native_stock_index"]]
                row={"symbol":t["symbol"]}
                row.update({k:int(r[k]) for k in N.SINGLE.REQUIRED_NUMERIC})
                selected.append(row)
        digest=[N.hmac_row(key,row) for row in selected]
        out={"state":options.get("state","native_complete"),
             "core311":True,"registry_only_temp":True,
             "stock_manager_initialized":True,
             "native_get_kdata_called":True,
             "h5_files_no_write_requested":True,
             "records_examined":7,
             "digest_by_target":digest}
        if options.get("wrong_hmac"):
            out["digest_by_target"][0]="0"*64
        if options.get("mismatch_day"):
            out["state"]="native_target_day_mismatch"
            out["records_examined"]=3
            out["digest_by_target"]=[""]*7
        stdout=(
            N.PHASE+b"before_core\n"+N.PHASE+b"query_ready\n"
            +N.PHASE+b"native_complete\n"+N.PHASE+b"finished\n"
            +N.PREFIX+json.dumps(out).encode("ascii")+b"\n")
        return SimpleNamespace(returncode=0,stdout=stdout,
                               stderr=b"PRIVATE Market Data Filename SHOULD NOT LEAK")
    return worker


class HistoricalSevenNativeHmacSyntheticTests(unittest.TestCase):
    def test_previous_qualified_source_coordinates_revalidated(self):
        with setup_source() as (root,_,full,qualification,_,_,_):
            coords,source,files,manifest,sha,fullsha=N.bind_coordinates(
                full,qualification,root)
            self.assertEqual(len(coords),7)
            self.assertEqual(len(source),7)
            self.assertEqual(len(files),2)
            self.assertTrue(manifest.exists())
            self.assertEqual(len(sha),64)
            self.assertEqual(len(fullsha),64)

    def test_7_native_hmac_success_subprocess_isolation_and_no_market_writes(self):
        with setup_source() as (root,private,full,qualification,out,work,originals):
            watch=[*originals,*private.rglob("*.parquet")]
            orig={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in watch}
            result=N.run(root,full,qualification,"ignored", "012345abcdef",out,
                         runner=return_success())
            self.assertEqual(result["native_matching_h5_historical_stock_days"],7)
            self.assertTrue(result["all_seven_native_h5_historical_records_match"])
            self.assertEqual(result["native_status"],"native_complete")
            self.assertFalse(result["historical_vendor_physical_units_or_adjustments_certified"])
            self.assertFalse(result["historical_security_master_certified"])
            self.assertFalse(result["ready_for_production_data_integration"])
            self.assertFalse(result["purchased_parquet_or_production_market_sqlite_accessed"])
            self.assertFalse(result["hmac_key_or_digests_saved_in_safe"])
            self.assertEqual(orig,{p:hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in watch})
            safe=out.read_text(encoding="utf-8")
            for secret in ("SH600000","SZ000001","19920502","HikyuuData",
                           "PRIVATE Market Data Filename","openPrice",
                           "transAmount","digest_by_target","ASTOCK_HISTORICAL_NATIVE_HMAC_SECRET"):
                self.assertNotIn(secret,safe)
            self.assertTrue((work/"run_012345abcdef").is_dir())

    def test_tampered_manifest_digest_refused_before_native_worker(self):
        with setup_source() as (root,_private,full,qualification,out,work,_):
            p=F.Q.WORK/"native_targets_012345abcdef"/"selected-original-h5-native-targets.json"
            with p.open("ab") as fp:
                fp.write(b"spoofed")
            with self.assertRaisesRegex(ValueError,"SHA"):
                N.run(root,full,qualification,"ignored","012345abcdef",out,
                      runner=return_success())
            self.assertFalse(out.exists())
            self.assertFalse(work.exists())

    def test_tampered_prior_safe_and_private_original_rejected(self):
        with setup_source() as (root,private,full,qualification,out,work,_):
            d=json.loads(qualification.read_text(encoding="utf-8"))
            d["historical_native_units_or_securities_certified"]=True
            qualification.write_text(json.dumps(d),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"not qualified"):
                N.run(root,full,qualification,"ignored","012345abcdef",out,
                      runner=return_success())
            self.assertFalse(work.exists())
        with setup_source() as (root,private,full,qualification,out,work,_):
            data=private/"native_pre2011_1992_012345abcdef"/"h5-native-day.parquet"
            with data.open("ab") as fp:
                fp.write(b"tampered")
            with self.assertRaisesRegex(ValueError,"SHA"):
                N.run(root,full,qualification,"ignored","012345abcdef",out,
                      runner=return_success())
            self.assertFalse(out.exists())

    def test_native_hmac_mismatch_remains_failure_in_safe(self):
        with setup_source() as (root,_,full,qualification,out,_,_):
            r=N.run(root,full,qualification,"ignored","012345abcdef",out,
                    runner=return_success(wrong_hmac=True))
            self.assertFalse(r["all_seven_native_h5_historical_records_match"])
            self.assertEqual(r["native_matching_h5_historical_stock_days"],6)
            self.assertFalse(r["historical_normalized_parquet_or_h5_mirror_created"])

    def test_native_day_mismatch_and_timeout_are_fail_closed(self):
        with setup_source() as (root,_,full,qualification,out,_,_):
            r=N.run(root,full,qualification,"ignored","012345abcdef",out,
                    runner=return_success(mismatch_day=True))
            self.assertEqual(r["native_status"],"native_target_day_mismatch")
            self.assertFalse(r["all_seven_native_h5_historical_records_match"])
            self.assertEqual(r["native_matching_h5_historical_stock_days"],0)
        with setup_source() as (root,_,full,qualification,out,_,_):
            def timeout(args,**kw):
                raise subprocess.TimeoutExpired(cmd="not logged",timeout=60)
            r=N.run(root,full,qualification,"ignored","012345abcdef",out,
                    runner=timeout)
            self.assertEqual(r["native_status"],"native_timeout")
            self.assertFalse(r["all_seven_native_h5_historical_records_match"])
            self.assertNotIn("cmd",out.read_text(encoding="utf-8"))

    def test_reject_malformed_worker_json_and_leaked_raw_fields(self):
        good={
            "state":"native_complete","core311":True,
            "registry_only_temp":True,"stock_manager_initialized":True,
            "native_get_kdata_called":True,"h5_files_no_write_requested":True,
            "records_examined":7,"digest_by_target":["a"*64]*7}
        self.assertEqual(N.decode_worker(N.PREFIX+
            json.dumps(good).encode("ascii"),0),good)
        good["raw_close"]=1234
        self.assertIsNone(N.decode_worker(N.PREFIX+
            json.dumps(good).encode("ascii"),0))
        self.assertIsNone(N.decode_worker(b"private raw stdout",0))
        self.assertIsNone(N.decode_worker(b"",1))

    def test_worker_declares_one_record_index_query_no_market_values_in_print(self):
        self.assertIn("hk.Query(index,index+1,hk.Query.DAY)",N.WORKER)
        self.assertIn('n!=r["source_stock_total_day_count"]',N.WORKER)
        self.assertIn('int(value.datetime.ymd)!=r["datetime"]//10000',N.WORKER)
        self.assertIn("hmac.new(key,msg,hashlib.sha256)",N.WORKER)
        self.assertIn("os._exit(0)",N.WORKER)
        self.assertNotIn("Query(-64",N.WORKER)
        self.assertNotIn("hikyuu_init()",N.WORKER)
        self.assertNotIn("h5py.File",N.WORKER)
        self.assertNotIn("print(raw",N.WORKER)


if __name__=="__main__":
    unittest.main(verbosity=2)
