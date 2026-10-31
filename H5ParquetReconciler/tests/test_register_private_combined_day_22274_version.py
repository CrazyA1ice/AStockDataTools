"""Purely synthetic registry tests; no purchased Parquet or native H5 IO."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "combined_22274_version_registry_test",
    HERE.parent / "tools" / "register-private-combined-day-22274-version.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "module"
        reports = module / "reports"
        reports.mkdir(parents=True)
        work = module / "work" / "unified_parquet"
        versions = work / "combined_day_versions"
        lock = work / ".combined-day-version-create.lock"
        prior = reports / "prior-union.json"
        mixed = reports / "mixed-stage.json"
        fresh = reports / "fresh-recheck.json"
        out = reports / "registered.json"
        mixed.write_text('{"isolated_stage":"synthetic"}\n', encoding="utf-8")
        proof = {
            "format": R.PRE.FORMAT,
            "state": "read_only_union_preflight_passed_not_promoted",
            "candidate_total_new_stockday_rows": 22274,
            "whole_day_candidate_rows": 22191,
            "mixed_stockday_candidate_rows": 83,
            "quarantined_2026_07_16_stockday_bars_not_included": 5,
            "whole_day_overlay_version_sha256": "a"*64,
            "mixed_stage_safe_sha256": sha(mixed.read_bytes()),
            "mixed_stage_parquet_sha256": "b"*64,
            "mixed_stage_manifest_sha256": "c"*64,
            "original_source_stat_sha256": "d"*64,
            "h5_mirror_created": False,
            "new_private_combined_version_created": False,
            "private_or_production_active_pointer_modified": False,
            "purchased_parquet_replaced": False,
            "source_market_files_written": False,
            "candidate_source_units_certified": False,
            "ready_for_automatic_market_merge": False,
        }
        prior.write_text(json.dumps(proof,sort_keys=True), encoding="utf-8")

        def fresh_proof(*args):
            target = args[-1]
            target.write_text(json.dumps(proof,sort_keys=True), encoding="utf-8")
            return dict(proof)

        with patch.object(R, "MODULE", module), \
             patch.object(R, "WORK", work), \
             patch.object(R, "VERSIONS", versions), \
             patch.object(R, "LOCK", lock), \
             patch.object(R.PRE, "REPORTS", reports), \
             patch.object(R.PRE.KEYS, "REPORTS", reports), \
             patch.object(R.PRE, "verify", side_effect=fresh_proof) as scan:
            yield module, reports, work, versions, lock, prior, mixed, fresh, out, proof, scan


def register(prior, mixed, fresh, out):
    # Remaining paths are dummy only: PRE.verify() is patched, and nobody
    # opens source market files during these local synthetic tests.
    fake = Path("__synthetic_market_only__")
    return R.prepare(fake, "a"*64, mixed, fake, fake, fake, fake, fake,
                     fake, prior, fresh, out)


class PrivateCombinedVersionTests(unittest.TestCase):
    def test_prepares_immutable_version_without_pointer_or_market_writes(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            result = register(prior,mixed,fresh,out)
            self.assertEqual(result["candidate_total_new_stockday_rows"],22274)
            self.assertTrue(result["new_private_combined_version_created"])
            self.assertFalse(result["private_or_production_active_pointer_modified"])
            self.assertTrue(out.is_file())
            self.assertEqual(scan.call_count,1)
            registry = versions/(result["version_sha256"]+".json")
            self.assertTrue(registry.is_file())
            self.assertFalse(lock.exists())
            self.assertFalse((work/"active-day-overlay.json").exists())
            self.assertFalse((work/"active-private-joined-day.json").exists())
            entry=R.load_version(result["version_sha256"])
            self.assertEqual(entry["mixed_stockday_candidate_rows"],83)
            self.assertEqual(entry["source_priority"],"purchased_parquet_first_exact_symbol_day")
            for forbidden in ("SH600000","SZ000001","openPrice","transCount","HikyuuData","AllCycleAStockData"):
                self.assertNotIn(forbidden,registry.read_text())

    def test_bad_prior_row_count_rejected_before_live_scan(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            proof["candidate_total_new_stockday_rows"] = 22273
            prior.write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError,"Untrusted"):
                register(prior,mixed,fresh,out)
            scan.assert_not_called()
            self.assertFalse(versions.exists())

    def test_unsafe_prior_claims_production_or_certified_rejected(self):
        for field in ("candidate_source_units_certified","ready_for_automatic_market_merge",
                      "private_or_production_active_pointer_modified"):
            with self.subTest(field=field),fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
                proof[field]=True
                prior.write_text(json.dumps(proof))
                with self.assertRaisesRegex(ValueError,"Untrusted"):
                    register(prior,mixed,fresh,out)
                scan.assert_not_called()

    def test_modified_mixed_stage_safe_sha_rejected(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            mixed.write_text("tampered")
            with self.assertRaisesRegex(ValueError,"Mixed stage SAFE differs"):
                register(prior,mixed,fresh,out)
            scan.assert_not_called()
            self.assertFalse(versions.exists())

    def test_fresh_live_proof_changed_rejected_without_version(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            def changed(*args):
                new=dict(proof)
                new["original_source_stat_sha256"]="f"*64
                args[-1].write_text(json.dumps(new))
                return new
            scan.side_effect=changed
            with self.assertRaisesRegex(ValueError,"differs"):
                register(prior,mixed,fresh,out)
            self.assertFalse(versions.exists())

    def test_concurrent_lock_rejected_without_pointer(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            work.mkdir(parents=True)
            lock.write_text("occupied")
            with self.assertRaisesRegex(ValueError,"locked"):
                register(prior,mixed,fresh,out)
            self.assertEqual(lock.read_text(),"occupied")
            self.assertFalse(versions.exists())

    def test_tampered_registered_version_body_rejected(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            result=register(prior,mixed,fresh,out)
            path=versions/(result["version_sha256"]+".json")
            entry=json.loads(path.read_text())
            entry["ready_for_production_query"]=True
            path.write_text(json.dumps(entry))
            with self.assertRaisesRegex(ValueError,"Untrusted"):
                R.load_version(result["version_sha256"])

    def test_modified_referenced_preflight_safe_rejected_on_load(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            result=register(prior,mixed,fresh,out)
            prior.write_bytes(prior.read_bytes()+b" ")
            with self.assertRaisesRegex(ValueError,"Referenced SAFE changed"):
                R.load_version(result["version_sha256"])

    def test_existing_report_cannot_be_overwritten(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            out.write_text("existing")
            with self.assertRaisesRegex(ValueError,"NEW"):
                register(prior,mixed,fresh,out)
            self.assertEqual(out.read_text(),"existing")
            scan.assert_not_called()
            self.assertFalse(versions.exists())

    def test_preflight_and_registration_report_paths_must_differ(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            with self.assertRaisesRegex(ValueError,"distinct"):
                register(prior,mixed,fresh,fresh)
            scan.assert_not_called()
            self.assertFalse(versions.exists())

    def test_symlinked_private_versions_root_rejected(self):
        with fixture() as (module,reports,work,versions,lock,prior,mixed,fresh,out,proof,scan):
            original_is_symlink = Path.is_symlink
            with patch.object(Path,"is_symlink",
                              lambda p: p == versions or original_is_symlink(p)):
                with self.assertRaisesRegex(ValueError,"symlinked"):
                    register(prior,mixed,fresh,out)
            scan.assert_not_called()


if __name__=="__main__":
    unittest.main(verbosity=2)
