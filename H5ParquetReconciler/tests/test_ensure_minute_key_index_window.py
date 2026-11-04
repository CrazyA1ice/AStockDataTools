"""Synthetic idempotent purchased minute index creation/reuse safety checks."""
import contextlib
import hashlib
import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


E=load("test_idempotent_purchased_minute_index",
       HERE.parent/"tools"/"ensure-minute-key-index-window.py")
F=load("test_existing_real_synthetic_parquet_h5_fixture",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class IdempotentMinuteIndexWindowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.day=date(2026,10,13)
        self.store=self.root/"work"/"unified_parquet"/"minute_key_index"

    def patched(self):
        ctx=contextlib.ExitStack()
        for mod,key,val in (
            (E.I,"STORE",self.store),
            (E.I.N.ST,"MODULE",self.root),
            (E.I.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
            (E.I.N.ST,"REPORTS",self.root/"reports"),
        ):
            ctx.enter_context(patch.object(mod,key,val))
        return ctx

    def sources(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for directory in ("AllCycleAStockData","HikyuuData")
                for p in (self.root/directory).rglob("*") if p.is_file()}

    def test_new_window_once_then_reuse_same_index_without_source_parquet_scan(self):
        before=self.sources()
        with self.patched():
            first=E.ensure(self.root,self.day,self.day,run_id="aabbccddee00")
            self.assertTrue(first["new_private_index_created"])
            self.assertEqual(first["purchased_ohlcva_rows_copied"],0)
            with patch.object(E.I,"purchased_masks",
                              side_effect=AssertionError("should never scan vendor rows again")):
                second=E.ensure(self.root,self.day,self.day)
        self.assertEqual(second["status"],
                         "reused_existing_source_key_index_no_new_file")
        self.assertEqual(first["index_path"],second["index_path"])
        self.assertEqual(len(list(self.store.glob("*.sqlite"))),1)
        self.assertEqual(before,self.sources())

    def test_changed_source_rejects_index_instead_of_rebuilding(self):
        with self.patched():
            first=E.ensure(self.root,self.day,self.day,run_id="aabbccddee00")
            f=self.root/"HikyuuData"/"sh_1min.h5"
            f.touch()
            # Touch may be a no-op with coarse timestamp on some systems;
            # add a guaranteed new recognized licensed-source file.
            import h5py
            with h5py.File(self.root/"HikyuuData"/"bj_1min.h5","r+") as db:
                db.attrs["synthetic_change"]="updated"
            with self.assertRaisesRegex(ValueError,"source metadata changed"):
                E.ensure(self.root,self.day,self.day)
        self.assertTrue(Path(first["index_path"]).is_file())
        self.assertEqual(len(list(self.store.glob("*.sqlite"))),1)

    def test_multiple_matching_completed_indexes_fail_closed(self):
        with self.patched():
            first=E.ensure(self.root,self.day,self.day,run_id="aabbccddee00")
            source=Path(first["index_path"])
            other=self.store/source.name.replace("aabbccddee00","112233445566")
            other.write_bytes(source.read_bytes())
            with self.assertRaisesRegex(ValueError,"Multiple purchased"):
                E.ensure(self.root,self.day,self.day)
        self.assertEqual(len(list(self.store.glob("*.sqlite"))),2)

    def test_range_bound_failure_does_not_create_index(self):
        with self.patched():
            with self.assertRaisesRegex(ValueError,"1..31 days"):
                E.ensure(self.root,date(2026,9,1),date(2026,10,13))
        self.assertFalse(self.store.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
