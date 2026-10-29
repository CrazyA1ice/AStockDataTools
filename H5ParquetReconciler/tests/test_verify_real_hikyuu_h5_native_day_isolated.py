"""Synthetic original-layout H5 only; native subprocess simulated, no real trading files."""
import hashlib
import hmac
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "real_h5_native_hmac_proof_under_test",
    HERE.parent/"tools"/"verify-real-hikyuu-h5-native-day-isolated.py")
G=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


class RealNativeProofSyntheticTests(unittest.TestCase):
    def setUp(self):
        import h5py
        import numpy as np
        self.h5py,self.np=h5py,np
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.h5root=self.base/"HikyuuData"
        self.h5root.mkdir()
        self.reports=self.base/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.work=self.base/"H5ParquetReconciler"/"work"/"h5_mirror"/"real_day_native"
        self.proof=self.reports/"raw-two-source-v1.json"
        self.out=self.reports/"real-hikyuu-native-v1.json"
        for patcher in (patch.object(G.AUDIT,"REPORTS",self.reports),
                        patch.object(G,"WORK",self.work),
                        patch.object(G.NATIVE.CHECK,"_explicit_python",
                                     return_value=Path("/fake/python311")),
                        patch.object(G.NATIVE.CHECK,"_sandbox_env",
                                     return_value={"FOO":"BAR"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_h5()
        self.proof.write_text(json.dumps({
            "format":G.RAW_GATE.FORMAT,
            "sample_day":"2026-09-30",
            "two_selected_stock_days_compared":2,
            "h5_raw_day_records_read":2,
            "raw_h5_record_used_not_native_cpp_driver_decoding":True,
            "sources_read_only_no_h5_or_parquet_writes":True,
            "no_real_ohlcva_or_raw_timestamp_values_in_report":True,
            "parquet_vendor_physical_amount_unit_certified":False,
            "parquet_vendor_physical_volume_unit_certified":False,
            "native_hikyuu_driver_unit_mapping_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "comparison":{
                "candidate_factor_multiply_raw_h5_record_to_parquet_value":{
                    "volume":{"100":2},"amount":{"1000":2}}
            },
        }),encoding="utf-8")

    def write_h5(self):
        np,h5py=self.np,self.h5py
        dtype=np.dtype([
            ("datetime","<u8"),("openPrice","<u4"),("highPrice","<u4"),
            ("lowPrice","<u4"),("closePrice","<u4"),("transCount","<u8"),
            ("transAmount","<u8")
        ])
        self.values={}
        for symbol,s in (("SH600000",1),("SZ000001",2)):
            vals={
                "datetime":202609300000,
                "openPrice":10000+s*100,
                "highPrice":10200+s*100,
                "lowPrice":9800+s*100,
                "closePrice":10100+s*100,
                "transCount":120+s,
                "transAmount":340+s
            }
            self.values[symbol]=vals
            file=self.h5root/(symbol[:2].lower()+"_day.h5")
            record=np.zeros(3,dtype=dtype)
            record["datetime"]=[202609290000,202609300000,202610080000]
            for key,v in vals.items():
                record[1][key]=v
            with h5py.File(file,"w") as f:
                f.create_group("data").create_dataset(symbol,data=record)

    def runner(self,bad="none",phase=True):
        def call(args,**kwargs):
            self.assertEqual(args[1:3],["-I","-c"])
            # The module is legitimately named H5ParquetReconciler.
            # Checking arbitrary path text for "Parquet" wrongly rejects
            # every Windows sandbox path. Inspect the actual child argv:
            # precisely one isolated stage and two direct H5 source files.
            self.assertEqual(len(args),7)
            stage=Path(args[4])
            self.assertEqual(stage.resolve(),Path(kwargs["cwd"]).resolve())
            self.assertEqual(stage.name,"run001")
            self.assertEqual(stage.parent.resolve(),self.work.resolve())
            self.assertEqual(
                tuple(Path(arg).resolve() for arg in args[5:7]),
                (self.h5root.joinpath("sh_day.h5").resolve(),
                 self.h5root.joinpath("sz_day.h5").resolve()))
            self.assertTrue(all(Path(arg).suffix.lower()==".h5"
                                for arg in args[5:7]))
            self.assertFalse(any(Path(arg).suffix.lower()==".parquet"
                                 for arg in args[4:7]))
            self.assertEqual(
                set(kwargs["env"]),
                {"FOO","ASTOCK_NATIVE_REAL_HMAC_SECRET"})
            self.assertEqual(kwargs["text"],False)
            self.assertEqual(kwargs["capture_output"],True)
            self.assertEqual(kwargs["env"].get("ASTOCK_NATIVE_REAL_HMAC_SECRET") is not None,
                             True)
            key=bytes.fromhex(kwargs["env"]["ASTOCK_NATIVE_REAL_HMAC_SECRET"])
            signed={symbol:G.signed_record(key,symbol,self.values[symbol])
                    for symbol in G.SYMBOLS}
            if bad=="wrong_mac":
                signed["SH600000"]="0"*64
            if bad=="wrong_fields":
                signed["SZ000001"]=""
            result={
                "state":"native_complete",
                "core311":True,
                "registry_only_temp":True,
                "stock_manager_initialized":True,
                "native_get_kdata_called":True,
                "h5_file_read_only":True,
                "records_examined_per_stock":{"SH600000":3,"SZ000001":3},
                "hmac_by_stock":signed,
            }
            raw=(b"native logs in GBK\xff\xfc\n"+
                 (G.STAGE_MARKER+b"finished\n" if phase else b"")+
                 G.MARKER+json.dumps(result).encode("ascii")+b"\n")
            return SimpleNamespace(returncode=0,stdout=raw,stderr=b"arbitrary")
        return call

    def run_it(self,bad="none",phase=True,run_id="run001"):
        return G.run(self.h5root,self.proof,self.out,Path("/fake/python311"),
                     run_id=run_id,runner=self.runner(bad,phase))

    def test_hmac_native_simulation_matches_two_actual_synthetic_h5_records(self):
        originals={p:hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in self.h5root.glob("*.h5")}
        result=self.run_it()
        self.assertTrue(result["all_two_native_h5_real_daily_records_match"])
        self.assertEqual(result["native_status"],"native_complete")
        self.assertEqual(result["native_matching_stock_day_count"],2)
        self.assertFalse(result["parquet_to_hikyuu_native_units_certified"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertEqual(originals,{p:hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in originals})
        payload=self.out.read_text(encoding="utf-8")
        for val in ("202609300000","SH600000","SZ000001","10200","340",
                    "ASTOCK_NATIVE_REAL_HMAC_SECRET","fake/python311",
                    "HikyuuData"):
            self.assertNotIn(val,payload)
        self.assertEqual(len(list(self.work.glob("run001"))),1)

    def test_native_runner_allows_h5parquetreconciler_module_name(self):
        # Regression for Windows temp paths like
        # .../H5ParquetReconciler/work/h5_mirror/real_day_native/run001.
        # Only actual argv path suffixes / identities are checked, not
        # whether their *directory name* contains a word like Parquet.
        self.assertIn("Parquet",str(self.work))
        out=self.run_it()
        self.assertEqual(out["native_matching_stock_day_count"],2)
        self.assertTrue(out["all_two_native_h5_real_daily_records_match"])

    def test_hmac_digest_rejects_tampering_of_one_source_value(self):
        key=b"q"*32
        a=G.signed_record(key,"SH600000",self.values["SH600000"])
        tampered=dict(self.values["SH600000"])
        tampered["transAmount"]+=1
        self.assertNotEqual(a,G.signed_record(key,"SH600000",tampered))
        self.assertEqual(len(a),64)

    def test_native_wrong_digest_is_not_a_pass(self):
        report=self.run_it(bad="wrong_mac")
        self.assertFalse(report["all_two_native_h5_real_daily_records_match"])
        self.assertEqual(report["native_matching_stock_day_count"],1)

    def test_missing_finished_phase_must_fail_closed(self):
        report=self.run_it(phase=False)
        self.assertFalse(report["all_two_native_h5_real_daily_records_match"])

    def test_wrong_native_payload_and_missing_mac_are_rejected(self):
        invalid={ "state":"native_complete","core311":True,
                  "registry_only_temp":True,
                  "stock_manager_initialized":True,
                  "native_get_kdata_called":True,
                  "h5_file_read_only":True,
                  "records_examined_per_stock":{"SH600000":3,"SZ000001":3},
                  "hmac_by_stock":{"SH600000":"invalid","SZ000001":""}}
        self.assertIsNone(G.decode_status(
            G.MARKER+json.dumps(invalid).encode("ascii"),0))
        self.assertIsNone(G.decode_status(b"garbage",0))
        self.assertIsNone(G.decode_status(G.MARKER+b"{}",1))

    def test_previous_safe_claim_of_certified_units_is_rejected(self):
        doc=json.loads(self.proof.read_text(encoding="utf-8"))
        doc["native_hikyuu_driver_unit_mapping_certified"]=True
        self.proof.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"prior successful"):
            self.run_it()
        self.assertFalse(self.work.exists())

    def test_h5_missing_or_wrong_dtype_cannot_initialize_native(self):
        path=self.h5root/"sz_day.h5"
        path.unlink()
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.work.exists())

    def test_native_timeout_produces_safe_failed_status(self):
        import subprocess
        def slow(*args,**kwargs):
            raise subprocess.TimeoutExpired(cmd="hikyuu",timeout=10,
                                            output=G.STAGE_MARKER+b"before_native\n")
        out=G.run(self.h5root,self.proof,self.out,Path("/fake/python311"),
                  runner=slow,timeout=10)
        self.assertEqual(out["native_status"],"native_timeout")
        self.assertFalse(out["all_two_native_h5_real_daily_records_match"])
        self.assertEqual(out["native_final_phase"],"before_native")
        self.assertEqual(out["native_last_work_phase"],"before_native")

    def test_original_h5_changed_during_native_is_refused(self):
        def replace(args,**kwargs):
            path=self.h5root/"sh_day.h5"
            with path.open("ab") as f:
                f.write(b"change")
            return self.runner()(args,**kwargs)
        with self.assertRaisesRegex(ValueError,"changed"):
            G.run(self.h5root,self.proof,self.out,Path("/fake/python311"),
                  runner=replace)
        self.assertFalse(self.out.exists())

    def test_reports_cannot_be_overwritten_and_run_id_unique(self):
        self.out.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.out.unlink()
        self.run_it()
        other=self.reports/"second.json"
        with self.assertRaisesRegex(ValueError,"run id already"):
            G.run(self.h5root,self.proof,other,Path("/fake/python311"),
                  runner=self.runner())
        self.assertFalse(other.exists())

    def test_invalid_timeout_runid_and_outside_report_rejected(self):
        for timeout in (0,5,121,True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    G.run(self.h5root,self.proof,self.out,
                          Path("/fake/python311"),timeout=timeout,
                          runner=self.runner())
        for run_id in ("../x","..","a","x"*41):
            with self.subTest(run_id=run_id):
                with self.assertRaises(ValueError):
                    G.run(self.h5root,self.proof,self.out,
                          Path("/fake/python311"),run_id=run_id,
                          runner=self.runner())
        outside=self.base/"leak.json"
        with self.assertRaises(ValueError):
            G.run(self.h5root,self.proof,outside,Path("/fake/python311"),
                  runner=self.runner())

    def test_safe_native_query_failure_status_is_accepted(self):
        body={
            "state":"failed_at_before_query",
            "core311":True,"registry_only_temp":True,
            "stock_manager_initialized":True,
            "native_get_kdata_called":False,
            "h5_file_read_only":True,
            "records_examined_per_stock":{"SH600000":0,"SZ000001":0},
            "hmac_by_stock":{"SH600000":"","SZ000001":""},
        }
        raw=G.MARKER+json.dumps(body,sort_keys=True).encode("ascii")
        self.assertEqual(G.decode_status(raw,0),body)
        body["state"]="failed_at_before_get_kdata"
        raw=G.MARKER+json.dumps(body,sort_keys=True).encode("ascii")
        self.assertEqual(G.decode_status(raw,0),body)
        body["state"]="native_target_day_not_found"
        raw=G.MARKER+json.dumps(body,sort_keys=True).encode("ascii")
        self.assertEqual(G.decode_status(raw,0),body)

    def test_unrecognized_or_excess_native_errors_are_never_echoed(self):
        body={
            "state":"failed_at_untrusted_native_message_including_path",
            "core311":True,"registry_only_temp":True,
            "stock_manager_initialized":True,
            "native_get_kdata_called":True,"h5_file_read_only":True,
            "records_examined_per_stock":{"SH600000":1,"SZ000001":0},
            "hmac_by_stock":{"SH600000":"","SZ000001":""},
        }
        raw=G.MARKER+json.dumps(body).encode("ascii")
        self.assertIsNone(G.decode_status(raw,0))
        body["state"]="failed_at_before_get_kdata"
        body["arbitrary_raw_ohlcva"]="restricted"
        raw=G.MARKER+json.dumps(body).encode("ascii")
        self.assertIsNone(G.decode_status(raw,0))

    def test_failure_code_and_stage_survive_to_safe_report_without_raw_logs(self):
        def controlled_failure(args,**kw):
            body={
                "state":"failed_at_before_get_kdata",
                "core311":True,"registry_only_temp":True,
                "stock_manager_initialized":True,
                "native_get_kdata_called":True,
                "h5_file_read_only":True,
                "records_examined_per_stock":{"SH600000":0,"SZ000001":0},
                "hmac_by_stock":{"SH600000":"","SZ000001":""},
            }
            out=(G.STAGE_MARKER+b"before_get_kdata\\n"+
                 G.STAGE_MARKER+b"finished\\n"+
                 G.MARKER+json.dumps(body).encode("ascii")+b"\\n")
            return SimpleNamespace(returncode=0,stdout=out,stderr=b"PRIVATE Native failure info")
        result=G.run(self.h5root,self.proof,self.out,Path("/fake/python311"),
                     runner=controlled_failure)
        self.assertEqual(result["native_status"],"failed_at_before_get_kdata")
        self.assertEqual(result["native_last_work_phase"],"before_get_kdata")
        self.assertFalse(result["all_two_native_h5_real_daily_records_match"])
        text=self.out.read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE",text)
        self.assertNotIn("HikyuuData",text)
        self.assertFalse(result["ready_for_full_market_mirror"])

    def test_worker_never_prints_real_ohlcva_and_no_source_h5_writes(self):
        self.assertNotIn("record.amount",G.WORKER.split("print(PREFIX")[1])
        self.assertIn("os._exit(0)",G.WORKER)
        self.assertIn("query=hk.Query(first,n,hk.Query.DAY)",G.WORKER)
        self.assertIn("stock.get_count(hk.Query.DAY)",G.WORKER)
        self.assertIn("recs=stock.get_kdata(query)",G.WORKER)
        self.assertNotIn("hk.Query(-64,hk.Query.DAY)",G.WORKER)
        self.assertNotIn("h5py.File",G.WORKER)
        self.assertNotIn("hikyuu_init()",G.WORKER)
        self.assertIn("hmac.new(key,msg,hashlib.sha256)",G.WORKER)


if __name__=="__main__":
    unittest.main(verbosity=2)
