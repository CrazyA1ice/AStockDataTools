"""Synthetic multi-year native H5 RAW private Parquet stage/reuse/fail-closed."""
import importlib.util
import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


B=load("historical_h5_annual_raw_batch_under_test",
       HERE.parent/"tools"/"batch-pre2011-native-h5-years-to-private-parquet.py")
F=load("historical_h5_single_year_synthetic_fixture",
       HERE/"test_stage_pre2011_native_h5_year_to_private_parquet.py")
JOB="012345abcdef"


@contextmanager
def fresh():
    # F.ready builds an actual synthetic source H5, purchased Parquet,
    # and a signed 1990-2010 historical source inventory in module reports.
    with F.ready() as (root,inventory,purchased,stage,out,original):
        home=inventory.parent.parent
        safe=inventory.parent/"multi-annual-batch-safe.json"
        with patch.object(B,"MODULE",home),patch.object(B,"SINGLE",F.M):
            yield root,inventory,purchased,stage,safe,original


def run(root,inv,safe,years,action="plan",job=None,allow=False):
    return B.run(root,inv,years,safe,action,job,allow)


class BoundedMultiYearOriginalH5RawStageTests(unittest.TestCase):
    def test_plan_three_years_one_full_inventory_and_no_market_write(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            data=purchased.read_bytes()
            with patch.object(F.M,"requalify",wraps=F.M.requalify) as qualified:
                result=run(root,inv,safe,[1991,1999,2001])
            qualified.assert_called_once()
            self.assertEqual(result["selected_years"],[1991,1999,2001])
            self.assertEqual(result["selected_year_source_native_rows"],4)
            self.assertFalse(result["existing_verified_years_before_action"])
            self.assertEqual(len(result["remaining_nonempty_missing_years"]),3)
            self.assertEqual(purchased.read_bytes(),data)
            self.assertFalse(stage.exists())
            self.assertFalse(result["purchased_compatible_normalized_day_parquet_created"])
            self.assertFalse(result["native_h5_mirror_created"])
            for secret in ("SH600000","SZ000001","HikyuuData",
                           "1000.0","10000","600000.XSHG"):
                self.assertNotIn(secret,safe.read_text(encoding="utf-8"))

    def test_explicit_two_year_batch_creates_real_raw_parquets_and_reuses_them(self):
        import pyarrow.parquet as pq
        with fresh() as (root,inv,purchased,stage,safe,_):
            original=purchased.read_bytes()
            with patch.object(F.M,"requalify",wraps=F.M.requalify) as qualified:
                result=run(root,inv,safe,[1991,2001],"stage",JOB,True)
            qualified.assert_called_once()
            self.assertEqual(result["newly_staged_years_this_action"],[1991,2001])
            self.assertEqual(result["selected_year_source_native_rows"],3)
            self.assertFalse(result["remaining_nonempty_missing_years"])
            self.assertEqual(purchased.read_bytes(),original)
            f=stage.parent/"native_pre2011_2001_"+JOB
            g=stage.parent/"native_pre2011_1991_"+JOB
            self.assertEqual(pq.read_metadata(f/"h5-native-day.parquet").num_rows,2)
            self.assertEqual(pq.read_metadata(g/"h5-native-day.parquet").num_rows,1)
            self.assertFalse((stage.parent/"active-day-overlay.json").exists())
            safe.unlink()
            with patch.object(F.M,"stage_year",side_effect=AssertionError(
                    "Unexpected restaging")):
                resumed=run(root,inv,safe,[1991,2001],"stage","123456789abc",True)
            self.assertEqual(resumed["newly_staged_years_this_action"],[])
            self.assertEqual(resumed["existing_verified_years_before_action"],
                             [1991,2001])

    def test_existing_1990_single_stage_can_be_reused_by_year_batch(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            folder=stage.parent/"native_pre2011_1999_012345abcdef"
            old_safe=inv.parent/"already-verified-1999.json"
            F.M.run(root,inv,1999,old_safe,"stage",folder,True)
            result=run(root,inv,safe,[1999,2001])
            self.assertEqual(result["existing_verified_years_before_action"],[1999])
            self.assertEqual(result["remaining_nonempty_missing_years"],[2001])
            self.assertEqual(result["yearly_status"][0]["audited_h5_native_rows"],1)
            self.assertTrue(result["yearly_status"][0][
                "private_raw_parquet_present_and_verified"])

    def test_resume_after_one_completed_private_year_but_no_safe(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            old=B.stage_missing
            completed=[]
            def fail_second(*args):
                if completed:
                    raise ValueError("synthetic failure before second private date")
                result=old(*args)
                completed.append(result)
                return result
            with patch.object(B,"stage_missing",side_effect=fail_second):
                with self.assertRaisesRegex(ValueError,"synthetic failure"):
                    run(root,inv,safe,[1991,2001],"stage",JOB,True)
            self.assertFalse(safe.exists())
            self.assertTrue((stage.parent/"native_pre2011_1991_"+JOB).exists())
            result=run(root,inv,safe,[1991,2001],"stage","fedcba987654",True)
            self.assertEqual(result["newly_staged_years_this_action"],[2001])
            self.assertEqual(result["existing_verified_years_before_action"],[1991])

    def test_zero_row_year_is_explicit_and_not_written(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            result=run(root,inv,safe,[1990,2001],"stage",JOB,True)
            self.assertEqual(result["selected_year_source_native_rows"],2)
            self.assertEqual(result["newly_staged_years_this_action"],[2001])
            self.assertTrue(result["yearly_status"][0][
                "has_no_original_h5_stockday_rows"])
            self.assertFalse((stage.parent/"native_pre2011_1990_"+JOB).exists())

    def test_resuming_private_stage_rechecks_original_h5_raw_values(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            run(root,inv,safe,[2001],"stage",JOB,True)
            safe.unlink()
            # Existing Parquet matches its manifest, but the *live* H5
            # row stream digest disagrees. Stat-only checks are insufficient.
            with patch.object(B,"source_year_native_digest",
                              return_value=("0"*64,{"SH":1,"SZ":1})):
                with self.assertRaisesRegex(
                        ValueError,"differs from live original H5 values"):
                    run(root,inv,safe,[2001])
            self.assertFalse(safe.exists())

    def test_tampered_existing_private_parquet_or_manifest_refused(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            run(root,inv,safe,[2001],"stage",JOB,True)
            safe.unlink()
            file=stage.parent/("native_pre2011_2001_"+JOB)/"h5-native-day.parquet"
            with file.open("ab") as stream:
                stream.write(b"modified")
            with self.assertRaisesRegex(ValueError,"digest mismatches"):
                run(root,inv,safe,[2001])
            self.assertFalse(safe.exists())

    def test_two_valid_stages_for_same_year_are_ambiguous(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            run(root,inv,safe,[2001],"stage",JOB,True)
            safe.unlink()
            first=stage.parent/("native_pre2011_2001_"+JOB)
            other=stage.parent/"native_pre2011_2001_fedcba987654"
            shutil.copytree(first,other)
            with self.assertRaisesRegex(ValueError,"Multiple verified"):
                run(root,inv,safe,[2001])
            self.assertFalse(safe.exists())

    def test_new_purchased_year_file_during_write_cleans_only_current_job(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            original=F.M.stage_year
            def after_raw_write(*args):
                result=original(*args)
                F.F.make_pq(root,days=("2001-01-02",),
                            name="newly-arrived.parquet")
                return result
            with patch.object(F.M,"stage_year",side_effect=after_raw_write):
                with self.assertRaisesRegex(ValueError,"source file set changed"):
                    run(root,inv,safe,[2001],"stage",JOB,True)
            self.assertFalse(safe.exists())
            self.assertFalse((stage.parent/"native_pre2011_2001_"+JOB).exists())

    def test_private_job_name_collision_does_not_delete_foreign_content(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            file=stage.parent/"native_pre2011_2001_"+JOB
            original=B.stage_missing
            def collision(*args):
                file.mkdir(parents=True)
                (file/"protected.txt").write_text("foreign",encoding="utf-8")
                return original(*args)
            with patch.object(B,"stage_missing",side_effect=collision):
                with self.assertRaises(ValueError):
                    run(root,inv,safe,[2001],"stage",JOB,True)
            self.assertEqual((file/"protected.txt").read_text(encoding="utf-8"),
                             "foreign")
            self.assertFalse(safe.exists())

    def test_stage_requires_explicit_authorization_and_safe_job_id(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            for year_list,action,job,allow in (
                ([2001],"stage",JOB,False),
                ([2001],"stage",None,True),
                ([2001],"stage","nothex",True),
                ([2001],"plan",JOB,False),
                ([2001],"plan",None,True),
                ([], "plan",None,False),
                ([1991,1999,2001,2002],"plan",None,False),
                ([2001,2001],"plan",None,False),
                ([1989],"plan",None,False),
                ([2011],"plan",None,False),
            ):
                with self.subTest(year_list=year_list,action=action):
                    with self.assertRaises(ValueError):
                        run(root,inv,safe,year_list,action,job,allow)
            self.assertFalse(safe.exists())

    def test_stale_source_inventory_report_refuses_stage(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            obj=json.loads(inv.read_text(encoding="utf-8"))
            obj["original_h5"]["pre2011_candidate_h5_stockday_rows"]=9999
            inv.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                run(root,inv,safe,[1991,2001],"stage",JOB,True)
            self.assertFalse(safe.exists())
            self.assertFalse(stage.exists())

    def test_budget_denies_large_selected_batch(self):
        with fresh() as (root,inv,purchased,stage,safe,_):
            with patch.object(B,"MAX_BATCH_ROWS",1):
                with self.assertRaisesRegex(ValueError,"budget"):
                    run(root,inv,safe,[1991,2001],"stage",JOB,True)
            self.assertFalse(safe.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
