"""Pure fictional PyArrow private parent+delta immutable logical version tests."""
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
    o=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o


R=load("private_joined_logical_registry_under_test",
       HERE.parent/"tools"/"register-private-joined-day-logical-version.py")
F=load("private_joined_logical_registry_fixture",
       HERE/"test_read_private_day_snapshot_with_symbol_delta.py")


@contextmanager
def ready():
    with F.ready() as (base,parent,folder,delta,out,batch,created):
        work=base.work/"unified_parquet"
        versions=work/"joined_day_versions"
        active=work/"active-private-joined-day.json"
        lock=work/".private-joined-day.lock"
        with patch.object(R,"J",F.J), \
             patch.object(R,"READER",F.J.READER), \
             patch.object(R,"MODULE",base.module), \
             patch.object(R,"WORK",work), \
             patch.object(R,"VERSIONS",versions), \
             patch.object(R,"ACTIVE",active), \
             patch.object(R,"LOCK",lock):
            yield base,parent,folder,delta,versions,active,lock,batch


def other_delta(base,folder,delta):
    target=base.work/"unified_parquet"/"snapshot_deltas"/"delta_abcdef1234569999"
    shutil.copytree(folder,target)
    output=base.reports/"private-symbol-delta-second.json"
    content=json.loads(delta.read_text(encoding="utf-8"))
    content["private_delta_relative_path"]=(
        "work/unified_parquet/snapshot_deltas/delta_abcdef1234569999")
    output.write_text(json.dumps(content),encoding="utf-8")
    return output


