"""Synthetic private snapshot assemble/activate/rollback integration tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "day_overlay_versioner", HERE.parent / "tools" /
    "build-parquet-primary-day-overlay.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

STAGE_SPEC = importlib.util.spec_from_file_location(
    "day_overlay_synthetic_sources",
    HERE / "test_stage_h5_only_day_to_parquet.py")
TEST_STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(TEST_STAGE)


@contextmanager
def ready():
    with TEST_STAGE.small_sources() as (root, module, report, gate, purchased):
        stage_dir = (module / "work" / "unified_parquet" /
                     "staging" / "day-20261008-v1")
        result = TEST_STAGE.M.stage(root, gate, report,
                                    date(2026, 10, 8), stage_dir, 200)
        self_name = module / "work" / "unified_parquet"
        with patch.object(M, "MODULE", module), \
                patch.object(M, "WORK", self_name), \
                patch.object(M, "STAGING", self_name / "staging"), \
                patch.object(M, "VERSIONS", self_name / "versions"), \
                patch.object(M, "ACTIVE", self_name / "active-day-overlay.json"), \
                patch.object(M.stage_tool, "MODULE", module), \
                patch.object(M.stage_tool, "REPORTS", module / "reports"), \
                patch.object(M.stage_tool, "STAGING", self_name / "staging"):
            yield root, module, report, gate, purchased, stage_dir, result


class PrivateDayOverlayTests(unittest.TestCase):
    def test_prepare_activate_rollback_does_not_change_original_files(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            before = M.stage_tool.file_digest(purchased)
            prepared = M.prepare(root, gate, report, [stage_dir])
            self.assertEqual(prepared["private_rows"], 1)
            self.assertEqual(prepared["prepared_days"], ["2026-10-08"])
            self.assertFalse(prepared["production_query_route_modified"])
            self.assertFalse(M.ACTIVE.exists())
            h = prepared["version_sha256"]
            version = M.load_version(h)
            self.assertEqual(version["rows_in_overlay"], 1)
            activated = M.activate(root, gate, report, h)
            self.assertEqual(activated["version_sha256"], h)
            self.assertEqual(M.read_active(), h)
            self.assertFalse(activated["production_query_route_modified"])
            with self.assertRaisesRegex(ValueError, "advanced"):
                M.activate(root, gate, report, h)
            undone = M.rollback()
            self.assertEqual(undone["status"],
                             "private_pointer_restored_or_disabled")
            self.assertFalse(M.ACTIVE.exists())
            self.assertEqual(M.stage_tool.file_digest(purchased), before)
            self.assertTrue((M.VERSIONS / (h + ".json")).is_file())
            self.assertEqual(M.load_version(h)["version_sha256"], h)

    def test_prepare_rechecks_all_candidate_dates_via_bounded_batch(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            real_batch = M.stage_tool.verify_live_absence_dates
            with patch.object(M.stage_tool, "verify_live_absence_dates",
                              wraps=real_batch) as batch, \
                    patch.object(M.stage_tool, "verify_live_absence",
                                 side_effect=AssertionError(
                                     "unexpected day-by-day rescan")):
                prepared = M.prepare(root, gate, report, [stage_dir])
            batch.assert_called_once()
            self.assertEqual(
                batch.call_args.args[2], {"2026-10-08": 1})
            self.assertEqual(prepared["private_rows"], 1)

    def test_compact_gate_day_key_matches_iso_staging_day(self):
        # The generated gate and source report index daily partitions as
        # YYYYMMDD, but a stage manifest uses the ISO YYYY-MM-DD date.
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            gate_json = json.loads(gate.read_text(encoding="utf-8"))
            self.assertEqual(
                [x["date"] for x in gate_json["daily_coverage"]
                 if x["category"] == "entire_date_h5_only_candidate"],
                ["20261008"])
            self.assertEqual(stage["day"], "2026-10-08")
            evidence = M.verify_reports(gate, report)
            self.assertEqual(evidence["expected"], {"2026-10-08": 1})
            chosen = M.validate_stages([stage_dir], evidence)
            self.assertEqual(chosen[0]["day"], "2026-10-08")
            self.assertEqual(chosen[0]["rows"], 1)

    def test_noncanonical_stage_date_fails_closed(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            manifest_path = stage_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["day"] = "20261008"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Stage is not eligible"):
                M.prepare(root, gate, report, [stage_dir])
            self.assertFalse(M.ACTIVE.exists())

    def test_stage_manifest_tamper_blocks_snapshot_prepare(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            path = stage_dir / "manifest.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["staged_bars"] = 3
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Stage is not eligible"):
                M.prepare(root, gate, report, [stage_dir])
            self.assertFalse(M.ACTIVE.exists())

    def test_tampered_staged_parquet_hash_blocks_prepare(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            path = stage_dir / "day.parquet"
            with path.open("ab") as f:
                f.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                M.prepare(root, gate, report, [stage_dir])

    def test_duplicate_stages_do_not_create_duplicate_market_rows(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            with self.assertRaisesRegex(ValueError, "exactly cover"):
                M.prepare(root, gate, report, [stage_dir, stage_dir])

    def test_malformed_unlinked_gate_rejected(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            data = json.loads(gate.read_text(encoding="utf-8"))
            data["source_report_sha256"] = "0" * 64
            gate.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid or stale"):
                M.prepare(root, gate, report, [stage_dir])

    def test_extra_purchased_date_row_after_staging_blocks_snapshot(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            target = purchased.parent / "2026-10.parquet"
            pq.write_table(pa.Table.from_pylist([{
                "ts": TEST_STAGE.stamp_ms(date(2026, 10, 8)),
                "symbol": "600000.XSHG",
                "open": 12.3, "high": 12.5, "low": 12.2, "close": 12.4,
                "volume": 15000.0, "amount": 1800000.0,
                "source": "purchased",
            }]), target)
            with self.assertRaisesRegex(ValueError, "Live source recheck"):
                M.prepare(root, gate, report, [stage_dir])
            self.assertFalse(M.ACTIVE.exists())

    def test_stage_path_outside_module_prohibited(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            with self.assertRaisesRegex(ValueError, "direct existing private"):
                M.prepare(root, gate, report, [root / "HikyuuData"])

    def test_version_manifest_tamper_refuses_activation(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            prepared = M.prepare(root, gate, report, [stage_dir])
            p = M.VERSIONS / (prepared["version_sha256"] + ".json")
            record = json.loads(p.read_text(encoding="utf-8"))
            record["rows_in_overlay"] = 999
            p.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Tampered"):
                M.activate(root, gate, report, prepared["version_sha256"])
            self.assertFalse(M.ACTIVE.exists())

    def test_stale_active_pointer_rejects_unsafe_prepare_or_activation(self):
        with ready() as (root, module, report, gate, purchased, stage_dir, stage):
            prepared = M.prepare(root, gate, report, [stage_dir])
            M.atomic_active("f" * 64)
            with self.assertRaisesRegex(ValueError, "advanced"):
                M.activate(root, gate, report, prepared["version_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
