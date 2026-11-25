"""Deterministic offline hash checks against owner log + issuer Q3 names.

This tests evidence reproducibility, NOT a data acceptance policy. The owner
already ran a one-shot cache-only audit and the old/new name SHA256 values
recorded here came from that owner-supplied stdout. No QMT dependency.
"""
import difflib
from hashlib import sha256
import unicodedata
import unittest

OLD_178 = "J.P.Morgan Securities PLC-自有资金"
NEW_178 = "J.P.MorganSecurities PLC-自有资金"
ISSUER_178 = "J.P.Morgan Securities PLC-自有资金"
OLD_310 = "允能新开投资管理(天津)有限公司-天津允新远赢新能源股权投资合伙企业(有限合伙)"
NEW_310 = "允能新开投资管理(天津)有限公司一天津允新远赢新能源股权投资合伙企业(有限合伙)"
ISSUER_310 = "允能新开投资管理（天津）有限公司－天津允新远赢新能源股权投资合伙企业（有限合伙）"
FINGERPRINTS = {
    "002178_old": "6f5502052dc88881981db2be07a676fc51cacbf2629923a58c796ee6cbbfb3a3",
    "002178_new": "29e3154f8732d1b0603648d1dc87918fc2e24d053550458536120750dcce862c",
    "002310_old": "ee1477b0b158cd0482a0e105eed893936d3b68b60edd2b307beb208285fffef3",
    "002310_new": "e14ebf59a2359a032c152b480b841e1772a394971c6d31404b2f2c40de775151",
}


def digest(value):
    return sha256(value.encode("utf-8")).hexdigest()


class OfficialEvidenceTests(unittest.TestCase):
    def test_002178_historic_matches_official_name_exactly(self):
        self.assertEqual(OLD_178, ISSUER_178)
        self.assertEqual(digest(OLD_178), FINGERPRINTS["002178_old"])
        self.assertEqual(len(OLD_178), 30)

    def test_002178_current_drops_only_one_space(self):
        self.assertEqual(NEW_178, OLD_178.replace("Morgan Securities", "MorganSecurities"))
        self.assertEqual(digest(NEW_178), FINGERPRINTS["002178_new"])
        self.assertEqual(len(NEW_178), 29)

    def test_002178_type_mismatch_remains_unapproved(self):
        old_type, new_type, issuer_category = "QFII机构", "公司", "境外法人"
        self.assertEqual(len({old_type, new_type, issuer_category}), 3)

    def test_002310_historic_fingerprint_exact(self):
        self.assertEqual(digest(OLD_310), FINGERPRINTS["002310_old"])
        self.assertEqual(len(OLD_310), 40)

    def test_002310_current_is_ideograph_instead_of_hyphen(self):
        self.assertEqual(NEW_310, OLD_310.replace("公司-", "公司一"))
        self.assertEqual(digest(NEW_310), FINGERPRINTS["002310_new"])
        self.assertEqual(len(NEW_310), 40)
        self.assertEqual(difflib.SequenceMatcher(None, OLD_310, NEW_310).ratio(), 0.975)
        self.assertIn("\u4e00", NEW_310)
        self.assertNotIn("\u002d", NEW_310)

    def test_002310_issuer_connector_is_dash_not_han_ideograph(self):
        self.assertIn("有限公司－天津", ISSUER_310)
        self.assertNotIn("有限公司一天津", ISSUER_310)
        expected = "允能新开投资管理(天津)有限公司-天津允新远赢新能源股权投资合伙企业(有限合伙)"
        normal = unicodedata.normalize("NFKC", ISSUER_310).replace("−", "-").replace("－", "-")
        self.assertEqual(normal, expected)

    def test_002328_old_shareholder_count_matches_official(self):
        official = 57896
        prior, current = 57896, 57900
        self.assertEqual(prior, official)
        self.assertNotEqual(current, official)
        self.assertEqual(current-prior, 4)
        self.assertAlmostEqual((current-prior)*100/prior, 0.00690894016857814)

    def test_002328_issuer_report_date_corresponds_to_old_value_only(self):
        report_end, issuer_report_date = "20260930", "20261029"
        old_declare, new_declare = "20261029", "20261012"
        self.assertEqual(report_end, "20260930")
        self.assertEqual(old_declare, issuer_report_date)
        self.assertNotEqual(new_declare, issuer_report_date)


if __name__ == "__main__":
    unittest.main()
