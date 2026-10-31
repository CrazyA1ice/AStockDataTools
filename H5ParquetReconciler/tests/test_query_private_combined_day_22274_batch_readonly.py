"""Pure fictional tests of one-live-gate private 22,274 stockday batch query."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "batch_private_22274_query_test",
    HERE.parent / "tools" / "query-private-combined-day-22274-batch-readonly.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


def bar(symbol, day):
    stamp=int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)
    return {"symbol":symbol,"period":"day","trading_date":day,
            "source_timestamp_ms":stamp,
            "open":10.0,"high":11.0,"low":9.0,"close":10.0,
            "volume":100.0,"amount":1000.0}


@contextmanager
def fake_batch(*, stale=False, overlap=False, source_changed=False,
               simulated_crlf=False):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reports = root / "reports"
        reports.mkdir()
        orig = reports / "original.json"
        stage = reports / "mixed-stage.json"
        data = root / "mixed.parquet"
        meta = root / "mixed-manifest.json"
        for f in (stage, data, meta):
            f.write_bytes(b"fictional-"+f.name.encode())
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        sha= lambda x:hashlib.sha256(x).hexdigest()
        proof={
            "format": B.PRE.FORMAT,
            "state":"read_only_union_preflight_passed_not_promoted",
            "whole_day_overlay_version_sha256":"a"*64,
            "whole_day_candidate_rows":22191,
            "mixed_stockday_candidate_rows":83,
            "candidate_total_new_stockday_rows":22274,
            "mixed_stage_parquet_sha256":digest(data),
            "mixed_stage_manifest_sha256":digest(meta),
            "mixed_stage_safe_sha256":digest(stage),
            "original_source_stat_sha256":"d"*64,
            "candidate_source_units_certified":False,
        }
        old=json.dumps(proof,sort_keys=True,indent=2,ensure_ascii=False)+"\n"
        if simulated_crlf:
            orig.write_bytes(old.replace("\n", "\r\n").encode("utf-8"))
        else:
            orig.write_text(old,encoding="utf-8")
        entry={
            "ready_for_production_query":False,
            "whole_day_candidate_rows":22191,
            "mixed_stockday_candidate_rows":83,
            "candidate_total_new_stockday_rows":22274,
            "whole_day_overlay_version_sha256":"a"*64,
            "mixed_stage_safe_basename":"mixed-stage.json",
            "mixed_stage_parquet_sha256":digest(data),
            "mixed_stage_manifest_sha256":digest(meta),
            "mixed_stage_safe_sha256":digest(stage),
            "original_source_stat_sha256":"d"*64,
            "original_preflight_safe_basename":"original.json",
            "original_preflight_safe_sha256":digest(orig),
            # Hash the on-disk bytes, not the pre-write LF text. Windows
            # text-mode write_text() can translate LF to CRLF; the real
            # source verifier hashes bytes of its written SAFE report.
            "fresh_recheck_safe_sha256":digest(orig),
        }
        dates=["2026-10-08","2026-10-09","2026-10-12","2026-10-13"]
        stages=[{"day":day,"rows":count} for day,count in zip(dates,[5546,5547,5549,5549])]
        whole={"rows_in_overlay":22191}
        def live_gate(*args,**kwargs):
            target=args[-1]
            changed=dict(proof)
            if stale:
                changed["original_source_stat_sha256"]="f"*64
            live_text=json.dumps(changed,sort_keys=True,indent=2,ensure_ascii=False)+"\n"
            if simulated_crlf:
                target.write_bytes(live_text.replace("\n", "\r\n").encode("utf-8"))
            else:
                target.write_text(live_text,encoding="utf-8")
            if "timing_sink" in kwargs:kwargs["timing_sink"]["mixed_2026_h5_exact_key_scan_seconds"]=2.0
            return changed
        def purchase(_root,symbol,period,start,end,**kw):
            target="2026-10-08" if overlap else "2026-10-06"
            return {"bars":[bar(symbol,target)],"safe_summary":{"source_rows_scanned":3}}
        def whole_decode(stage_item,symbol):
            return [bar(symbol,stage_item["day"])]
        def mixed_decode(rows,symbol,start,end):
            return [bar(symbol,"2026-10-07")] if symbol=="SH600001" else []
        digest_states=["d"*64,"f"*64] if source_changed else ["d"*64,"d"*64]
        with patch.object(B.PRE,"REPORTS",reports),\
             patch.object(B.REG,"LOCK",root/"not-existing-lock"),\
             patch.object(B.REG,"load_version",return_value=entry) as version_load,\
             patch.object(B.PRE,"verify",side_effect=live_gate) as scan,\
             patch.object(B.REG,"read_audit",return_value=(orig,orig.read_bytes(),dict(proof))),\
             patch.object(B.PRE.KEYS,"state_digest",side_effect=digest_states),\
             patch.object(B.WHOLE,"verified_version",return_value=(whole,{},stages)),\
             patch.object(B.PRE.KEYS,"verified_existing_plan",return_value=({},{})),\
             patch.object(B.PRE,"verify_mixed_stage",return_value=(
                 {},{("SH600000",201609300000)}|{(f"SH600{i:03d}",202604080000)
                     for i in range(1,83)},data,meta,digest(data),[],stage
             )),\
             patch.object(B.PURCHASED,"query_bars",side_effect=purchase) as purchase_mock,\
             patch.object(B.WHOLE,"_decode_selected_stage",side_effect=whole_decode),\
             patch.object(B.Q,"selected_mixed_rows",side_effect=mixed_decode):
            yield root, reports, version_load, scan, purchase_mock, entry


def run(root, reports, symbols=("SH600000","SH600001"),**kwargs):
    p=reports/"fresh.json"
    out=reports/"safe.json"
    return B.query_batch(
        root, symbols, "2026-10-06", "2026-10-13","e"*64,
        reports/"live.json",reports/"keys.json",
        reports/"ledger.json",reports/"2016.json",reports/"2026.json",
        reports/"plan.json",p,out,**kwargs)


class PrivateBatchOneGateTests(unittest.TestCase):
    def test_fixture_sha_binds_on_disk_safe_bytes_portably(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            source=reports/"original.json"
            actual=hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(entry["original_preflight_safe_sha256"],actual)
            self.assertEqual(entry["fresh_recheck_safe_sha256"],actual)
            self.assertNotEqual(entry["fresh_recheck_safe_sha256"],
                                hashlib.sha256(source.read_bytes()+b"modified").hexdigest())
            gate.assert_not_called()

    def test_simulated_windows_crlf_safe_passes_identical_sha_gate(self):
        with fake_batch(simulated_crlf=True) as (root,reports,version,gate,purchase,entry):
            self.assertIn(b"\r\n", (reports/"original.json").read_bytes())
            result=run(root,reports,symbols=("SH600000",))
            self.assertEqual(result["safe_summary"]["full_live_recheck_safe_sha256"],
                             entry["fresh_recheck_safe_sha256"])
            self.assertEqual(result["safe_summary"]["query_result_stockday_bars"],5)
            self.assertEqual(gate.call_count,1)

    def test_two_stocks_one_full_market_gate_with_exact_source_totals(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            result=run(root,reports,fast_bounded_h5_scan=True)
            s=result["safe_summary"]
            self.assertEqual(s["requested_stock_count"],2)
            self.assertEqual(s["full_live_market_keyset_audit_count"],1)
            self.assertEqual(s["query_result_stockday_bars"],11)
            self.assertEqual(s["purchased_parquet_bars"],2)
            self.assertEqual(s["whole_h5_only_candidate_bars"],8)
            self.assertEqual(s["mixed_h5_only_candidate_bars"],1)
            self.assertEqual(s["purchased_parquet_rowgroup_rows_scanned_across_stocks"],6)
            self.assertTrue(s["bounded_h5_scan_explicit_opt_in"])
            self.assertEqual(s["full_live_recheck_safe_sha256"],entry["fresh_recheck_safe_sha256"])
            self.assertFalse(s["ready_for_production_query"])
            self.assertEqual(gate.call_count,1)
            self.assertEqual(purchase.call_count,2)
            self.assertGreaterEqual(version.call_count,2)
            self.assertTrue((reports/"safe.json").is_file())
            text=(reports/"safe.json").read_text()
            self.assertNotIn("SH600001",text)
            self.assertNotIn("SH600000",text)
            self.assertNotIn("open",text.lower().replace("source_priority",""))
            self.assertEqual(len(result["bars_by_symbol"]["SH600001"]),6)

    def test_reject_duplicate_stock_symbols_before_any_source_gate(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            with self.assertRaisesRegex(ValueError,"Duplicate"):
                run(root,reports,symbols=("SH600000","SH600000"))
            gate.assert_not_called()
            self.assertFalse((reports/"safe.json").exists())

    def test_lowercase_and_noncanonical_stocks_rejected(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            with self.assertRaises(ValueError):
                run(root,reports,symbols=("sh600000","SH600001"))
            gate.assert_not_called()

    def test_exceed_stock_count_bound_before_source_read(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            with self.assertRaisesRegex(ValueError,"1..10"):
                run(root,reports,symbols=("SH600000",)*11)
            gate.assert_not_called()

    def test_modified_original_source_proof_blocks_all_output(self):
        with fake_batch(stale=True) as (root,reports,version,gate,purchase,entry):
            with self.assertRaisesRegex(ValueError,"proof"):
                run(root,reports)
            self.assertFalse((reports/"safe.json").exists())
            purchase.assert_not_called()

    def test_purchased_and_private_stockday_collision_fails_closed(self):
        with fake_batch(overlap=True) as (root,reports,version,gate,purchase,entry):
            with self.assertRaisesRegex(ValueError,"overlap"):
                run(root,reports)
            self.assertFalse((reports/"safe.json").exists())
            self.assertEqual(gate.call_count,1)

    def test_source_mutation_after_stock_queries_blocks_output(self):
        with fake_batch(source_changed=True) as (root,reports,version,gate,purchase,entry):
            with self.assertRaisesRegex(ValueError,"changed during batch"):
                run(root,reports)
            self.assertFalse((reports/"safe.json").exists())
            gate.assert_called_once()
            self.assertEqual(purchase.call_count, 2)

    def test_reject_existing_output_without_overwrite(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            output=reports/"safe.json"
            output.write_text("original")
            with self.assertRaisesRegex(ValueError,"NEW"):
                run(root,reports)
            self.assertEqual(output.read_text(),"original")
            gate.assert_not_called()

    def test_aggregate_result_limit_fails_entire_batch(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            with self.assertRaisesRegex(ValueError,"Aggregate returned"):
                run(root,reports,max_total_result_bars=10)
            self.assertFalse((reports/"safe.json").exists())

    def test_single_market_gate_is_default_legacy_h5_scanner(self):
        with fake_batch() as (root,reports,version,gate,purchase,entry):
            s=run(root,reports,symbols=("SH600000",))["safe_summary"]
            self.assertEqual(gate.call_count,1)
            self.assertFalse(gate.call_args.kwargs["bounded_h5_scan"])
            self.assertEqual(s["full_live_market_keyset_audit_count"],1)
            self.assertEqual(s["query_result_stockday_bars"],5)


if __name__=="__main__":
    unittest.main(verbosity=2)
