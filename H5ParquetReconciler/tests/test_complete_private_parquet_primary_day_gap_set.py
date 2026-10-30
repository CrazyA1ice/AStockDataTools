"""Synthetic entire A-share day-gap private Parquet completion and version prep."""
import importlib.util
import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C=load("allmarket_day_gap_completion_under_test",
       HERE.parent/"tools"/"complete-private-parquet-primary-day-gap-set.py")
F=load("allmarket_day_gap_existing_synthetic_integration",
       HERE/"test_build_parquet_primary_day_overlay.py")


@contextmanager
def ready():
    with F.ready() as (root,module,report,gate,purchased,stage,_):
        reports=module/"reports"
        safe=reports/"complete-full-day-safe.json"
        with patch.object(C,"OVERLAY",F.M), \
             patch.object(C,"STAGE",F.M.stage_tool), \
             patch.object(C,"MODULE",module), \
             patch.object(C,"REPORTS",reports):
            yield root,module,gate,report,purchased,stage,safe


def run(root,gate,report,safe,action="plan",allow=False):
    return C.run(root,gate,report,safe,action,allow)


class FullDayGapCompletionTests(unittest.TestCase):
    def test_plan_reuses_validated_existing_market_stages_and_does_not_activate(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            before=purchased.read_bytes()
            result=run(root,gate,report,safe)
            self.assertEqual(result["audited_complete_h5_only_days"],1)
            self.assertEqual(result["audited_complete_h5_only_day_rows"],1)
            self.assertEqual(result["existing_private_staged_days_before_action"],1)
            self.assertFalse(result["missing_private_stage_dates"])
            self.assertIsNone(result["prepared_immutable_overlay_sha256"])
            self.assertTrue(result["purchased_original_files_left_read_only"])
            self.assertFalse(result["private_active_pointer_changed"])
            self.assertEqual(purchased.read_bytes(),before)
            self.assertFalse(F.M.ACTIVE.exists())
            for secret in ("SH600000","SZ000001","XSHG","HikyuuData"):
                self.assertNotIn(secret,safe.read_text(encoding="utf-8"))

    def test_plan_says_missing_after_private_stage_removed_without_recreating(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            shutil.rmtree(stage)
            result=run(root,gate,report,safe)
            self.assertEqual(result["missing_private_stage_dates"],["2026-10-08"])
            self.assertFalse(stage.exists())
            self.assertIsNone(result["prepared_immutable_overlay_sha256"])

    def test_complete_existing_entire_day_stage_prepares_immutable_version(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            original=purchased.read_bytes()
            result=run(root,gate,report,safe,"complete",True)
            self.assertEqual(result["audited_complete_h5_only_day_rows"],1)
            self.assertEqual(result["staged_new_private_days_this_action"],[])
            sha=result["prepared_immutable_overlay_sha256"]
            self.assertEqual(F.M.load_version(sha)["rows_in_overlay"],1)
            self.assertTrue(safe.exists())
            self.assertFalse(F.M.ACTIVE.exists())
            self.assertEqual(purchased.read_bytes(),original)

    def test_complete_missing_date_stages_real_synthetic_parquet_and_prepares(self):
        import pyarrow.parquet as pq
        with ready() as (root,module,gate,report,purchased,stage,safe):
            shutil.rmtree(stage)
            original=purchased.read_bytes()
            result=run(root,gate,report,safe,"complete",True)
            self.assertEqual(result["staged_new_private_days_this_action"],
                             ["2026-10-08"])
            newer=stage.parent/"complete-day-20261008-v1"
            self.assertEqual(pq.read_table(newer/"day.parquet").num_rows,1)
            self.assertTrue((newer/"manifest.json").is_file())
            self.assertEqual(F.M.load_version(
                result["prepared_immutable_overlay_sha256"])["rows_in_overlay"],1)
            self.assertFalse(F.M.ACTIVE.exists())
            self.assertEqual(purchased.read_bytes(),original)

    def test_complete_requires_explicit_private_parquet_approval(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            with self.assertRaisesRegex(ValueError,"authorization"):
                run(root,gate,report,safe,"complete",False)
            self.assertFalse(safe.exists())
            self.assertFalse(F.M.ACTIVE.exists())

    def test_plan_rejects_accidental_private_materialization_flag(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            with self.assertRaisesRegex(ValueError,"authorization"):
                run(root,gate,report,safe,"plan",True)
            self.assertFalse(safe.exists())

    def test_tampered_existing_day_stage_hash_fails_closed(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            with (stage/"day.parquet").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError,"bytes changed"):
                run(root,gate,report,safe)
            self.assertFalse(safe.exists())

    def test_gate_changed_after_staging_fails_source_chain(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            obj=json.loads(gate.read_text(encoding="utf-8"))
            obj["source_report_sha256"]="0"*64
            gate.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaises(ValueError):
                run(root,gate,report,safe)
            self.assertFalse(safe.exists())

    def test_duplicate_same_day_stages_refuse_ambiguous_private_sources(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            second=stage.parent/"copy-duplicate-day"
            shutil.copytree(stage,second)
            with self.assertRaisesRegex(ValueError,"Ambiguous multiple"):
                run(root,gate,report,safe)
            self.assertFalse(safe.exists())

    def test_mixed_day_gap_count_never_accepted_as_complete_date(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            obj=json.loads(gate.read_text(encoding="utf-8"))
            obj["h5_only_rows_on_mixed_dates_need_symbol_day_manifest"]=1
            gate.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"zero mixed"):
                run(root,gate,report,safe)
            self.assertFalse(safe.exists())

    def test_original_source_change_during_prepare_aborts_safe(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            old=F.M.prepare
            def malicious(*args,**kwargs):
                prepared=old(*args,**kwargs)
                with purchased.open("ab") as stream:
                    stream.write(b"changed")
                return prepared
            with patch.object(F.M,"prepare",side_effect=malicious):
                with self.assertRaisesRegex(ValueError,"source file stats changed"):
                    run(root,gate,report,safe,"complete",True)
            self.assertFalse(safe.exists())

    def test_output_outside_reports_or_preexisting_rejected(self):
        with ready() as (root,module,gate,report,purchased,stage,safe):
            with self.assertRaisesRegex(ValueError,"module reports"):
                run(root,gate,report,module/"outside.json")
            safe.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"module reports"):
                run(root,gate,report,safe)
            self.assertEqual(safe.read_text(encoding="utf-8"),"protected")


if __name__=="__main__":
    unittest.main(verbosity=2)
