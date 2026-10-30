"""Synthetic-only additive stock-universe Parquet delta regression."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    o=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o

A=load("private_symbol_delta_under_test",
       HERE.parent/"tools"/"append-private-unified-day-symbol-delta.py")
F=load("private_symbol_delta_base_fixture",
       HERE/"test_version_private_unified_day_parquet_snapshot.py")

OVERLAY="a"*64


def bar(sym,date,source,price):
    from datetime import timezone,timedelta
    stamp=int(datetime.fromisoformat(date).replace(
        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    return {
        "symbol":sym,"period":"day","trading_date":date,
        "source_timestamp_ms":stamp,"value_source":source,
        "open":float(price),"high":float(price+.2),
        "low":float(price-.2),"close":float(price+.1),
        "amount":150000.25,"volume":1300.0,
    }


def fake_batch(symbols=("SH600519",)):
    by={}
    per={}
    for sym in symbols:
        rows=[
            bar(sym,"2026-09-30","purchased_parquet",10.1),
            bar(sym,"2026-10-08","private_hikyuu_h5_gap_candidate",10.2)]
        by[sym]=rows
        per[sym]={"purchased_bars":1,"private_bars":1,"returned_bars":2}
    return {
        "bars_by_symbol":by,
        "safe_summary":{
            "format":A.MAT.BATCH.FORMAT,
            "private_version_sha256":OVERLAY,
            "from_date":"2026-09-30",
            "to_date":"2026-10-08",
            "symbols":list(symbols),
            "symbol_count":len(symbols),
            "per_symbol_counts":per,
            "matching_bar_count":2*len(symbols),
            "purchased_parquet_bars_returned":len(symbols),
            "private_overlay_bars_returned":len(symbols),
            "purchased_parquet_priority":True,
            "private_overlay_stages_sha_and_keys_verified":True,
            "selected_private_stages_final_snapshot_reverified":True,
            "no_source_market_writes":True,
            "no_production_query_switch":True,
            "no_raw_ohlcva_in_safe_summary":True,
            "no_active_pointer_read_or_change":True,
            "private_version_selection_mode":"explicit_immutable_version_sha256",
        },
    }


@contextmanager
def fixture():
    # Reuse REAL PyArrow-backed synthetic base and the actual registered
    # SHA versioner, never modify a user's market source or true reports.
    with F.fresh() as (base,versions,active,lock):
        deltas=base.work/"unified_parquet"/"snapshot_deltas"
        folder=deltas/"delta_012345abcdef"
        output=base.reports/"new-symbol-delta-safe.json"
        with patch.object(A,"VERSION",F.V), \
             patch.object(A,"READER",F.V.READER), \
             patch.object(A,"MODULE",base.module), \
             patch.object(A,"WORK",base.work/"unified_parquet"), \
             patch.object(A,"DELTAS",deltas), \
             patch.object(A.MAT.BATCH,"query_private_day_overlay_batch",
                          return_value=fake_batch()) as batch:
            parent=F.V.prepare(base.safe_file)["version_sha256"]
            yield base,parent,folder,output,batch


def append(base,parent,folder,out,symbols=("SH600519",),overlay=OVERLAY):
    return A.append(base.module/"test-market-synthetic",parent,overlay,
                    list(symbols),folder,out)


class AdditivePrivateSymbolDeltaTests(unittest.TestCase):
    def test_new_stock_partition_real_arrow_roundtrip_and_parent_unchanged(self):
        import pyarrow.parquet as pq
        with fixture() as (f,parent,folder,out,batch):
            before={p:A.READER.sha256_file(p) for p in (
                f.pqfile,f.manifest_file,f.safe_file)}
            result=append(f,parent,folder,out)
            self.assertEqual(result["added_rows"],2)
            self.assertEqual(result["purchased_rows"],1)
            self.assertEqual(result["h5_gap_candidate_rows"],1)
            self.assertEqual(result["parent_private_snapshot_version_sha256"],parent)
            self.assertFalse(result["existing_snapshot_rows_rewritten"])
            self.assertFalse(result["private_active_pointer_changed"])
            self.assertFalse(result["ready_for_full_market_mirror"])
            self.assertEqual(len(pq.read_table(folder/"day.parquet").to_pylist()),2)
            meta=json.loads((folder/"manifest.json").read_text())
            self.assertEqual(meta["new_symbols"],["SH600519"])
            self.assertEqual(meta["parent_private_snapshot_version_sha256"],parent)
            self.assertEqual(meta["delta_parquet_sha256"],
                             A.READER.sha256_file(folder/"day.parquet"))
            self.assertEqual(result["delta_manifest_sha256"],
                             A.READER.sha256_file(folder/"manifest.json"))
            self.assertEqual(before,{p:A.READER.sha256_file(p) for p in before})
            self.assertFalse((f.work/"unified_parquet"/"active-private-snapshot.json").exists())
            batch.assert_called_once()
            self.assertFalse(batch.call_args.kwargs["use_private_active"])
            for forbidden in ("150000.25","SH600519","600519",
                              "HikyuuData","test-market-synthetic"):
                self.assertNotIn(forbidden,out.read_text())

    def test_existing_parent_stock_cannot_be_appended(self):
        with fixture() as (f,parent,folder,out,batch):
            with self.assertRaisesRegex(ValueError,"overlap"):
                append(f,parent,folder,out,symbols=["SH600000"])
            batch.assert_not_called()
            self.assertFalse(folder.exists())

    def test_second_copy_of_same_symbol_cannot_be_appended(self):
        with fixture() as (f,parent,folder,out,batch):
            with self.assertRaisesRegex(ValueError,"distinct"):
                append(f,parent,folder,out,symbols=["SH600519","SH600519"])
            batch.assert_not_called()

    def test_source_overlay_version_must_match_parent_snapshot(self):
        with fixture() as (f,parent,folder,out,batch):
            with self.assertRaisesRegex(ValueError,"exactly base"):
                append(f,parent,folder,out,overlay="b"*64)
            batch.assert_not_called()

    def test_wrong_or_noncanonical_symbol_refused(self):
        with fixture() as (f,parent,folder,out,batch):
            for sym in ("sh600519","BAD","SH60051",None):
                with self.subTest(sym=sym):
                    with self.assertRaises(ValueError):
                        append(f,parent,folder,out,symbols=[sym])
            batch.assert_not_called()

    def test_no_new_bars_does_not_create_empty_delta(self):
        with fixture() as (f,parent,folder,out,batch):
            result=fake_batch()
            result["bars_by_symbol"]={"SH600519":[]}
            result["safe_summary"]["per_symbol_counts"]={
                "SH600519":{"purchased_bars":0,"private_bars":0,"returned_bars":0}}
            for key in ("matching_bar_count","purchased_parquet_bars_returned",
                        "private_overlay_bars_returned"):
                result["safe_summary"][key]=0
            batch.return_value=result
            with self.assertRaisesRegex(ValueError,"Bounded row accounting"):
                append(f,parent,folder,out)
            self.assertFalse(folder.exists())
            self.assertFalse(out.exists())

    def test_source_field_corruption_rejected_before_private_write(self):
        with fixture() as (f,parent,folder,out,batch):
            data=fake_batch()
            data["bars_by_symbol"]["SH600519"][0]["amount"]=float("nan")
            batch.return_value=data
            with self.assertRaisesRegex(ValueError,"nonfinite"):
                append(f,parent,folder,out)
            self.assertFalse(folder.exists())

    def test_duplicate_stockday_within_delta_rejected(self):
        with fixture() as (f,parent,folder,out,batch):
            data=fake_batch()
            data["bars_by_symbol"]["SH600519"][1]["trading_date"]="2026-09-30"
            batch.return_value=data
            with self.assertRaisesRegex(ValueError,"duplicate stock-day"):
                append(f,parent,folder,out)
            self.assertFalse(out.exists())

    def test_modified_parent_parquet_blocks_before_source_scan(self):
        with fixture() as (f,parent,folder,out,batch):
            with f.pqfile.open("ab") as stream:
                stream.write(b"tampered-parent")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                append(f,parent,folder,out)
            batch.assert_not_called()

    def test_parent_proof_mutates_during_new_source_query(self):
        with fixture() as (f,parent,folder,out,batch):
            def mutate(*args,**kwargs):
                with f.safe_file.open("ab") as stream:
                    stream.write(b"\n")
                return fake_batch()
            batch.side_effect=mutate
            with self.assertRaisesRegex(ValueError,"proof changed"):
                append(f,parent,folder,out)
            self.assertFalse(folder.exists())
            self.assertFalse(out.exists())

    def test_existing_delta_folder_or_safe_report_is_not_overwritten(self):
        with fixture() as (f,parent,folder,out,batch):
            folder.parent.mkdir(parents=True,exist_ok=True)
            folder.mkdir()
            with self.assertRaisesRegex(ValueError,"NEW"):
                append(f,parent,folder,out)
            folder.rmdir()
            out.write_text("protected")
            with self.assertRaises(ValueError):
                append(f,parent,folder,out)
            self.assertEqual(out.read_text(),"protected")
            batch.assert_not_called()

    def test_private_output_path_traversal_refused(self):
        with fixture() as (f,parent,folder,out,batch):
            for path in (f.module/"delta_012345abcdef",
                         f.work/"wrong"/"delta_012345abcdef",
                         folder/"sub",
                         f.work/"unified_parquet"/"snapshot_deltas"/"delta_bad"):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        A.private_output(path,out)
            batch.assert_not_called()


if __name__=="__main__":
    unittest.main(verbosity=2)
