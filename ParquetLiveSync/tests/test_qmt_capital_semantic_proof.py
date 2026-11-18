"""Strict offline proof: only Capital.m_quarter may vary; all dates and
business fields in the historical union must survive, without writes."""
from __future__ import annotations

from collections import Counter
import unittest

import qmt_extra_data as E
import qmt_capital_semantic_proof as G


def row(t=20260930, quarter=0., total=100., **extra):
    return {"_index": "row", "m_timetag": t,
            "m_quarter": quarter, "total_capital": total,
            "circulating_capital": 70., "m_anntime": 20261028, **extra}


def union(*snapshots):
    saved = Counter()
    for snapshot in snapshots:
        saved |= Counter(
            E.canonical_json({k: v for k, v in rec.items() if k != "_index"})
            for rec in snapshot)
    return saved


class CapitalSemanticProofTests(unittest.TestCase):
    def test_actual_case_single_meta_field_changed(self):
        old = [row(20260930, 0.), row(20260630, 2010001.)]
        fresh = [row(20260930, 6750319.), row(20260630, 2010001.)]
        result = G.prove_historical_union(union(old), fresh)
        self.assertEqual(result["classification"], "M_QUARTER_ONLY_CANDIDATE")
        self.assertEqual(result["m_quarter_differences"], 1)
        self.assertTrue(result["only_unstable_field_candidate"])
        self.assertFalse(result["ready_to_commit"])

    def test_same_full_rows_are_no_change(self):
        old = [row()]
        self.assertEqual(
            G.prove_historical_union(union(old), old)["classification"], "NO_CHANGE")

    def test_economic_total_capital_change_fails_closed(self):
        old = [row()]
        current = [row(total=101.)]
        result = G.prove_historical_union(union(old), current)
        self.assertEqual(result["classification"], "BUSINESS_OR_DATE_FIELD_CHANGED")
        self.assertFalse(result["only_unstable_field_candidate"])

    def test_circulating_stock_change_fails_closed(self):
        old = [row()]
        result = G.prove_historical_union(
            union(old), [row(quarter=123., circulating_capital=75.)])
        self.assertEqual(result["classification"], "BUSINESS_OR_DATE_FIELD_CHANGED")

    def test_added_new_date_fails_closed_not_hidden_as_meta(self):
        old = [row()]
        result = G.prove_historical_union(
            union(old), [row(quarter=123.), row(t=20261030, quarter=456.)])
        self.assertEqual(result["classification"], "REPORT_KEYS_ADDED_OR_REMOVED")

    def test_missing_prior_date_fails_closed(self):
        old = [row(t=20260930), row(t=20260630)]
        result = G.prove_historical_union(union(old), [row(t=20260930)])
        self.assertEqual(result["classification"], "REPORT_KEYS_ADDED_OR_REMOVED")

    def test_old_selected_history_business_revision_disqualifies(self):
        first = [row(t=20260930, quarter=0., total=100.)]
        second = [row(t=20260930, quarter=0., total=200.)]
        latest = [row(t=20260930, quarter=111., total=200.)]
        result = G.prove_historical_union(union(first, second), latest)
        self.assertEqual(result["classification"], "HISTORICAL_BUSINESS_FIELD_REVISION")

    def test_multiple_old_mquarter_variants_are_not_lost_or_double_counted(self):
        first = [row(t=20260930, quarter=0.)]
        second = [row(t=20260930, quarter=99.)]
        latest = [row(t=20260930, quarter=42.)]
        result = G.prove_historical_union(union(first, second), latest)
        self.assertEqual(result["classification"], "M_QUARTER_ONLY_CANDIDATE")
        self.assertEqual(result["history_report_dates"], 1)
        self.assertEqual(result["historical_raw_variants"], 2)

    def test_duplicate_source_report_date_fails_closed(self):
        saved = union([row()])
        current = [row(quarter=0.), row(quarter=99.)]
        self.assertEqual(G.prove_historical_union(
            saved, current)["classification"], "FRESH_DUPLICATE_REPORT_KEY")

    def test_field_added_fails_closed(self):
        prior = [row()]
        current = [row(quarter=33., extra_business=123.)]
        self.assertEqual(G.prove_historical_union(
            union(prior), current)["classification"], "BUSINESS_OR_DATE_FIELD_CHANGED")

    def test_missing_mquarter_column_fails_closed(self):
        old = [row()]
        fresh = [dict(old[0])]
        fresh[0].pop("m_quarter")
        self.assertEqual(G.prove_historical_union(
            union(old), fresh)["classification"], "M_QUARTER_FIELD_MISSING")

    def test_duplicate_exact_prior_raw_row_fails_closed(self):
        raw = E.canonical_json({k: v for k, v in row().items() if k != "_index"})
        self.assertEqual(G.prove_historical_union(
            Counter({raw: 2}), [row()])["classification"],
            "HISTORICAL_DUPLICATE_RAW_RECORD")

    def test_empty_prior_fails_closed(self):
        result = G.prove_historical_union(Counter(), [row()])
        self.assertEqual(result["classification"], "BASELINE_MISSING")

    def test_malformed_prior_fails_closed(self):
        result = G.prove_historical_union(Counter({"{": 1}), [row()])
        self.assertEqual(result["classification"],
                         "UNVERIFIED_MALFORMED_OR_UNKEYED_RECORD")


if __name__ == "__main__":
    unittest.main()
