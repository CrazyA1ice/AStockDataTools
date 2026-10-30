"""Synthetic snapshot version/pointer tests; no real market source access."""
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
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V=load("private_snapshot_version_test",
       HERE.parent/"tools"/"version-private-unified-day-parquet-snapshot.py")
F=load("private_snapshot_reader_test_fixture",
       HERE/"test_read_private_unified_day_parquet_snapshot.py")


@contextmanager
def fresh():
    fixture=F.VerifiedPrivateSnapshotTests(
        "test_real_arrow_synthetic_parquet_verified_end_to_end_without_original_market")
    fixture.setUp()
    work=fixture.work/"unified_parquet"
    versions=work/"snapshot_versions"
    active=work/"active-private-snapshot.json"
    lock=work/".private-snapshot-version.lock"
    try:
        with patch.object(V,"MODULE",fixture.module), \
             patch.object(V,"WORK",work), \
             patch.object(V,"VERSIONS",versions), \
             patch.object(V,"ACTIVE",active), \
             patch.object(V,"LOCK",lock), \
             patch.object(V.READER,"MODULE",fixture.module), \
             patch.object(V.READER,"WORK",fixture.work), \
             patch.object(V.READER,"ROOT",fixture.snapshots), \
             patch.object(V.READER,"REPORTS",fixture.reports):
            yield fixture,versions,active,lock
    finally:
        fixture.doCleanups()


def another(fixture):
    folder=fixture.snapshots/"snapshot_012345abcdef1111"
    shutil.copytree(fixture.folder,folder)
    safe=fixture.reports/"private-snapshot-second.json"
    other={**fixture.safe,
           "snapshot_relative_path":
               "work/unified_parquet/snapshots/snapshot_012345abcdef1111"}
    safe.write_text(json.dumps(other),encoding="utf-8")
    return safe


class PrivateVersionRegistrationTests(unittest.TestCase):
    def test_real_arrow_snapshot_full_verification_before_register(self):
        with fresh() as (f,versions,active,lock):
            version=V.prepare(f.safe_file)
            self.assertEqual(version["rows"],3)
            self.assertEqual(version["previous_version_sha256"],None)
            self.assertFalse(version["private_snapshot_pointer_changed"])
            self.assertFalse(active.exists())
            self.assertFalse(lock.exists())
            p=versions/(version["version_sha256"]+".json")
            self.assertTrue(p.is_file())
            info=V.load_version(version["version_sha256"])
            self.assertEqual(info["purchased_rows"],1)
            self.assertEqual(info["h5_gap_candidate_rows"],2)
            self.assertEqual(info["snapshot_safe_basename"],f.safe_file.name)
            for forbidden in ("150000.25","320000.75",
                              '"amount": 150000','"open": 10.1',
                              "AllCycleAStockData","HikyuuData"):
                self.assertNotIn(forbidden,p.read_text(encoding="utf-8"))
            self.assertEqual(V.status()["verified_active_snapshot_rows"],0)

    def test_prepare_same_snapshot_is_idempotent_without_pointer(self):
        with fresh() as (f,versions,active,lock):
            first=V.prepare(f.safe_file)
            second=V.prepare(f.safe_file)
            self.assertEqual(first,second)
            self.assertEqual(len(list(versions.glob("*.json"))),1)
            self.assertFalse(active.exists())

    def test_incomplete_or_tampered_parquet_refused_before_version_file(self):
        with fresh() as (f,versions,active,lock):
            with f.pqfile.open("ab") as handle:
                handle.write(b"broken")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                V.prepare(f.safe_file)
            self.assertFalse(versions.exists())
            self.assertFalse(active.exists())

    def test_forged_resigned_parquet_with_duplicate_key_refused(self):
        with fresh() as (f,versions,active,lock):
            f.rows[2]["symbol"]="SH600000"
            f.pq.write_table(
                f.pa.Table.from_pylist(f.rows,schema=V.READER.expected_schema(f.pa)),
                f.pqfile)
            f.manifest["private_parquet_sha256"]=V.READER.sha256_file(f.pqfile)
            f._resign()
            with self.assertRaisesRegex(ValueError,"Unverified private snapshot"):
                V.prepare(f.safe_file)
            self.assertFalse(versions.exists())

    def test_preexisting_version_tamper_denied(self):
        with fresh() as (f,versions,active,lock):
            version=V.prepare(f.safe_file)["version_sha256"]
            p=versions/(version+".json")
            info=json.loads(p.read_text())
            info["rows"]+=1
            p.write_text(json.dumps(info),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"content hash mismatch"):
                V.load_version(version)
            with self.assertRaises(ValueError):
                V.prepare(f.safe_file)

    def test_lock_blocks_registration_and_remains_unmodified(self):
        with fresh() as (f,versions,active,lock):
            lock.parent.mkdir(parents=True,exist_ok=True)
            lock.write_text("lock",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"lock already exists"):
                V.prepare(f.safe_file)
            self.assertEqual(lock.read_text(),"lock")
            self.assertFalse(active.exists())

    def test_no_pointer_activation_without_explicit_call(self):
        with fresh() as (f,versions,active,lock):
            version=V.prepare(f.safe_file)["version_sha256"]
            self.assertFalse(active.exists())
            self.assertIsNone(V.read_pointer())
            self.assertTrue((versions/(version+".json")).exists())
            self.assertFalse((f.module/"work"/"unified_parquet"/
                              "active-day-overlay.json").exists())


