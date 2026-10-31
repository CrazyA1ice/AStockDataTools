"""Pure synthetic union preflight gates; no licensed market data reads."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "private_day_combined_readonly_under_test",
    HERE.parent / "tools" / "verify-private-combined-day-22274-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class CombinedPrivateUnionTests(unittest.TestCase):
    def test_new_safe_report_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            existing = reports / "original.json"
            existing.write_text("{}")
            with patch.object(M, "REPORTS", reports):
                self.assertEqual(M.new_report(reports/"new.json"), reports/"new.json")
                with self.assertRaisesRegex(ValueError, "NEW"):
                    M.new_report(existing)

    def test_new_safe_report_cannot_escape_module_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root/"reports"
            reports.mkdir()
            with patch.object(M, "REPORTS", reports), self.assertRaises(ValueError):
                M.new_report(root/"elsewhere.json")

    def test_new_safe_report_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root/"reports"
            reports.mkdir()
            candidate = reports/"link.json"
            original_is_symlink = Path.is_symlink
            # Windows may disallow symlink creation without Developer Mode.
            with patch.object(Path, "is_symlink",
                              lambda p: p == candidate or original_is_symlink(p)):
                with patch.object(M, "REPORTS", reports), self.assertRaises(ValueError):
                    M.new_report(candidate)

    def test_guard_rejects_unsafe_mixed_stage_before_private_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            safe = root/"mixed.json"
            safe.write_text(json.dumps({"action": "plan", "stage_row_count": 83}))
            with patch.object(M.KEYS, "safe_file", return_value=safe):
                with patch.object(M.MIXED, "read_verified_key_manifest") as downstream:
                    with self.assertRaisesRegex(ValueError, "not a certified"):
                        M.verify_mixed_stage(safe, None, None, {}, {})
                    downstream.assert_not_called()

    def fixtures(self, root):
        home = root / "module"
        market = root / "market"
        reports = home / "reports"
        reports.mkdir(parents=True)
        (market/"HikyuuData").mkdir(parents=True)
        (market/"AllCycleAStockData"/"day").mkdir(parents=True)
        files = [reports / n for n in ("candidate.json", "private.json", "live.json", "source.json", "manifest.json")]
        for f in files:
            f.write_bytes(f.name.encode())
        stage_safe, private, live, source, meta = files
        out = reports / "union.json"
        whole = {"rows_in_overlay": 22191}
        dates = [{"day": d, "rows": 1} for d in sorted(M.WHOLE_DATES)]
        dates[0]["rows"] = 22188
        origins = {"plan": (source, source.read_bytes())}
        selected = {("SH600000", 201609300000)} | {(f"SH600{i:03d}", 202604080000) for i in range(1, 83)}
        mixed = ({"source_stat_sha256": "source"}, selected, private, meta,
                 M.sha(private), [{"symbol": "SH600000", "ts": 1}], stage_safe)
        return market, reports, out, whole, dates, origins, mixed, live, private, source

    def run_fake(self, root, *, modified=None, whole=None, selected=None, expected=None):
        market, reports, out, w, dates, origins, mixed, live, private, source = self.fixtures(root)
        if whole is not None:
            w = whole
        if selected is not None:
            mixed = (mixed[0], selected, *mixed[2:])
        actual = mixed[5]
        expected = actual if expected is None else expected
        with patch.object(M, "MODULE", reports.parent), patch.object(M, "REPORTS", reports), \
             patch.object(M.WHOLE, "verified_version", return_value=(w, {"source": True}, dates)), \
             patch.object(M.KEYS, "verified_existing_plan", return_value=(origins, {})), \
             patch.object(M.KEYS, "state_digest", side_effect=modified or ["source","source"]), \
             patch.object(M, "verify_mixed_stage", return_value=mixed), \
             patch.object(M.MIXED, "verify_all_live_absence", return_value=1236863), \
             patch.object(M.MIXED, "normalize_private_h5_rows", return_value=expected), \
             patch.object(M.OVERLAY, "recheck_live") as original_market_recheck:
            result = M.verify(market, "a"*64, mixed[6], live, private,
                              source, source, source, source, out)
            original_market_recheck.assert_called_once()
            return result, out

    def test_synthetic_valid_union_summarizes_22274_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, report = self.run_fake(Path(tmp))
            self.assertEqual(result["candidate_total_new_stockday_rows"], 22274)
            self.assertEqual(result["whole_day_candidate_rows"], 22191)
            self.assertEqual(result["mixed_stockday_candidate_rows"], 83)
            self.assertFalse(result["private_or_production_active_pointer_modified"])
            self.assertFalse(result["new_private_combined_version_created"])
            self.assertFalse(result["candidate_source_units_certified"])
            self.assertTrue(report.is_file())
            self.assertNotIn("SH600000", report.read_text())

    def test_mixed_and_whole_day_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "overlaps"):
                self.run_fake(Path(tmp), selected={("SH600000", 202610080000)} | {(f"SH600{i:03d}", 202604080000) for i in range(1, 83)})

    def test_mixed_ohlcva_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "differs"):
                self.run_fake(Path(tmp), expected=[{"amount": 999.0}])

    def test_live_source_state_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "changed"):
                self.run_fake(Path(tmp), modified=["source","different"])

    def test_wrong_full_market_row_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "audited exact four"):
                self.run_fake(Path(tmp), whole={"rows_in_overlay": 22190})


if __name__ == "__main__":
    unittest.main(verbosity=2)
