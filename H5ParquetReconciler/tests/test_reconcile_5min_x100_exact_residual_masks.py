"""Synthetic candidate ×100 exclusive-mask census; licensed OHLCV never used."""
import importlib.util
import tempfile
import unittest
from collections import Counter
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "reconcile-local-a-share-h5-parquet.py")
SPEC = importlib.util.spec_from_file_location("reconcile_5min_exact_masks", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

MASKS = (
    "none", "volume", "amount", "price", "volume_amount",
    "volume_price", "amount_price", "volume_amount_price"
)


class ExactResidualMasksTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = M.db_open(Path(folder.name) / "synthetic.sqlite")
        self.addCleanup(self.db.close)

    def populate(self, *, include_unmatched=False):
        h, p = [], []
        for i, mask in enumerate(MASKS):
            symbol = "SH600000" if i < 4 else "BJ920069"
            day = 20260924 if i < 4 else 20260928
            label = 935 + 5 * (i % 4)
            stamp = day * 10000 + label
            h.append((symbol, stamp, 10, 11, 9, 10, 10, 1000))
            p.append((
                symbol, stamp,
                10.03 if "price" in mask else 10, 11, 9, 10,
                1200 if "volume" in mask else 1000,
                2005000 if "amount" in mask else 1000
            ))
        if include_unmatched:
            p.append(("SZ000001", 202609300935, 10, 11, 9, 10, 1000, 1000))
        self.db.executemany(
            "INSERT INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)", h)
        stats = Counter({"period": "5min", "from_date": "2026-09-24",
                         "to_date": "2026-09-30"})
        M.check_batch(self.db, p, stats, "5min")
        return stats

    def test_each_exact_field_mask_and_group_conservation(self):
        stats = self.populate(include_unmatched=True)
        candidate = stats["quantity_scale_diagnostics"][
            "h5_volume_times_100_candidate"]
        self.assertEqual(stats["matched_keys"], 8)
        self.assertEqual(stats["pq_only_rows"], 1)
        self.assertEqual(candidate["candidate_volume_mismatch"], 4)
        self.assertEqual(candidate[
            "candidate_value_mismatch_with_original_price_and_amount_rules"], 7)
        self.assertEqual(
            candidate["exact_residual_field_mask_counts"],
            {key: 1 for key in MASKS})
        M.finalize_candidate_residual_masks(candidate, stats)
        self.assertNotIn("_internal_residual_stock_days", candidate)
        self.assertTrue(candidate["exact_masks_are_mutually_exclusive"])
        self.assertEqual(len(candidate["exact_residual_top_stock_days"]), 2)
        self.assertEqual(candidate["exact_residual_top_stock_days"][0]["symbol"],
                         "BJ920069")
        self.assertEqual(candidate["exact_residual_top_stock_days"][0][
            "candidate_conflicting_bars"], 4)
        self.assertEqual(candidate["exact_residual_top_stock_days"][1][
            "candidate_conflicting_bars"], 3)
        self.assertNotIn("SZ_other_prefix", candidate["exact_field_mask_by_prefix"])
        self.assertNotIn("20260930", candidate["exact_field_mask_by_day"])
        self.assertEqual(candidate["exact_field_mask_by_day"]["20260924"]["none"], 1)
        self.assertEqual(candidate["exact_field_mask_by_prefix"][
            "BJ_prefix"]["volume_amount_price"], 1)
        self.assertFalse(candidate["candidate_unit_mapping_certified"])

    def test_reject_tampered_mask_marginal(self):
        stats = self.populate()
        candidate = stats["quantity_scale_diagnostics"][
            "h5_volume_times_100_candidate"]
        candidate["exact_residual_field_mask_counts"]["volume"] += 1
        with self.assertRaisesRegex(ValueError, "marginal conservation"):
            M.finalize_candidate_residual_masks(candidate, stats)

    def test_reject_corrupt_daily_partition_without_touching_source(self):
        stats = self.populate()
        candidate = stats["quantity_scale_diagnostics"][
            "h5_volume_times_100_candidate"]
        candidate["exact_field_mask_by_day"]["20260924"]["price"] += 1
        with self.assertRaisesRegex(ValueError, "group match mismatch"):
            M.finalize_candidate_residual_masks(candidate, stats)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM h").fetchone()[0], 8)

    def test_explicit_none_and_two_source_guard(self):
        self.assertEqual(M.candidate_residual_mask(False,False,False),"none")
        self.assertEqual(M.candidate_residual_mask(True,True,True),
                         "volume_amount_price")
        self.assertEqual(M.candidate_residual_mask(False,True,True),
                         "amount_price")
        self.assertEqual(len(M.CANDIDATE_RESIDUAL_MASKS),8)
        stats = Counter({"period":"day","from_date":"2026-09-29",
                         "to_date":"2026-09-29"})
        M.record_bounded_5min_quantity_evidence(
            stats, "SH600000", 202609290935,
            (10,11,9,10,1000,1000),(10,11,9,10,10,1000),
            ["volume"], {})
        self.assertNotIn("quantity_scale_diagnostics",stats)


if __name__=="__main__":
    unittest.main(verbosity=2)