class PrivateVersionPointerTests(unittest.TestCase):
    def test_activate_and_rollback_only_module_private_pointer(self):
        with fresh() as (f,versions,active,lock):
            version=V.prepare(f.safe_file)["version_sha256"]
            report=V.activate(version)
            self.assertEqual(report["status"],"private_snapshot_pointer_activated")
            self.assertEqual(V.read_pointer(),version)
            self.assertEqual(V.status()["verified_active_snapshot_rows"],3)
            self.assertFalse((f.module/"work"/"unified_parquet"/
                              "active-day-overlay.json").exists())
            restore=V.rollback()
            self.assertIsNone(restore["restored_version_sha256"])
            self.assertIsNone(V.read_pointer())
            self.assertFalse(active.exists())
            self.assertTrue((versions/(version+".json")).is_file())
            with self.assertRaisesRegex(ValueError,"No private snapshot"):
                V.rollback()

    def test_version_chain_two_private_snapshots_and_one_step_rollback(self):
        with fresh() as (f,versions,active,lock):
            first=V.prepare(f.safe_file)["version_sha256"]
            V.activate(first)
            second_safe=another(f)
            second=V.prepare(second_safe)
            self.assertEqual(second["previous_version_sha256"],first)
            self.assertNotEqual(first,second["version_sha256"])
            V.activate(second["version_sha256"])
            self.assertEqual(V.read_pointer(),second["version_sha256"])
            result=V.rollback()
            self.assertEqual(result["restored_version_sha256"],first)
            self.assertEqual(V.read_pointer(),first)
            V.rollback()
            self.assertIsNone(V.read_pointer())
            self.assertEqual(len(list(versions.glob("*.json"))),2)

    def test_stale_activation_version_is_refused(self):
        with fresh() as (f,versions,active,lock):
            first=V.prepare(f.safe_file)["version_sha256"]
            second=V.prepare(another(f))["version_sha256"]
            V.activate(first)
            with self.assertRaisesRegex(ValueError,"advanced"):
                V.activate(second)
            self.assertEqual(V.read_pointer(),first)

    def test_active_snapshot_hash_mutation_blocks_status_and_rollback_target(self):
        with fresh() as (f,versions,active,lock):
            first=V.prepare(f.safe_file)["version_sha256"]
            V.activate(first)
            second=V.prepare(another(f))["version_sha256"]
            V.activate(second)
            with f.pqfile.open("ab") as stream:
                stream.write(b"tampered older private snapshot")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                V.rollback()
            self.assertEqual(V.read_pointer(),second)
            # Current pointer still refers to a valid second copy.
            self.assertEqual(V.status()["active_version_sha256"],second)

    def test_forged_or_symlink_private_pointer_rejected(self):
        with fresh() as (f,versions,active,lock):
            active.parent.mkdir(parents=True,exist_ok=True)
            active.write_text(json.dumps({"format":V.POINTER_FORMAT,
                                          "version_sha256":"bad"}))
            with self.assertRaises(ValueError):
                V.status()
            active.unlink()
            # Creating a real symlink needs SeCreateSymbolicLinkPrivilege on
            # standard Windows accounts (WinError 1314). Simulate the OS
            # symlink flag instead of skipping the security check.
            with patch.object(Path,"is_symlink",autospec=True,
                              side_effect=lambda path: path==active):
                with self.assertRaisesRegex(ValueError,"symlink"):
                    V.read_pointer()

    def test_version_rebind_after_source_safe_mutation_rejected(self):
        with fresh() as (f,versions,active,lock):
            version=V.prepare(f.safe_file)["version_sha256"]
            original=f.safe_file.read_text()
            f.safe_file.write_text(original+"\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                V.activate(version)
            self.assertFalse(active.exists())

    def test_corrupted_snapshot_manifest_cannot_activate(self):
        with fresh() as (f,versions,active,lock):
            version=V.prepare(f.safe_file)["version_sha256"]
            with f.manifest_file.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                V.activate(version)
            self.assertFalse(active.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
