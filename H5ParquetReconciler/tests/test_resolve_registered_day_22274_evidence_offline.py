"""Synthetic SHA-linked 22,274-day private evidence discovery tests.

All content is fictional JSON, no licensed H5/Parquet and no actual stock IDs.
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "private_day_sha_linked_evidence_resolver_test",
    HERE.parent / "tools" / "resolve-registered-day-22274-evidence-offline.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def write_json(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True)+"\n",
                 encoding="utf-8")
    return hashlib.sha256(p.read_bytes()).hexdigest()


class RegisteredDayEvidenceResolverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.reports = self.root / "reports"
        self.work = self.root / "work" / "unified_parquet"
        self.reports.mkdir()
        self.work.mkdir(parents=True)
        self.private = (self.work / "mixed_day_key_manifests" /
                        "keys_abcdef123456" / "keys.json")
        self.private_hash = write_json(self.private, {"fictional_keys": []})
        self.year = {}
        for year in (2016,2026):
            p = self.reports / f"fictional-exact-{year}.json"
            sha = write_json(p, {"requested_years":[year]})
            self.year[year] = (p,sha)
        self.ledger = self.reports / "fictional-ledger.json"
        ledger_doc = {
            "yearly_exact_source_coverage": [{
                "year": y,
                "audit_source_report_basename": self.year[y][0].name,
                "audit_source_report_sha256": self.year[y][1],
            } for y in (2016,2026)]
        }
        ledger_sha = write_json(self.ledger, ledger_doc)
        self.plan = self.reports / "fictional-plan.json"
        plan_sha = write_json(self.plan, {"eligible":83, "quarantined":5})
        self.live = self.reports / "fictional-live.json"
        live_doc = {
            "format": M.KEYS.FORMAT,
            "live_verified_nonquarantined_h5_only_stockdays":83,
            "quarantined_stockdays_excluded_from_exact_live_keyset":5,
            "original_market_files_written":False,
            "original_historical_ledger_sha256":ledger_sha,
            "private_key_manifest_relative_path":
                "work/unified_parquet/mixed_day_key_manifests/"
                "keys_abcdef123456/keys.json",
            "private_key_manifest_sha256":self.private_hash,
        }
        live_sha = write_json(self.live, live_doc)
        self.stage = self.reports / "fictional-mixed-stage.json"
        stage_doc = {
            "format":M.MIXED.FORMAT,
            "verified_mixed_h5_only_stockday_bars":83,
            "quarantined_2026_07_16_stockday_bars_not_included":5,
            "ready_for_automatic_market_merge":False,
            "source_live_key_safe_sha256":live_sha,
            "offline_mixed_plan_sha256":plan_sha,
            "private_key_manifest_sha256":self.private_hash,
        }
        stage_sha = write_json(self.stage, stage_doc)
        self.version = "a"*64
        self.entry = {
            "candidate_total_new_stockday_rows":22274,
            "ready_for_production_query":False,
            "mixed_stage_safe_basename":self.stage.name,
            "mixed_stage_safe_sha256":stage_sha,
        }
        self.originals = {"ledger":(self.ledger, self.ledger.read_bytes()),
                          "plan":(self.plan, self.plan.read_bytes())}
        self.patches = [
            patch.object(M, "MODULE", self.root),
            patch.object(M, "REPORTS", self.reports),
            patch.object(M, "WORK", self.work),
            patch.object(M.REG, "load_version", return_value=self.entry),
            patch.object(M.KEYS, "safe_file", side_effect=self.safe_file),
            patch.object(M.KEYS, "verified_existing_plan",
                         return_value=(self.originals,{2016:[],2026:[]})),
            patch.object(M.MIXED, "read_verified_key_manifest",
                         return_value=({}, b"", {}, b"", {}, set())),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def safe_file(self, path, read=False, max_bytes=M.MAX_REPORT_BYTES):
        p = Path(path)
        if (not read or p.is_symlink()
                or p.resolve().parent != self.reports.resolve()
                or not p.is_file()
                or not 0 < p.stat().st_size <= max_bytes):
            raise ValueError("Untrusted bounded SAFE report")
        return p.resolve()

    def test_discover_all_seven_fields_without_any_new_file(self):
        result = M.prepare(self.version)
        self.assertEqual(result["identified_evidence_inputs"],7)
        self.assertEqual(result["whole_plus_mixed_candidate_count"],22274)
        self.assertFalse(result["original_market_files_read"])
        self.assertIsNone(result["private_config_path"])
        self.assertFalse(M.config_path(self.version).exists())

    def test_private_config_created_only_when_explicit_and_is_idempotent(self):
        first=M.prepare(self.version,write=True)
        self.assertEqual(first["state"],"private_22274_research_evidence_ready_locally")
        p=Path(first["private_config_path"])
        old=(p.stat().st_size,p.stat().st_mtime_ns)
        self.assertEqual(set(json.loads(p.read_text())),set(M.CONFIG_FIELDS))
        self.assertEqual(M.prepare(self.version,write=True)["private_config_path"],str(p))
        self.assertEqual(old,(p.stat().st_size,p.stat().st_mtime_ns))

    def test_changed_source_annual_report_is_rejected_by_sha(self):
        self.year[2016][0].write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,r"^Original annual report SHA mismatch$"):
            M.prepare(self.version)

    def test_changed_live_safe_is_rejected_before_private_open(self):
        self.live.write_text('{"tampered":true}')
        with self.assertRaisesRegex(ValueError,"Missing SHA-linked"):
            M.prepare(self.version)

    def test_repeated_sha_identical_safe_is_resolved_deterministically(self):
        duplicate=self.reports/"aaa-copied-fictional-live.json"
        duplicate.write_bytes(self.live.read_bytes())
        resolved=M.resolve(self.version)
        self.assertEqual(Path(resolved["live_safe"]),duplicate.resolve())
        self.assertEqual(Path(resolved["private_keys"]),self.private.resolve())

    def test_wrong_registered_candidate_count_fails_closed(self):
        self.entry["candidate_total_new_stockday_rows"]=22273
        with self.assertRaisesRegex(ValueError,"exact unactivated"):
            M.prepare(self.version)

    def test_existing_changed_private_config_never_overwritten(self):
        p=M.config_path(self.version)
        p.write_text("changed",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"refusing overwrite"):
            M.prepare(self.version,write=True)
        self.assertEqual(p.read_text(),"changed")

    def test_missing_plan_fails_before_any_market_read(self):
        self.plan.unlink()
        with self.assertRaisesRegex(ValueError,"Missing SHA-linked"):
            M.prepare(self.version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
