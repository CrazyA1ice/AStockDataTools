"""P9 002310 issuer Unicode and 002328 approximate/exact vintage HOLD tests."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import finance_five_review_freeze_once as G
import finance_five_adjudication_dossier_once as P7
import finance_public_source_crosscheck_once as P8
import finance_disclosure_vintage_provenance_once as P9

DOCS = BASE / "docs"
FILES = list(dict.fromkeys([
    *P7.FREEZE_INPUT_NAMES.values(), P7.DOSSIER_FILE,
    "finance-public-source-crosscheck-20261125.json", P9.DOC_FILENAME,
]))


def evidence():
    prior = {
        key: G.load_json(DOCS / fname)
        for key, fname in P7.FREEZE_INPUT_NAMES.items()
    }
    freeze = G.validate(**prior)
    p7 = P7.validate(G.load_json(DOCS / P7.DOSSIER_FILE), freeze)
    p8 = P8.validate(
        G.load_json(DOCS / "finance-public-source-crosscheck-20261125.json"), p7)
    return G.load_json(DOCS / P9.DOC_FILENAME), p8


def stock(data, code):
    return next(x for x in data["cases"] if x["symbol"] == code)


def reject(change, code):
    doc, p8 = evidence()
    change(doc, p8)
    with unittest.TestCase().assertRaisesRegex(ValueError, code):
        P9.validate(doc, p8)


class VintagePositiveTests(unittest.TestCase):
    def test_p8_owner_receipt_pinned(self):
        _, p8 = evidence()
        self.assertEqual(p8["packet_sha256"], P9.P8_PACKET_SHA)

    def test_p9_five_holds_two_focus(self):
        doc, p8 = evidence()
        receipt = P9.validate(doc, p8)
        self.assertEqual(receipt["five_cases"], 5)
        self.assertEqual(receipt["focused_cases"], 2)
        self.assertEqual(receipt["approved"], 0)
        self.assertFalse(receipt["can_apply"])
        self.assertFalse(receipt["can_clear_pending"])
        self.assertFalse(receipt["qmt_ingestion_lineage_proven"])

    def test_qmt_early_approximate_late_exact_declared_dates(self):
        doc, _ = evidence()
        f = stock(doc, "002328.SZ")["focused_evidence"]
        self.assertEqual(f["current_qmt_declareDate"], "20261012")
        self.assertEqual(f["historical_qmt_declareDate"], "20261029")
        self.assertEqual(f["current_qmt_shareholder"], 57900)
        self.assertEqual(f["historical_qmt_shareholder"], 57896)
        self.assertEqual(f["reported_numerical_difference"], 4)

    def test_early_value_is_approximate_not_exact(self):
        doc, _ = evidence()
        f = stock(doc, "002328.SZ")["focused_evidence"]
        self.assertEqual(f["early_approximate_shareholder_reported"], "约57900户")
        self.assertFalse(f["early_value_exact_source_count_proven"])
        self.assertFalse(f["authenticated_original_interaction_record_verified"])

    def test_issuer_57896_primary_pdf(self):
        doc, _ = evidence()
        f = stock(doc, "002328.SZ")["focused_evidence"]
        self.assertEqual(f["issuer_report_shareholder_exact"], 57896)
        self.assertEqual(f["issuer_report_date"], "2026-10-29")
        self.assertTrue(f["issuer_original_document_url"].startswith(
            "https://static.cninfo.com.cn/"))
        self.assertEqual(f["issuer_report_page_one_based"], 4)

    def test_not_proven_qmt_ingest_lineage(self):
        doc, _ = evidence()
        f = stock(doc, "002328.SZ")["focused_evidence"]
        self.assertFalse(f["provider_qmt_source_lineage_proven"])
        self.assertFalse(f["historical_qmt_exact_cas_verified_now"])
        self.assertFalse(f["automatic_rounding_explanation_allowed"])

    def test_qmt_shareholder_and_shareholderA_dictionary_distinct(self):
        doc, _ = evidence()
        f = stock(doc, "002328.SZ")["focused_evidence"]
        self.assertEqual(f["qmt_shareholder_field_label"], "股东总数")
        self.assertEqual(f["qmt_shareholderA_field_label"], "A股东户数")

    def test_002310_issuer_separator_is_fullwidth_hyphen(self):
        doc, _ = evidence()
        f = stock(doc, "002310.SZ")["focused_evidence"]
        self.assertEqual(f["issuer_sample_separator"], "－")
        self.assertEqual(ord(f["issuer_sample_separator"]), 0xFF0D)
        self.assertEqual(f["issuer_sample_separator_codepoint"], "U+FF0D")
        self.assertIn("－", f["issuer_sample_name"])

    def test_002310_disputed_row_not_identified(self):
        doc, _ = evidence()
        f = stock(doc, "002310.SZ")["focused_evidence"]
        self.assertFalse(f["sample_row_equals_disputed_hashed_qmt_row"])
        self.assertFalse(f["allowed_to_normalize_holder_names"])
        self.assertEqual(f["qmt_diff_old_codepoint"], "U+002D")
        self.assertEqual(f["qmt_diff_current_codepoint"], "U+4E00")

    def test_prior_name_sha256_still_pinned(self):
        doc, _ = evidence()
        f = stock(doc, "002310.SZ")["focused_evidence"]
        self.assertEqual(f["qmt_old_name_sha256"],
                         "ee1477b0b158cd0482a0e105eed893936d3b68b60edd2b307beb208285fffef3")
        self.assertEqual(f["qmt_current_name_sha256"],
                         "e14ebf59a2359a032c152b480b841e1772a394971c6d31404b2f2c40de775151")

    def test_three_other_cases_remain_historical_holds(self):
        doc, _ = evidence()
        for code in ("002178.SZ", "002188.SZ", "002388.SZ"):
            self.assertEqual(stock(doc, code)["decision"], "HOLD_PENDING")
            self.assertEqual(stock(doc, code)["new_evidence"], "NO_CHANGE_FROM_P8")

    def test_report_deterministic_and_immutable(self):
        doc, p8 = evidence()
        self.assertEqual(P9.validate(doc, p8),
                         P9.validate(deepcopy(doc), deepcopy(p8)))

    def test_output_does_not_claim_current_source_refresh(self):
        doc, p8 = evidence()
        packet = P9.validate(doc, p8)
        self.assertFalse(packet["external_sources_currently_refetched"])
        self.assertTrue(packet["historical_only"])
        self.assertEqual(packet["issuer_002310_codepoint"], "U+FF0D")


class VintageFailClosedTests(unittest.TestCase):
    def test_p8_packet_changed(self):
        reject(lambda d, p: p.update({"packet_sha256": "0"*64}),
               "PR253_P8_PACKET_CHANGED")

    def test_p8_approval_fabricated(self):
        reject(lambda d, p: p.update({"human_approved": 1}),
               "PR253_P8_HOLD_STATE_CHANGED")

    def test_p9_claims_one_approval(self):
        reject(lambda d, p: d.update({"approved_count": 1}),
               "P9_APPROVAL_COUNT_CHANGED")

    def test_p9_apply_enabled(self):
        reject(lambda d, p: d.update({"allow_apply": True}),
               "P9_FORBIDDEN_FLAG_allow_apply")

    def test_p9_pending_clear_enabled(self):
        reject(lambda d, p: d.update({"allow_pending_clear": True}),
               "P9_FORBIDDEN_FLAG_allow_pending_clear")

    def test_p9_dedup_enabled(self):
        reject(lambda d, p: d.update({"allow_deduplication": True}),
               "P9_FORBIDDEN_FLAG_allow_deduplication")

    def test_p9_live_state_claimed_verified(self):
        reject(lambda d, p: d.update({"live_source_or_ledger_revalidated": True}),
               "P9_FORBIDDEN_FLAG_live_source_or_ledger_revalidated")

    def test_new_approval_field_injected(self):
        reject(lambda d, p: d.update({"human_signature": "approved"}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002328_57900_rounded_as_exact_wrong(self):
        reject(lambda d, p: stock(d, "002328.SZ")["focused_evidence"]
               .update({"early_value_exact_source_count_proven": True}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002328_provider_lineage_not_inferred(self):
        reject(lambda d, p: stock(d, "002328.SZ")["focused_evidence"]
               .update({"provider_qmt_source_lineage_proven": True}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002328_may_not_auto_round(self):
        reject(lambda d, p: stock(d, "002328.SZ")["focused_evidence"]
               .update({"automatic_rounding_explanation_allowed": True}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002328_early_and_later_count_reversal_refused(self):
        reject(lambda d, p: stock(d, "002328.SZ")["focused_evidence"]
               .update({"current_qmt_shareholder": 57896}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002328_approx_removed_refused(self):
        reject(lambda d, p: stock(d, "002328.SZ")["focused_evidence"]
               .update({"early_approximate_shareholder_reported": "57900户"}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002310_issuer_fullwidth_downgraded_to_ascii_refused(self):
        reject(lambda d, p: stock(d, "002310.SZ")["focused_evidence"]
               .update({"issuer_sample_separator": "-"}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002310_issuer_connector_wrong_codepoint_refused(self):
        reject(lambda d, p: stock(d, "002310.SZ")["focused_evidence"]
               .update({"issuer_sample_separator_codepoint": "U+002D"}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002310_target_holder_falsely_matched(self):
        reject(lambda d, p: stock(d, "002310.SZ")["focused_evidence"]
               .update({"sample_row_equals_disputed_hashed_qmt_row": True}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_002310_global_name_normalization_not_allowed(self):
        reject(lambda d, p: stock(d, "002310.SZ")["focused_evidence"]
               .update({"allowed_to_normalize_holder_names": True}),
               "P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")

    def test_unapproved_case_decision_changed(self):
        reject(lambda d, p: stock(d, "002388.SZ")
               .update({"decision": "APPROVED"}),
               "P9_CASE_NOT_HELD_002388")

    def test_missing_case_blocks(self):
        reject(lambda d, p: d["cases"].pop(), "P9_FIVE_CASES_MISSING")

    def test_reordered_case_blocks(self):
        reject(lambda d, p: d["cases"].reverse(),
               "P9_CASE_ORDER_OR_IDENTITY_CHANGED")

    def test_wrong_p8_source_packet_ref_blocks(self):
        reject(lambda d, p: d.update({"source_p8_packet_sha256": "f"*64}),
               "P9_PRIOR_PACKET_REF_CHANGED")


class CliTests(unittest.TestCase):
    def test_all_five_receipts_are_hold_only(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report = P9.run(DOCS)
        lines = buffer.getvalue().splitlines()
        self.assertEqual(sum(x.startswith("FINANCE_VINTAGE_PROVENANCE_HOLD=")
                             for x in lines), 5)
        self.assertEqual(lines[-1],
                         "FINANCE_VINTAGE_PROVENANCE_COMPLETE_NO_APPROVAL_NO_APPLY")
        self.assertEqual(report["approved"], 0)

    def test_tampered_issuer_manifest_no_success_output(self):
        with tempfile.TemporaryDirectory() as td:
            for filename in FILES:
                shutil.copyfile(DOCS / filename, Path(td) / filename)
            path = Path(td) / P7.FREEZE_INPUT_NAMES["issuer"]
            source = json.loads(path.read_text(encoding="utf-8"))
            next(x for x in source["cases"] if x["symbol"] == "002328.SZ")[
                "current"]["shareholder"] = 57896
            path.write_text(json.dumps(source), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(ValueError):
                    P9.run(td)
            self.assertEqual(buf.getvalue(), "")

    def test_missing_source_files_no_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(ValueError):
                    P9.run(td)
            self.assertEqual(buf.getvalue(), "")

    def test_no_source_files_changed(self):
        before = {x: (DOCS / x).read_bytes() for x in FILES}
        with redirect_stdout(io.StringIO()):
            P9.run(DOCS)
        after = {x: (DOCS / x).read_bytes() for x in FILES}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
