"""No-QMT, no-Parquet, no-write regression for exact Capital m_quarter variants."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import unittest

src = Path(__file__).resolve().parent.parent / "qmt_finance_versioned_recovery_preview.py"
spec = importlib.util.spec_from_file_location("capital_compat_preview", src)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


class E:
    FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital",
                  "Top10FlowHolder", "Top10Holder", "HolderNum",
                  "PershareIndex", "PerShare")

    @staticmethod
    def canonical_json(x):
        return json.dumps(x, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class F:
    E = E


def financial(key, quarter, total=100):
    return {"m_timetag": key, "m_quarter": quarter, "total_capital": total}


def holder(name, date="20261022", amount=100):
    return {"endDate": "20260930", "declareDate": date,
            "name": name, "shares": amount, "type": "公司"}


def history(table, *rows):
    old = {name: Counter() for name in E.FIN_TABLES}
    old[table] = Counter(R.encode(row, F) for row in rows)
    return old


def current(table, *rows):
    new = {name: [] for name in E.FIN_TABLES}
    new[table] = [dict(row, _index=str(i)) for i, row in enumerate(rows)]
    return new


def setup_with_capital(old_cap, new_cap, *, code="002388.SZ",
                       table="Top10FlowHolder", mode="HOLDER_METADATA"):
    a = holder("Holder", "20261022")
    b = dict(a, declareDate="20261027")
    previous = history(table, a)
    fresh = current(table, b)
    previous["Capital"] = Counter(R.encode(row, F) for row in old_cap)
    fresh["Capital"] = [dict(row, _index=str(i)) for i, row in enumerate(new_cap)]
    return R.preview_symbol(code, mode, table, previous, fresh, F,
                            ledger_sha256="a" * 64)


class CapitalQuarterCompatTests(unittest.TestCase):
    def test_unique_historical_quarter_variant_produces_review_only(self):
        old = [financial("20260331", 1.0), financial("20260331", 2.0)]
        new = [financial("20260331", 2.0)]
        p = setup_with_capital(old, new)
        cross = p["cross_table_capital_quarter_proof"]
        self.assertEqual(p["classification"], "HOLDER_METADATA_REVIEW_REQUIRED")
        self.assertEqual(cross["historical_report_keys"], 1)
        self.assertEqual(cross["historical_raw_variants_extra"], 1)
        self.assertEqual(cross["raw_mismatch_report_keys"], 1)
        self.assertEqual(cross["report_keys_removed"], 0)
        self.assertEqual(cross["report_keys_added"], 0)
        self.assertTrue(cross["preserve_original_raw_snapshots"])
        self.assertFalse(p["allow_apply"])
        self.assertFalse(p["allow_auto_clear"])
        self.assertFalse(p["pending_state_changed"])
        self.assertFalse(p["snapshot_state_changed"])

    def test_cross_table_capital_single_mquarter_revision_review_only(self):
        old = [financial("20260331", 1.0)]
        new = [financial("20260331", 3.0)]
        p = setup_with_capital(old, new)
        self.assertEqual(p["cross_table_capital_quarter_proof"]["raw_mismatch_report_keys"], 1)

    def test_matching_capital_reports_no_quarter_changes(self):
        old = [financial("20260331", 1.0)]
        p = setup_with_capital(old, old)
        self.assertEqual(p["cross_table_capital_quarter_proof"]["raw_mismatch_report_keys"], 0)

    def test_changed_capital_economic_field_blocks(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_ECONOMIC_FIELD_CHANGED"):
            setup_with_capital([financial("20260331", 1.0)],
                               [financial("20260331", 2.0, 101)])

    def test_historical_economic_contradiction_blocks(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_HISTORICAL_ECONOMIC_CONFLICT"):
            setup_with_capital([financial("20260331", 1.0), financial("20260331", 2.0, 101)],
                               [financial("20260331", 2.0)])

    def test_missing_old_report_key_blocks(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_REPORT_KEYS_CHANGED"):
            setup_with_capital([financial("20260331", 1.0),
                                financial("20260630", 2.0)],
                               [financial("20260630", 2.0)])

    def test_unapproved_new_report_key_in_other_table_blocks(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_REPORT_KEYS_CHANGED"):
            setup_with_capital([financial("20260331", 1.0)],
                               [financial("20260331", 1.0), financial("20260630", 2.0)])

    def test_duplicate_current_capital_report_key_blocks(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_CURRENT_DUPLICATE_KEY"):
            setup_with_capital([financial("20260331", 1.0)],
                               [financial("20260331", 1.0), financial("20260331", 2.0)])

    def test_missing_quarter_field_blocks(self):
        x = financial("20260331", 1.0)
        del x["m_quarter"]
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_KEY_OR_QUARTER_MALFORMED"):
            setup_with_capital([x], [financial("20260331", 1.0)])

    def test_invalid_report_key_blocks(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "CROSS_CAPITAL_KEY_OR_QUARTER_MALFORMED"):
            setup_with_capital([financial("20260331", 1.0)], [financial(0, 1.0)])

    def test_exact_duplicate_raw_historical_capital_still_blocks(self):
        same = financial("20260331", 1.0)
        with self.assertRaisesRegex(R.ReviewBlocked, "HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY"):
            setup_with_capital([same, same], [same])

    def test_duplicate_raw_history_other_table_still_blocks(self):
        old = financial("20260331", 1.0)
        a = holder("A")
        b = dict(a, declareDate="20261027")
        historical = history("Top10Holder", a)
        historical["Income"] = Counter({R.encode({"amount": 10}, F): 2})
        historical["Capital"] = Counter({R.encode(old, F): 1})
        current_source = current("Top10Holder", b)
        current_source["Capital"] = [dict(old, _index="0")]
        with self.assertRaisesRegex(R.ReviewBlocked, "HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10Holder",
                             historical, current_source, F)

    def test_other_table_real_raw_loss_remains_blocked(self):
        old = financial("20260331", 1.0)
        previous = history("Top10FlowHolder", holder("A"))
        previous["Income"] = Counter({R.encode({"sales": 77}, F): 1})
        previous["Capital"] = Counter({R.encode(old, F): 1})
        fresh = current("Top10FlowHolder", dict(holder("A"), declareDate="20261027"))
        fresh["Capital"] = [dict(old, _index="0")]
        with self.assertRaisesRegex(R.ReviewBlocked, "OTHER_TABLE_HISTORY_LOSS_Income"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "Top10FlowHolder",
                             previous, fresh, F)

    def test_numeric_shareholder_change_not_admitted_as_metadata(self):
        old = financial("20260331", 1.0)
        a = {"endDate": "20260930", "declareDate": "20261022", "shareholder": 100}
        b = dict(a, shareholder=101)
        previous = history("HolderNum", a)
        previous["Capital"] = Counter({R.encode(old, F): 1})
        fresh = current("HolderNum", b)
        fresh["Capital"] = [dict(old, _index="0")]
        with self.assertRaisesRegex(R.ReviewBlocked, "REPORT_OR_BUSINESS_PROJECTION_CHANGED"):
            R.preview_symbol("002388.SZ", "HOLDER_METADATA", "HolderNum", previous, fresh, F)

    def test_known_688259_utf8_error_never_gets_preview(self):
        with self.assertRaisesRegex(R.ReviewBlocked, "KNOWN_PROVIDER_UTF8_QUARANTINE"):
            setup_with_capital([], [], code="688259.SH")

    def test_capital_target_additive_rule_unchanged(self):
        old = financial("20260331", 1.0)
        p = R.preview_symbol(
            "002188.SZ", "CAPITAL_ADDITIVE", "Capital",
            history("Capital", old),
            current("Capital", financial("20260331", 2.0),
                    financial("20261119", 3.0)), F)
        self.assertEqual(p["classification"], "CAPITAL_ADDITIVE_REVIEW_REQUIRED")
        self.assertIsNone(p["cross_table_capital_quarter_proof"])
        self.assertFalse(p["allow_apply"])


if __name__ == "__main__":
    unittest.main()
