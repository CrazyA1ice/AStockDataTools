"""Synthetic H5 historical year -> exact RAW private Parquet, no unit guessing."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M=load("native_h5_year_private_parquet_test",
       HERE.parent/"tools"/"stage-pre2011-native-h5-year-to-private-parquet.py")
F=load("native_h5_year_inventory_fixture",
       HERE/"test_inventory_pre2011_h5_parquet_day_readonly.py")


@contextmanager
def ready():
    with F.fresh() as (root,inventory_safe,pq):
        home=inventory_safe.parent.parent
        private=home/"work"/"unified_parquet"/"pre2011_native_h5_raw"
        stage=private/"native_pre2011_2001_012345abcdef"
        out=inventory_safe.parent/"year-native-safe.json"
        with patch.object(M,"MODULE",home), \
             patch.object(M,"REPORTS",inventory_safe.parent), \
             patch.object(M,"PRIVATE",private), \
             patch.object(M.AUDIT,"MODULE",home), \
             patch.object(M.AUDIT,"REPORTS",inventory_safe.parent):
            inventory=M.AUDIT.inventory(root,inventory_safe)
            yield root,inventory_safe,pq,stage,out,inventory


def run(root,inventory,year,out,action="plan",folder=None,allow=False):
    return M.run(root,inventory,year,out,action,folder,allow)


class OriginalH5NativeYearPrivateParquetTests(unittest.TestCase):
    def test_exact_h5_year_2001_plan_just_counts_no_private_prices(self):
        with ready() as (root,inv,pq,stage,out,_):
            raw=pq.read_bytes()
            result=run(root,inv,2001,out)
            self.assertEqual(result["audited_h5_native_stockday_rows"],2)
            self.assertEqual(result["pre2011_h5_all_year_stockday_rows"],5)
            self.assertTrue(result["purchased_no_pre2011_day_keys_proven_by_all_footers"])
            self.assertFalse(result["new_raw_private_year_parquet_created"])
            self.assertFalse(result["private_normalized_purchased_schema"])
            self.assertFalse(stage.exists())
            self.assertEqual(pq.read_bytes(),raw)
            self.assertFalse(result["private_active_pointer_or_production_query_modified"])
            for secret in ("SH600000","SZ000001","HikyuuData","10000","1000.0"):
                self.assertNotIn(secret,out.read_text(encoding="utf-8"))

    def test_private_stage_preserves_exact_h5_uints_and_roundtrip(self):
        import pyarrow.parquet as pqmod
        with ready() as (root,inv,pq,stage,out,_):
            before=pq.read_bytes()
            result=run(root,inv,2001,out,"stage",stage,True)
            self.assertTrue(result["new_raw_private_year_parquet_created"])
            self.assertFalse(result["private_normalized_purchased_schema"])
            self.assertTrue(result["raw_private_stage_is_not_a_usable_purchased_day_overlay"])
            self.assertFalse(result["private_active_pointer_or_production_query_modified"])
            pf=pqmod.ParquetFile(stage/"h5-native-day.parquet")
            rows=pf.read().to_pylist()
            self.assertEqual(len(rows),2)
            self.assertEqual({r["symbol"] for r in rows},{"SH600000","SZ000001"})
            self.assertEqual({r["datetime"] for r in rows},{200101020000})
            self.assertTrue(all(r["openPrice"]==10000 for r in rows))
            self.assertTrue(all(r["transAmount"]==1000 for r in rows))
            self.assertTrue(all(r["transCount"]==100 for r in rows))
            self.assertEqual(tuple(pf.schema_arrow.names),M.FIELDS)
            pf.close()
            manifest=json.loads((stage/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["raw_h5_stockday_rows"],2)
            self.assertEqual(manifest["full_private_parquet_sha256"],
                             M.hash_file(stage/"h5-native-day.parquet"))
            self.assertFalse(manifest["H5_native_quantity_and_amount_units_certified"])
            self.assertEqual(pq.read_bytes(),before)
            self.assertFalse((stage/"active.json").exists())
            self.assertNotIn("SH600000",out.read_text(encoding="utf-8"))
            self.assertNotIn("10000",out.read_text(encoding="utf-8"))

    def test_private_stage_for_1999_also_reuses_exact_year_gate(self):
        import pyarrow.parquet as pqmod
        with ready() as (root,inv,pq,stage,out,_):
            folder=stage.parent/"native_pre2011_1999_012345abcdef"
            result=run(root,inv,1999,out,"stage",folder,True)
            self.assertEqual(result["audited_h5_native_stockday_rows"],1)
            rows=pqmod.read_table(folder/"h5-native-day.parquet").to_pylist()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["datetime"],199911100000)

    def test_zero_h5_year_1990_plans_but_refuses_empty_private_file(self):
        with ready() as (root,inv,pq,stage,out,_):
            result=run(root,inv,1990,out)
            self.assertEqual(result["audited_h5_native_stockday_rows"],0)
            out.unlink()
            folder=stage.parent/"native_pre2011_1990_012345abcdef"
            with self.assertRaisesRegex(ValueError,"zero native H5 rows"):
                run(root,inv,1990,out,"stage",folder,True)
            self.assertFalse(folder.exists())

    def test_stage_needs_explicit_permission_and_exact_private_folder(self):
        with ready() as (root,inv,pq,stage,out,_):
            with self.assertRaisesRegex(ValueError,"authorization"):
                run(root,inv,2001,out,"stage",stage,False)
            with self.assertRaises(ValueError):
                run(root,inv,2001,out,"stage",root/"native_pre2011_2001_012345abcdef",True)
            with self.assertRaises(ValueError):
                run(root,inv,2001,out,"stage",stage.parent/"bad-name",True)
            with self.assertRaises(ValueError):
                run(root,inv,2001,out,"plan",stage,True)
            self.assertFalse(out.exists())

    def test_previous_private_stage_is_never_overwritten(self):
        with ready() as (root,inv,pq,stage,out,_):
            stage.mkdir(parents=True)
            (stage/"important.txt").write_text("protected")
            with self.assertRaisesRegex(ValueError,"unused"):
                run(root,inv,2001,out,"stage",stage,True)
            self.assertEqual((stage/"important.txt").read_text(),"protected")
            self.assertFalse(out.exists())

    def test_old_inventory_report_with_tampered_year_count_refused(self):
        with ready() as (root,inv,pq,stage,out,_):
            obj=json.loads(inv.read_text(encoding="utf-8"))
            obj["original_h5"]["yearly_source_key_inventory"]["2001"][
                "H5_candidate_stockday_rows"]=9
            inv.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                run(root,inv,2001,out)
            self.assertFalse(out.exists())

    def test_source_parquet_change_after_inventory_refuses_before_stage(self):
        with ready() as (root,inv,pq,stage,out,_):
            F.make_pq(root,days=("2011-03-01",))
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                run(root,inv,2001,out)
            self.assertFalse(stage.exists())
            self.assertFalse(out.exists())

    def test_purchased_parquet_2010_rows_in_source_blocks_private_h5(self):
        with ready() as (root,inv,pq,stage,out,_):
            F.make_pq(root,days=("2010-12-30","2011-01-04"))
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                run(root,inv,2001,out,"stage",stage,True)
            self.assertFalse(stage.exists())
            self.assertFalse(out.exists())

    def test_changed_original_h5_during_stage_rejects_result_and_cleans_private_only(self):
        with ready() as (root,inv,pq,stage,out,_):
            old=M.stage_year
            def malicious(*args):
                result=old(*args)
                path=root/"HikyuuData"/"sh_day.h5"
                with path.open("ab") as f:
                    f.write(b"changed")
                return result
            with patch.object(M,"stage_year",side_effect=malicious):
                with self.assertRaisesRegex(ValueError,"Original H5/PQ changed"):
                    run(root,inv,2001,out,"stage",stage,True)
            self.assertFalse(out.exists())
            # The private staging folder is removed because source changed.
            self.assertFalse(stage.exists())

    def test_concurrent_private_job_name_collision_never_deletes_foreign_job(self):
        with ready() as (root,inv,pq,stage,out,_):
            original=M.private_folder
            def concurrent_creator(*args):
                path=original(*args)
                path.mkdir(parents=True,exist_ok=False)
                (path/"protected.txt").write_text("another job",encoding="utf-8")
                return path
            with patch.object(M,"private_folder",side_effect=concurrent_creator):
                with self.assertRaises(FileExistsError):
                    run(root,inv,2001,out,"stage",stage,True)
            self.assertEqual((stage/"protected.txt").read_text(encoding="utf-8"),
                             "another job")
            self.assertFalse(out.exists())

    def test_new_purchased_day_file_arrives_during_stage_refuses_publish(self):
        with ready() as (root,inv,pq,stage,out,_):
            original=M.stage_year
            def source_arrival(*args):
                result=original(*args)
                # This file was NOT present in the validated footer inventory.
                # Its older timestamp could overlap the H5-only year, so
                # the current private staging must fail closed.
                F.make_pq(root,days=("2001-01-02",),
                          name="unexpected-older-day.parquet")
                return result
            with patch.object(M,"stage_year",side_effect=source_arrival):
                with self.assertRaisesRegex(
                        ValueError,"source file set changed"):
                    run(root,inv,2001,out,"stage",stage,True)
            self.assertFalse(stage.exists())
            self.assertFalse(out.exists())

    def test_bad_h5_native_datetime_or_unexpected_count_refuses_stage(self):
        with ready() as (root,inv,pq,stage,out,_):
            old=M.iterate_native_year
            def broken(*args):
                yield {"symbol":"SH600000","datetime":200101029999,
                       "openPrice":10000,"highPrice":11000,
                       "lowPrice":9000,"closePrice":10500,
                       "transCount":100,"transAmount":1000}
            with patch.object(M,"iterate_native_year",side_effect=broken):
                with self.assertRaises(ValueError):
                    run(root,inv,2001,out,"stage",stage,True)
            self.assertFalse(stage.exists())
            self.assertFalse(out.exists())

    def test_safe_must_be_new_json_inside_module_reports(self):
        with ready() as (root,inv,pq,stage,out,_):
            with self.assertRaises(ValueError):
                run(root,inv,2001,root/"unsafe.json")
            out.write_text("protected")
            with self.assertRaises(ValueError):
                run(root,inv,2001,out)
            self.assertEqual(out.read_text(),"protected")

    def test_foreign_inventory_report_refused_and_bounds(self):
        with ready() as (root,inv,pq,stage,out,_):
            for y in (1989,2011,"2001",None):
                with self.subTest(y=y):
                    with self.assertRaises(ValueError):
                        run(root,inv,y,out)
            with self.assertRaises(ValueError):
                run(root,root/"foreign.json",2001,out)
            self.assertFalse(out.exists())

    def test_stage_too_many_historical_rows_fail_closed(self):
        with ready() as (root,inv,pq,stage,out,_):
            with patch.object(M,"MAX_YEAR_ROWS",1):
                with self.assertRaisesRegex(ValueError,"budget"):
                    run(root,inv,2001,out,"stage",stage,True)
            self.assertFalse(stage.exists())
            self.assertFalse(out.exists())

    def test_stage_directory_year_must_match_requested_year(self):
        with ready() as (root,inv,pq,stage,out,_):
            folder=stage.parent/"native_pre2011_1999_012345abcdef"
            with self.assertRaises(ValueError):
                run(root,inv,2001,out,"stage",folder,True)
            self.assertFalse(folder.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
