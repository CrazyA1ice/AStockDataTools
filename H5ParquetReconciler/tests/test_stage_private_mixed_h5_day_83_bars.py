"""No licensed market IO: fictional H5 bars/keys, fake preverified audit proofs."""
import contextlib
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


HERE=Path(__file__).resolve().parent


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


M=load("private_83_stager_under_test",
       HERE.parent/"tools"/"stage-private-mixed-h5-day-83-bars.py")


def sample_keys():
    # Never from real stocks: unique fictional codes only.
    return {
        *( (f"SH600{i:03d}",201609300000) for i in range(1)),
        *( (f"SH600{i:03d}",202604080000) for i in range(1,83)),
    }


def source_h5(root,keys,bad_price=False):
    import h5py
    import numpy as np

    folder=root/"HikyuuData"
    folder.mkdir(parents=True,exist_ok=True)
    dtype=np.dtype([(n,"<i8") for n in M.CORE.H5_FIELDS])
    by_code={}
    for symbol,stamp in keys:
        by_code.setdefault(symbol,[]).append(stamp)
    for market in ("sh","sz","bj"):
        with h5py.File(folder/f"{market}_day.h5","w") as fh:
            data=fh.create_group("data")
            if market!="sh":
                continue
            for symbol,days in sorted(by_code.items()):
                vals=np.zeros(len(days),dtype=dtype)
                vals["datetime"]=sorted(days)
                vals["openPrice"]=10000
                vals["highPrice"]=11000
                vals["lowPrice"]=9000
                vals["closePrice"]=10000
                vals["transCount"]=42
                vals["transAmount"]=3333
                if bad_price and symbol=="SH600000":
                    vals["highPrice"]=100
                data.create_dataset(symbol,data=vals)


def valid_audit_files(fake_root,keys):
    reports=fake_root/"reports"
    priv=fake_root/"work"/"unified_parquet"/"mixed_day_key_manifests"/"keys_0123456789ab"
    reports.mkdir(parents=True,exist_ok=True)
    priv.mkdir(parents=True,exist_ok=True)
    originals={}
    for name in ("ledger","2016","2026","plan"):
        p=reports/f"{name}.json"
        payload=f'{{"source":"{name}"}}\n'.encode()
        p.write_bytes(payload)
        originals[name]=(p,payload)
    year_dates={
        2016:[{"date":"2016-09-30"}],
        2026:[{"date":"2026-04-08"}],
    }
    private_doc={
        "format":M.KEYS.PRIVATE_FORMAT,
        "period":"day",
        "source_state_stat_sha256":"source-state",
        "offline_mixed_plan_sha256":M.sha256(originals["plan"][1]),
        "original_historical_ledger_sha256":M.sha256(originals["ledger"][1]),
        "candidate_key_count":83,
        "h5_values_or_ohlcva_exported":False,
        "ready_for_unattended_staging":False,
        "source_purchased_parquet_priority_required":True,
        "candidate_symbol_day_keys":[{
            "date":f"{stamp//100000000:04d}-{stamp//1000000%100:02d}-{stamp//10000%100:02d}",
            "symbol":symbol,
        } for symbol,stamp in sorted(keys)],
    }
    keyfile=priv/"keys.json"
    keypayload=(json.dumps(private_doc,ensure_ascii=False,sort_keys=True)+"\n").encode()
    keyfile.write_bytes(keypayload)
    safe={
        "format":M.KEYS.FORMAT,
        "live_verified_nonquarantined_h5_only_stockdays":83,
        "quarantined_stockdays_excluded_from_exact_live_keyset":5,
        "original_market_files_written":False,
        "private_parquet_market_rows_staged":False,
        "private_or_production_active_pointer_modified":False,
        "ready_for_automatic_merge":False,
        "original_historical_ledger_sha256":M.sha256(originals["ledger"][1]),
        "offline_mixed_plan_sha256":M.sha256(originals["plan"][1]),
        "original_source_stat_sha256":"source-state",
        "private_key_manifest_relative_path":
            "work/unified_parquet/mixed_day_key_manifests/keys_0123456789ab/keys.json",
        "private_key_manifest_sha256":M.sha256(keypayload),
    }
    safe_path=reports/"live.json"
    safe_path.write_text(json.dumps(safe,ensure_ascii=False),encoding="utf-8")
    return originals,year_dates,safe_path,keyfile,reports


@contextlib.contextmanager
def temporary_module_dir(home):
    with (patch.object(M,"MODULE",home),
          patch.object(M,"WORK",home/"work"),
          patch.object(M,"UNIFIED",home/"work"/"unified_parquet"),
          patch.object(M,"STAGES",home/"work"/"unified_parquet"/"mixed_day_stages"),
          patch.object(M,"REPORTS",home/"reports"),
          patch.object(M.KEYS,"REPORTS",home/"reports"),
          patch.object(M.KEYS,"PRIVATE",home/"work"/"unified_parquet"/"mixed_day_key_manifests")):
        yield


