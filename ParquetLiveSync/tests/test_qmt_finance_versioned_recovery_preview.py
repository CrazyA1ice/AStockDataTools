"""Synthetic nine-table finance-history recovery previews; NEVER QMT or writes."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parent.parent / "qmt_finance_versioned_recovery_preview.py"
spec = importlib.util.spec_from_file_location("recovery_preview", FILE)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


class E:
    FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital",
                  "Top10FlowHolder", "Top10Holder", "HolderNum",
                  "PershareIndex", "PerShare")

    @staticmethod
    def canonical_json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)


class F:
    E = E


def history(t, *rows):
    baseline = {name: Counter() for name in E.FIN_TABLES}
    baseline[t] = Counter(R.encode(row, F) for row in rows)
    return baseline


def fresh(t, *rows):
    current = {name: [] for name in E.FIN_TABLES}
    current[t] = [dict(row, _index=str(i)) for i, row in enumerate(rows)]
    return current


def make_old(name="甲", *, end="20260930", type_name="公司",
             declaration="20261022", shares=100):
    return {"endDate": end, "name": name, "type": type_name,
            "declareDate": declaration, "shares": shares}


def capital(key, quarter, value=100):
    return {"m_timetag": key, "m_quarter": quarter, "total_capital": value}


def plan(t, a, b, mode="HOLDER_METADATA", code="002388.SZ",
         evidence=None):
    return R.preview_symbol(code, mode, t, history(t, *a), fresh(t, *b),
                            F, evidence=evidence, ledger_sha256="a" * 64)


class MetadataTests(unittest.TestCase):
    def test_only_disclosure_date_change(self):
        old = make_old()
        new = dict(old, declareDate="20261027")
        p = plan("Top10Holder", [old], [new])
        self.assertEqual(p["classification"], "HOLDER_METADATA_REVIEW_REQUIRED")
        self.assertEqual(p["proof"]["revised_rows"], 1)
        self.assertEqual(p["readiness"], "REVIEW_ONLY_NO_APPLY_AUTHORIZATION")
        self.assertFalse(p["allow_auto_clear"])
        self.assertFalse(p["allow_apply"])
        self.assertFalse(p["snapshot_state_changed"])
        self.assertFalse(p["candidate_is_parquet_snapshot"])

    def test_only_type_change(self):
        old = make_old()
        new = dict(old, type="机构投资账户")
        p = plan("Top10FlowHolder", [old], [new])
        self.assertEqual(p["proof"]["pair_sha256"][0]["changed_fields"], ["type"])

    def test_date_and_type_together(self):
        old = make_old()
        new = dict(old, type="自然人", declareDate="20261029")
        p = plan("Top10Holder", [old], [new])
        self.assertEqual(p["proof"]["pair_sha256"][0]["changed_fields"],
                         ["declareDate", "type"])

    def test_holder_num_disclosure_date(self):
        old = {"endDate": "20260930", "shareholder": 100, "declareDate": "20261022"}
        new = dict(old, declareDate="20261029")
        p = plan("HolderNum", [old], [new])
        self.assertEqual(p["classification"], "HOLDER_METADATA_REVIEW_REQUIRED")

    def test_holder_num_count_change_not_whitelisted(self):
        old = {"endDate": "20260930", "shareholder": 100, "declareDate": "20261022"}
        new = dict(old, shareholder=101)
        with self.assertRaisesRegex(R.ReviewBlocked, "REPORT_OR_BUSINESS_PROJECTION"):
            plan("HolderNum", [old], [new])

    def test_name_revision_not_generic_holder_metadata(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "REPORT_OR_BUSINESS_PROJECTION"):
            plan("Top10Holder", [old], [dict(old, name="乙")])

    def test_report_end_change_blocked(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "REPORT_OR_BUSINESS_PROJECTION"):
            plan("Top10Holder", [old], [dict(old, endDate="20261231")])

    def test_non_unique_projection_blocked(self):
        old = make_old()
        duplicate = dict(old, declareDate="20261028")
        new = dict(old, declareDate="20261027")
        with self.assertRaisesRegex(R.ReviewBlocked, "NONUNIQUE_PAIRING"):
            plan("Top10Holder", [old, duplicate],
                 [new, duplicate])

    def test_unbalanced_record_counts_blocked(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "NO_BALANCED_RAW_REVISIONS"):
            plan("Top10Holder", [old], [old, make_old(name="乙")])

    def test_two_row_distinct_metadata_revisions_are_allowed_for_review(self):
        a, b = make_old(name="甲"), make_old(name="乙", shares=101)
        p = plan("Top10Holder", [a, b],
                 [dict(a, declareDate="20261027"),
                  dict(b, type="自然人")])
        self.assertEqual(p["proof"]["revised_rows"], 2)

    def test_unmodified_case_has_no_exception(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "NO_BALANCED_RAW_REVISIONS"):
            plan("Top10Holder", [old], [old])

    def test_stable_evidence_is_reproducible(self):
        a = make_old()
        b = dict(a, type="自然人")
        x = plan("Top10Holder", [a], [b])
        y = plan("Top10Holder", [a], [b])
        self.assertEqual(x, y)
        self.assertRegex(x["preview_sha256"], "^[0-9a-f]{64}$")

    def test_no_leak_of_source_name_in_ordinary_preview(self):
        a = make_old(name="涉及个人姓名甲")
        b = dict(a, declareDate="20261027")
        s = json.dumps(plan("Top10Holder", [a], [b]), ensure_ascii=False)
        self.assertNotIn("涉及个人姓名甲", s)


class NineTableTests(unittest.TestCase):
    def test_one_unrelated_table_can_have_additive_new_records(self):
        old = make_old()
        hist = history("Top10Holder", old)
        cur = fresh("Top10Holder", dict(old, type="自然人"))
        cur["Income"] = [{"_index": "0", "m_timetag": 20260930, "revenue": 100}]
        p = R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             hist, cur, F)
        self.assertEqual(p["unrelated_table_new_source_rows"]["Income"], 1)
        self.assertFalse(p["allow_apply"])

    def test_other_table_lost_record_is_fatal(self):
        old = make_old()
        hist = history("Top10Holder", old)
        hist["Income"] = Counter([R.encode({"m_timetag": 20260331, "revenue": 7}, F)])
        cur = fresh("Top10Holder", dict(old, type="自然人"))
        with self.assertRaisesRegex(R.ReviewBlocked, "OTHER_TABLE_HISTORY_LOSS_Income"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             hist, cur, F)

    def test_missing_current_table_blocks(self):
        old = make_old()
        cur = fresh("Top10Holder", dict(old, type="自然人"))
        del cur["Income"]
        with self.assertRaisesRegex(R.ReviewBlocked, "NINE_TABLE_CURRENT_SCOPE"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             history("Top10Holder", old), cur, F)

    def test_missing_prior_table_blocks(self):
        old = make_old()
        hist = history("Top10Holder", old)
        del hist["Income"]
        with self.assertRaisesRegex(R.ReviewBlocked, "NINE_TABLE_HISTORICAL_SCOPE"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             hist, fresh("Top10Holder", dict(old, type="自然人")), F)

    def test_invalid_current_raw_index_blocks(self):
        old = make_old()
        cur = fresh("Top10Holder", dict(old, type="自然人"))
        del cur["Top10Holder"][0]["_index"]
        with self.assertRaisesRegex(R.ReviewBlocked, "INVALID_CURRENT_RAW_INDEX"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             history("Top10Holder", old), cur, F)

    def test_duplicate_historical_raw_counter_blocks(self):
        old = make_old()
        hist = history("Top10Holder", old)
        hist["Top10Holder"] = Counter({R.encode(old, F): 2})
        with self.assertRaisesRegex(R.ReviewBlocked, "DUPLICATE_OR_MALFORMED"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             hist, fresh("Top10Holder", dict(old, type="自然人")), F)

    def test_invalid_symbol_blocks(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "SYMBOL_INVALID"):
            plan("Top10Holder", [old], [dict(old, type="自然人")], code="../etc")

    def test_invalid_ledger_hash_blocks(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "LEDGER_FINGERPRINT_INVALID"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             history("Top10Holder", old),
                             fresh("Top10Holder", dict(old, type="自然人")),
                             F, ledger_sha256="bad")

    def test_other_table_metadata_scope_cannot_override_capital(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "MODE_TABLE_CONFLICT"):
            plan("Capital", [old], [dict(old, type="自然人")])

    def test_special_stock_cannot_route_to_generic_metadata(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "SPECIAL_CASE_CANNOT"):
            plan("Top10Holder", [old], [dict(old, type="自然人")],
                 code="002178.SZ")

    def test_non_special_cannot_use_issuer_route(self):
        old = make_old()
        with self.assertRaisesRegex(R.ReviewBlocked, "UNSCOPED_SPECIAL"):
            plan("Top10Holder", [old], [dict(old, type="自然人")],
                 mode="ISSUER_DISPUTED")


class CapitalTests(unittest.TestCase):
    def test_one_additive_report_preserves_old_economic_versions(self):
        old = [capital(20250630, 0), capital(20250630, 1)]
        new = [capital(20250630, 1), capital(20250930, 2)]
        p = plan("Capital", old, new, mode="CAPITAL_ADDITIVE", code="002188.SZ")
        self.assertEqual(p["classification"], "CAPITAL_ADDITIVE_REVIEW_REQUIRED")
        self.assertEqual(p["proof"]["historical_raw_variants_retained"], 2)
        self.assertEqual(p["proof"]["old_report_keys"], 1)
        self.assertEqual(p["proof"]["current_report_keys"], 2)
        self.assertEqual(p["proof"]["added_report_keys"], ["20250930"])
        self.assertEqual(p["proof"]["removed_report_keys"], 0)
        self.assertFalse(p["allow_apply"])

    def test_old_capital_key_removed_blocks(self):
        a, b = capital(20250331, 1), capital(20250630, 2)
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_HISTORICAL_REPORT_KEY_REMOVED"):
            plan("Capital", [a, b], [b, capital(20250930, 3)],
                 mode="CAPITAL_ADDITIVE", code="002188.SZ")

    def test_capital_business_revision_blocks(self):
        a = capital(20250630, 1)
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_HISTORIC_ECONOMIC"):
            plan("Capital", [a], [capital(20250630, 1, 101), capital(20250930, 2)],
                 mode="CAPITAL_ADDITIVE", code="002188.SZ")

    def test_capital_two_historical_economic_variants_block(self):
        a = capital(20250630, 1)
        b = dict(a, total_capital=105, m_quarter=2)
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_HISTORIC_ECONOMIC"):
            plan("Capital", [a, b], [a, capital(20250930, 3)],
                 mode="CAPITAL_ADDITIVE", code="002188.SZ")

    def test_capital_duplicate_current_report_key_blocks(self):
        a = capital(20250630, 1)
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_DUPLICATE_CURRENT_REPORT_KEY"):
            plan("Capital", [a], [a, capital(20250630, 2), capital(20250930, 3)],
                 mode="CAPITAL_ADDITIVE", code="002188.SZ")

    def test_capital_without_new_report_blocks(self):
        a = capital(20250630, 1)
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_EXPECT_EXACTLY_ONE_ADDED"):
            plan("Capital", [a], [a], mode="CAPITAL_ADDITIVE", code="002188.SZ")

    def test_capital_two_new_reports_block(self):
        a = capital(20250630, 1)
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_EXPECT_EXACTLY_ONE_ADDED"):
            plan("Capital", [a], [a, capital(20250930, 3), capital(20251231, 4)],
                 mode="CAPITAL_ADDITIVE", code="002188.SZ")

    def test_capital_unkeyed_row_blocks(self):
        a = capital(20250630, 1)
        del a["m_timetag"]
        with self.assertRaisesRegex(R.ReviewBlocked, "CAPITAL_KEY_OR_QUARTER_MISSING"):
            plan("Capital", [a], [capital(20250630, 1)], mode="CAPITAL_ADDITIVE",
                 code="002188.SZ")


class IssuerTests(unittest.TestCase):
    def _evidence(self, code, table, old, new, stable):
        fields = {
            "002178.SZ": ["name", "type"],
            "002310.SZ": ["name"],
            "002328.SZ": ["declareDate", "shareholder", "shareholderA"],
        }[code]
        return {
            "format": "astock_finance_source_disclosure_proof_v1",
            "allow_auto_clear": False,
            "default_action": "HOLD_PENDING_NO_COMMIT",
            "cases": [{
                "symbol": code, "table": table, "endDate": "20260930",
                "manual_approval_required": True, "pairing_unambiguous": True,
                "changed_fields": fields,
                "prior_record_sha256": R.digest(R.encode(old, F)),
                "current_record_sha256": R.digest(R.encode(new, F)),
                "stable_projection_sha256": R.digest(
                    R._projection(old, frozenset(fields), F)),
                "issuer_source": "https://example.org/issuer.pdf",
                "issuer_confirmation": "REVIEW_REQUIRED",
            }],
        }

    def test_002178_pinned_name_and_type_remain_review_only(self):
        old = make_old()
        new = dict(old, name="乙", type="机构投资账户")
        ev = self._evidence("002178.SZ", "Top10Holder", old, new, "")
        p = plan("Top10Holder", [old], [new], mode="ISSUER_DISPUTED",
                 code="002178.SZ", evidence=ev)
        self.assertEqual(p["classification"], "ISSUER_DISPUTED_REVIEW_REQUIRED")
        self.assertTrue(p["proof"]["disclosure"]["manual_approval_required"])
        self.assertFalse(p["allow_apply"])

    def test_002310_pinned_name_spelling_review_only(self):
        old = make_old()
        new = dict(old, name="乙")
        ev = self._evidence("002310.SZ", "Top10Holder", old, new, "")
        p = plan("Top10Holder", [old], [new], mode="ISSUER_DISPUTED",
                 code="002310.SZ", evidence=ev)
        self.assertEqual(p["proof"]["revised_rows"], 1)

    def test_002328_conflicted_count_still_review_only(self):
        old = {"endDate": "20260930", "declareDate": "20261029",
               "shareholder": 57896, "shareholderA": 57896}
        new = dict(old, declareDate="20261012",
                   shareholder=57900, shareholderA=57900)
        ev = self._evidence("002328.SZ", "HolderNum", old, new, "")
        p = plan("HolderNum", [old], [new], mode="ISSUER_DISPUTED",
                 code="002328.SZ", evidence=ev)
        self.assertEqual(p["classification"], "ISSUER_DISPUTED_REVIEW_REQUIRED")
        self.assertFalse(p["allow_auto_clear"])

    def test_issuer_manifest_fingerprint_change_blocks(self):
        old = make_old()
        new = dict(old, name="乙")
        ev = self._evidence("002310.SZ", "Top10Holder", old, new, "")
        ev["cases"][0]["current_record_sha256"] = "0" * 64
        with self.assertRaisesRegex(R.ReviewBlocked, "SPECIAL_RECORD_FINGERPRINT_CHANGED"):
            plan("Top10Holder", [old], [new], mode="ISSUER_DISPUTED",
                 code="002310.SZ", evidence=ev)

    def test_unreviewed_issuer_case_status_blocks(self):
        old = make_old()
        new = dict(old, name="乙")
        ev = self._evidence("002310.SZ", "Top10Holder", old, new, "")
        ev["allow_auto_clear"] = True
        with self.assertRaisesRegex(R.ReviewBlocked, "SPECIAL_EVIDENCE_MANIFEST_INVALID"):
            plan("Top10Holder", [old], [new], mode="ISSUER_DISPUTED",
                 code="002310.SZ", evidence=ev)

    def test_issuer_pinned_report_period_mismatch_blocks(self):
        old = make_old(end="20260331")
        new = dict(old, name="乙")
        ev = self._evidence("002310.SZ", "Top10Holder", old, new, "")
        with self.assertRaisesRegex(R.ReviewBlocked, "SPECIAL_REPORT_PERIOD_CHANGED"):
            plan("Top10Holder", [old], [new], mode="ISSUER_DISPUTED",
                 code="002310.SZ", evidence=ev)

    def test_issuer_wrong_table_blocks(self):
        old = make_old()
        new = dict(old, name="乙")
        ev = self._evidence("002310.SZ", "Top10Holder", old, new, "")
        with self.assertRaisesRegex(R.ReviewBlocked, "SPECIAL_CASE_TABLE_CHANGED"):
            plan("Top10FlowHolder", [old], [new], mode="ISSUER_DISPUTED",
                 code="002310.SZ", evidence=ev)


if __name__ == "__main__":
    unittest.main()