class PrivateJoinedLogicalVersionTests(unittest.TestCase):
    def test_prepare_immutable_version_references_two_real_arrow_partitions(self):
        with ready() as (base,parent,folder,delta,versions,active,lock,batch):
            watched=[base.pqfile,base.manifest_file,base.safe_file,
                     folder/"day.parquet",folder/"manifest.json",delta]
            sha_before={p:R.READER.sha256_file(p) for p in watched}
            result=R.prepare(parent,delta)
            self.assertEqual(result["joined_rows"],5)
            self.assertEqual(result["joined_stocks"],3)
            self.assertEqual(result["purchased_rows"],2)
            self.assertEqual(result["h5_gap_candidate_rows"],3)
            self.assertIsNone(result["previous_joined_version_sha256"])
            self.assertFalse(result["private_joined_pointer_changed"])
            self.assertFalse(active.exists())
            self.assertEqual({p:R.READER.sha256_file(p) for p in watched},sha_before)
            file=versions/(result["version_sha256"]+".json")
            self.assertTrue(file.is_file())
            loaded=R.load_version(result["version_sha256"])
            self.assertEqual(loaded["parent_private_version_sha256"],parent)
            self.assertEqual(loaded["delta_safe_basename"],delta.name)
            self.assertEqual(loaded["joined_rows"],5)
            self.assertTrue(R.check_version_files(loaded))
            self.assertEqual(R.status()["active_joined_rows"],0)
            for forbidden in ("150000.25","SH600519","SH600000",
                              "AllCycleAStockData","HikyuuData"):
                self.assertNotIn(forbidden,file.read_text(encoding="utf-8"))
            self.assertFalse((base.work/"unified_parquet"/
                              "active-private-snapshot.json").exists())

    def test_prepare_is_repeatable_without_pointer_change(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            a=R.prepare(parent,delta)
            c=R.prepare(parent,delta)
            self.assertEqual(a,c)
            self.assertEqual(len(list(versions.glob("*.json"))),1)
            self.assertFalse(active.exists())

    def test_tampered_delta_sha_rejected_before_version_registration(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            with (folder/"day.parquet").open("ab") as f:
                f.write(b"changed")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                R.prepare(parent,delta)
            self.assertFalse(versions.exists())
            self.assertFalse(active.exists())

    def test_tampered_parent_sha_rejected_before_version_registration(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            with b.pqfile.open("ab") as f:
                f.write(b"changed")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                R.prepare(parent,delta)
            self.assertFalse(versions.exists())

    def test_parent_mismatch_and_bad_delta_identity_refused(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            with self.assertRaises(ValueError):
                R.prepare("f"*64,delta)
            d=json.loads(delta.read_text())
            d["parent_private_snapshot_version_sha256"]="b"*64
            delta.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,"verified private additive"):
                R.prepare(parent,delta)
            self.assertFalse(versions.exists())

    def test_rehashed_forged_delta_stock_overlap_is_rejected(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            def change(data):
                data["new_symbols"]=["SH600000"]
                data["per_symbol_counts"]["SH600000"]=data["per_symbol_counts"].pop("SH600519")
            F.resign_delta(folder,delta,metadata=change)
            with self.assertRaisesRegex(ValueError,"overlaps parent"):
                R.prepare(parent,delta)
            self.assertFalse(versions.exists())

    def test_loaded_version_file_tamper_refused_even_if_json_valid(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            ver=R.prepare(parent,delta)["version_sha256"]
            p=versions/(ver+".json")
            item=json.loads(p.read_text())
            item["joined_rows"]+=1
            p.write_text(json.dumps(item),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"content SHA differs"):
                R.load_version(ver)
            with self.assertRaises(ValueError):
                R.prepare(parent,delta)

    def test_lock_conflict_refuses_prepare_and_leaves_existing_lock(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            lock.parent.mkdir(parents=True,exist_ok=True)
            lock.write_text("held")
            with self.assertRaisesRegex(ValueError,"lock exists"):
                R.prepare(parent,delta)
            self.assertEqual(lock.read_text(),"held")
            self.assertFalse(versions.exists())

    def test_explicit_private_activate_rollback_without_production_effect(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            ver=R.prepare(parent,delta)["version_sha256"]
            self.assertIsNone(R.read_pointer())
            R.activate(ver)
            self.assertEqual(R.read_pointer(),ver)
            self.assertEqual(R.status()["active_joined_rows"],5)
            self.assertEqual(R.status()["active_joined_stocks"],3)
            self.assertFalse((b.work/"unified_parquet"/
                              "active-private-snapshot.json").exists())
            self.assertFalse((b.work/"unified_parquet"/
                              "active-day-overlay.json").exists())
            rolled=R.rollback()
            self.assertIsNone(rolled["restored_version_sha256"])
            self.assertIsNone(R.read_pointer())
            self.assertTrue((versions/(ver+".json")).exists())
            with self.assertRaisesRegex(ValueError,"No active"):
                R.rollback()

    def test_two_generation_pointer_chaining_and_rollback(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            first=R.prepare(parent,delta)["version_sha256"]
            R.activate(first)
            second_delta=other_delta(b,folder,delta)
            second=R.prepare(parent,second_delta)
            self.assertEqual(second["previous_joined_version_sha256"],first)
            self.assertNotEqual(second["version_sha256"],first)
            R.activate(second["version_sha256"])
            self.assertEqual(R.read_pointer(),second["version_sha256"])
            R.rollback()
            self.assertEqual(R.read_pointer(),first)
            R.rollback()
            self.assertIsNone(R.read_pointer())
            self.assertEqual(len(list(versions.glob("*.json"))),2)

    def test_stale_prepared_version_cannot_activate_after_pointer_advances(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            first=R.prepare(parent,delta)["version_sha256"]
            new=R.prepare(parent,other_delta(b,folder,delta))["version_sha256"]
            R.activate(first)
            with self.assertRaisesRegex(ValueError,"advanced"):
                R.activate(new)
            self.assertEqual(R.read_pointer(),first)

    def test_tampered_predecessor_blocks_rollback(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            first=R.prepare(parent,delta)["version_sha256"]
            R.activate(first)
            new=R.prepare(parent,other_delta(b,folder,delta))["version_sha256"]
            R.activate(new)
            first_path=versions/(first+".json")
            data=json.loads(first_path.read_text())
            data["joined_rows"]+=1
            first_path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,"content SHA differs"):
                R.rollback()
            self.assertEqual(R.read_pointer(),new)

    def test_source_modified_after_registration_blocks_activate(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            ver=R.prepare(parent,delta)["version_sha256"]
            delta.write_text(delta.read_text()+"\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                R.activate(ver)
            self.assertFalse(active.exists())

    def test_forged_pointer_and_symlink_simulation_rejected_cross_platform(self):
        with ready() as (b,parent,folder,delta,versions,active,lock,batch):
            active.write_text(json.dumps({"format":R.POINTER_FORMAT,
                                          "version_sha256":"not-sha"}))
            with self.assertRaises(ValueError):
                R.status()
            active.unlink()
            # No OS symlink creation privilege needed on Windows.
            with patch.object(Path,"is_symlink",autospec=True,
                              side_effect=lambda path: path==active):
                with self.assertRaisesRegex(ValueError,"Symlinked"):
                    R.read_pointer()


if __name__=="__main__":
    unittest.main(verbosity=2)