class MixedPrivateStageSyntheticTests(unittest.TestCase):
    def test_eighty_three_fictional_h5_rows_roundtrip_candidates(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"market"
            keys=sample_keys()
            source_h5(root,keys)
            bars=M.normalize_private_h5_rows(root,keys)
            self.assertEqual(len(keys),83)
            self.assertEqual(len(bars),83)
            self.assertEqual({x["source"] for x in bars},
                             {"hikyuu_h5_mixed_day_candidate"})
            self.assertTrue(all(x["volume"]==4200.0 and
                                x["amount"]==3333000.0 for x in bars))
            f=Path(tmp)/"verify.parquet"
            pq.write_table(pa.Table.from_pylist(bars),f)
            self.assertEqual(pq.read_table(f).num_rows,83)

    def test_invalid_h5_price_geometry_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"market"
            keys=sample_keys()
            source_h5(root,keys,bad_price=True)
            with self.assertRaisesRegex(ValueError,"geometry"):
                M.normalize_private_h5_rows(root,keys)

    def test_missing_h5_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"Missing or symlinked"):
                M.normalize_private_h5_rows(Path(tmp),sample_keys())

    def test_missing_one_h5_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"market"
            keys=sample_keys()
            # Keep the H5 stock group present, but omit its required date.
            # An entirely missing stock dataset is a different error path.
            missing=("SH600001",202604080000)
            self.assertIn(missing,keys)
            source_h5(root,(keys-{missing}) | {("SH600001",202604070000)})
            with self.assertRaisesRegex(ValueError,"missing/duplicate"):
                M.normalize_private_h5_rows(root,keys)

    def test_source_manifest_sha_and_date_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            keys=sample_keys()
            origins,years,safe,keyfile,_=valid_audit_files(root,keys)
            with temporary_module_dir(root):
                _p,_raw,_k,_kr,_report,selected=M.read_verified_key_manifest(
                    safe,keyfile,origins,years)
                self.assertEqual(selected,keys)
                self.assertEqual(len(selected),83)

    def test_tampered_private_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            origins,years,safe,keyfile,_=valid_audit_files(root,sample_keys())
            keyfile.write_bytes(keyfile.read_bytes()+b" ")
            with temporary_module_dir(root),self.assertRaisesRegex(ValueError,"SHA"):
                M.read_verified_key_manifest(safe,keyfile,origins,years)

    def test_private_manifest_outside_module_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            origins,years,safe,keyfile,_=valid_audit_files(root,sample_keys())
            with temporary_module_dir(root),self.assertRaisesRegex(ValueError,"private"):
                M.read_verified_key_manifest(safe,root/"outside"/"keys.json",
                                             origins,years)

    def test_private_manifest_quarantined_day_rejected_even_with_rehashed_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            origins,years,safe,keyfile,_=valid_audit_files(root,sample_keys())
            doc=json.loads(keyfile.read_bytes())
            doc["candidate_symbol_day_keys"][0]["date"]="2026-07-16"
            raw=json.dumps(doc,sort_keys=True).encode()
            keyfile.write_bytes(raw)
            record=json.loads(safe.read_text())
            record["private_key_manifest_sha256"]=M.sha256(raw)
            safe.write_text(json.dumps(record),encoding="utf-8")
            with temporary_module_dir(root),self.assertRaisesRegex(ValueError,"quarantine|outside"):
                M.read_verified_key_manifest(safe,keyfile,origins,years)

    def test_duplicate_private_keys_rejected_even_with_rehashed_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            origins,years,safe,keyfile,_=valid_audit_files(root,sample_keys())
            doc=json.loads(keyfile.read_bytes())
            doc["candidate_symbol_day_keys"][0]=doc["candidate_symbol_day_keys"][1]
            raw=json.dumps(doc,sort_keys=True).encode()
            keyfile.write_bytes(raw)
            record=json.loads(safe.read_text())
            record["private_key_manifest_sha256"]=M.sha256(raw)
            safe.write_text(json.dumps(record),encoding="utf-8")
            with temporary_module_dir(root),self.assertRaisesRegex(ValueError,"Duplicate|outside"):
                M.read_verified_key_manifest(safe,keyfile,origins,years)

    def test_only_new_private_stage_directory_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"work"/"unified_parquet"/"mixed_day_stages"
            folder.mkdir(parents=True)
            with temporary_module_dir(root):
                accepted=M.stage_dir(folder/"mixed_0123456789ab")
                self.assertEqual(accepted.parent,folder)
                accepted.mkdir()
                with self.assertRaises(ValueError):
                    M.stage_dir(accepted)
                with self.assertRaises(ValueError):
                    M.stage_dir(root/"outside"/"mixed_0123456789ab")

    def test_plan_does_not_stage_private_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/"module"
            market=Path(tmp)/"orig"
            (market/"HikyuuData").mkdir(parents=True)
            (market/"AllCycleAStockData"/"day").mkdir(parents=True)
            source_h5(market,sample_keys())
            origins,years,safe,keyfile,_=valid_audit_files(home,sample_keys())
            folder=home/"work"/"unified_parquet"/"mixed_day_stages"/"mixed_0123456789ab"
            out=home/"reports"/"stage-plan-output.json"
            with temporary_module_dir(home),patch.object(
                    M.KEYS,"verified_existing_plan",return_value=(origins,years)),patch.object(
                    M.KEYS,"state_digest",return_value="source-state"),patch.object(
                    M,"verify_all_live_absence",return_value=1234):
                # Preserve fail-closed behavior when an output aliases evidence.
                with self.assertRaisesRegex(ValueError,"No overwrite"):
                    M.run(market,*(origins[x][0] for x in
                        ("ledger","2016","2026","plan")),
                        safe,keyfile,folder,origins["plan"][0],"plan",False)
                result=M.run(market,*(
                    origins[x][0] for x in ("ledger","2016","2026","plan")),
                    safe,keyfile,folder,out,"plan",False)
                self.assertFalse(result["stage_parquet_created"])
                self.assertFalse(folder.exists())
                self.assertEqual(result["verified_mixed_h5_only_stockday_bars"],83)
                self.assertTrue(out.is_file())
                self.assertNotIn("SH600000",out.read_text())

    def test_explicit_private_stage_writes_exactly_83_and_no_pointer(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/"module"
            market=Path(tmp)/"orig"
            (market/"HikyuuData").mkdir(parents=True)
            (market/"AllCycleAStockData"/"day").mkdir(parents=True)
            keys=sample_keys()
            source_h5(market,keys)
            origins,years,safe,keyfile,_=valid_audit_files(home,keys)
            folder=home/"work"/"unified_parquet"/"mixed_day_stages"/"mixed_0123456789ab"
            out=home/"reports"/"stage-safe.json"
            with temporary_module_dir(home),patch.object(
                    M.KEYS,"verified_existing_plan",return_value=(origins,years)),patch.object(
                    M.KEYS,"state_digest",return_value="source-state"),patch.object(
                    M,"verify_all_live_absence",return_value=1234):
                result=M.run(market,*(
                    origins[x][0] for x in ("ledger","2016","2026","plan")),
                    safe,keyfile,folder,out,"stage",True)
                self.assertTrue(result["stage_parquet_created"])
                self.assertEqual(pq.read_table(folder/"day.parquet").num_rows,83)
                self.assertTrue((folder/"manifest.json").is_file())
                self.assertTrue(out.is_file())
                self.assertFalse(result["private_or_production_active_pointer_modified"])
                self.assertFalse(result["ready_for_automatic_market_merge"])
                self.assertFalse(result["candidate_source_units_certified"])
                self.assertNotIn("SH600000",out.read_text())

    def test_stage_flag_required_and_plan_flag_forbidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            for action,flag in (("stage",False),("plan",True),("illegal",False)):
                with self.subTest(action=action,flag=flag),self.assertRaisesRegex(
                        ValueError,"Explicit stage"):
                    M.run(home,None,None,None,None,None,None,None,None,action,flag)

    def test_stale_purchased_keyset_refused_before_any_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/"module"
            market=Path(tmp)/"orig"
            (market/"HikyuuData").mkdir(parents=True)
            (market/"AllCycleAStockData"/"day").mkdir(parents=True)
            origins,years,safe,keyfile,_=valid_audit_files(home,sample_keys())
            folder=home/"work"/"unified_parquet"/"mixed_day_stages"/"mixed_0123456789ab"
            out=home/"reports"/"fail.json"
            with temporary_module_dir(home),patch.object(
                    M.KEYS,"verified_existing_plan",return_value=(origins,years)),patch.object(
                    M.KEYS,"state_digest",return_value="source-state"),patch.object(
                    M,"verify_all_live_absence",side_effect=ValueError("stale purchased source")):
                with self.assertRaisesRegex(ValueError,"stale purchased"):
                    M.run(market,*(
                        origins[x][0] for x in ("ledger","2016","2026","plan")),
                        safe,keyfile,folder,out,"stage",True)
                self.assertFalse(folder.exists())
                self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
