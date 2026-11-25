"""Synthetic P7 five-stock case-adjudication HOLD-only proof, no QMT/Parquet."""
from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import finance_five_review_freeze_once as G

spec = importlib.util.spec_from_file_location(
    "finance_five_adjudication_dossier_once",
    BASE / "finance_five_adjudication_dossier_once.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
DOCS = BASE / "docs"


def inputs():
    originals = {key: G.load_json(DOCS / name)
                 for key, name in P.FREEZE_INPUT_NAMES.items()}
    return G.load_json(DOCS / P.DOSSIER_FILE), G.validate(**originals)


def case(doc, symbol):
    return next(c for c in doc["cases"] if c["symbol"] == symbol)


def gap(doc, symbol, code):
    return next(q for q in case(doc, symbol)["review_gaps"]
                if q["code"] == code)


def rejection(mutate, message):
    source, frozen = inputs()
    mutate(source, frozen)
    with unittest.TestCase().assertRaisesRegex(ValueError, message):
        P.validate(source, frozen)


class DossierPositiveTests(unittest.TestCase):
    def test_p7_5_hold_7_unresolved_and_no_approval(self):
        d, prior = inputs()
        receipt = P.validate(d, prior)
        self.assertEqual(receipt["total_cases"], 5)
        self.assertEqual(receipt["unresolved_gap_count"], 7)
        self.assertEqual(receipt["human_approved"], 0)
        self.assertFalse(receipt["eligible_to_apply"])
        self.assertFalse(receipt["eligible_to_clear_pending"])
        self.assertFalse(receipt["can_deduplicate"])

    def test_prior_p6_fingerprint_exact(self):
        _, prior = inputs()
        self.assertEqual(prior["packet_sha256"], P.SOURCE_PACKET_SHA)
        self.assertEqual(prior["packet_sha256"],
                         "5cc5aca739e19b9426ae2fc1fa398e5b9c11af5fc8a0344d0be8abfa58988dc3")

    def test_output_hash_reproducible(self):
        a, b = inputs()
        self.assertEqual(P.validate(a, b), P.validate(deepcopy(a), deepcopy(b)))

    def test_cases_match_original_five_preview_hashes(self):
        dossier, prior = inputs()
        p = P.validate(dossier, prior)
        for row in p["cases"]:
            self.assertEqual(row["source_preview_sha256"],
                             G.CASES[row["symbol"]][2])
            self.assertEqual(row["human_decision"], "HOLD_PENDING")

    def test_002178_requires_name_and_type_sources(self):
        d, _ = inputs()
        self.assertEqual(gap(d, "002178.SZ",
                             "NAME_SPACING_AND_TYPE_TAXONOMY_UNRESOLVED")
                         ["independent_evidence_required"],
                         list(P.NEEDED["NAME_SPACING_AND_TYPE_TAXONOMY_UNRESOLVED"]))

    def test_002188_exposes_two_unresolved_gaps_not_dedup(self):
        d, prior = inputs()
        c = case(d, "002188.SZ")
        self.assertEqual(len(c["review_gaps"]), 2)
        self.assertFalse(c["allow_deduplication"])
        self.assertIn("NINE_RAW_SHA256_COUNT_TWO_ORIGIN",
                      c["review_gaps"][0]["independent_evidence_required"])
        self.assertFalse(P.validate(d, prior)["eligible_to_apply"])

    def test_002310_requires_hyphen_and_han_one_evidence(self):
        d, _ = inputs()
        required = gap(d, "002310.SZ", "NAME_PUNCTUATION_ISSUER_SOURCE_DISPUTE")[
            "independent_evidence_required"]
        self.assertIn("ISSUER_ASCII_HYPHEN_SOURCE_EVIDENCE", required)
        self.assertIn("QMT_HAN_ONE_SOURCE_EVIDENCE", required)

    def test_002328_requires_numeric_and_shareholderA_semantics(self):
        d, _ = inputs()
        self.assertEqual(len(case(d, "002328.SZ")["review_gaps"]), 2)
        self.assertIn("FOUR_COUNT_DIFFERENCE_EXPLANATION_AND_ADJUDICATION",
                      gap(d, "002328.SZ",
                          "ISSUER_57896_VS_PROVIDER_57900_NUMERIC_CONFLICT")[
                              "independent_evidence_required"])

    def test_002388_metadata_source_proofs_are_pending(self):
        d, _ = inputs()
        questions = case(d, "002388.SZ")["review_gaps"]
        self.assertEqual(len(questions), 1)
        self.assertIn("CROSS_CAPITAL_MQUARTER_HISTORY_PRESERVATION",
                      questions[0]["independent_evidence_required"])
        self.assertFalse(questions[0]["gap_resolved"])

    def test_no_person_names_or_raw_shareholder_rows_in_output(self):
        d, old = inputs()
        report = G.canonical(P.validate(d, old))
        self.assertNotIn("MORGAN", report)
        self.assertNotIn('"name":', report)
        self.assertNotIn('"shareholder":', report)
        self.assertNotIn('"approved":true', report)

    def test_case_source_docs_are_independent_and_exact(self):
        d, old = inputs()
        P.validate(d, old)
        self.assertEqual(case(d, "002188.SZ")["source_document_names"],
                         list(P.SOURCE_NAMES["002188.SZ"]))
        self.assertEqual(case(d, "002328.SZ")["source_document_names"],
                         list(P.SOURCE_NAMES["002328.SZ"]))


class FailClosedDossierTests(unittest.TestCase):
    def test_approval_count_changed(self):
        rejection(lambda d, p: d.update({"manual_approval_count": 1}),
                  "DOSSIER_SCOPE_OR_HOLD_POLICY_CHANGED")

    def test_live_state_marked_verified(self):
        rejection(lambda d, p: d.update({"live_state_reverified": True}),
                  "DOSSIER_FLAG_live_state_reverified")

    def test_auto_writer_flag(self):
        rejection(lambda d, p: d.update({"may_trigger_live_write": True}),
                  "DOSSIER_FLAG_may_trigger_live_write")

    def test_auto_clear_flag(self):
        rejection(lambda d, p: d.update({"may_clear_pending": True}),
                  "DOSSIER_FLAG_may_clear_pending")

    def test_dedup_flag(self):
        rejection(lambda d, p: d.update({"may_deduplicate": True}),
                  "DOSSIER_FLAG_may_deduplicate")

    def test_approval_record_support_flag(self):
        rejection(lambda d, p: d.update({"approval_records_supported": True}),
                  "DOSSIER_FLAG_approval_records_supported")

    def test_root_extra_approval_field(self):
        rejection(lambda d, p: d.update({"signed": True}),
                  "DOSSIER_TOP_LEVEL_FIELDS_CHANGED")

    def test_bad_packet_digest(self):
        rejection(lambda d, p: d.update({"source_pr251_packet_sha256": "a"*64}),
                  "DOSSIER_SCOPE_OR_HOLD_POLICY_CHANGED")

    def test_frozen_packet_digest_drift(self):
        rejection(lambda d, p: p.update({"packet_sha256": "a"*64}),
                  "PR251_FROZEN_PACKET_SHA_CHANGED")

    def test_frozen_packet_claims_approval(self):
        rejection(lambda d, p: p.update({"human_approved": 1}),
                  "PR251_INELIGIBLE_HISTORICAL_PACKET_CHANGED")

    def test_frozen_packet_no_longer_hold(self):
        def change(d, p):
            p["cases"][0]["decision"] = "APPROVED"
        rejection(change, "PR251_FROZEN_HOLD_CASES_CHANGED")

    def test_frozen_packet_eligible_to_apply(self):
        rejection(lambda d, p: p.update({"eligible_to_apply": True}),
                  "PR251_INELIGIBLE_HISTORICAL_PACKET_CHANGED")

    def test_frozen_packet_auto_clear(self):
        rejection(lambda d, p: p.update({"allow_auto_clear": True}),
                  "PR251_FLAG_allow_auto_clear")

    def test_case_approval_ref_inserted(self):
        rejection(lambda d, p: case(d, "002188.SZ").update({
                  "approval_reference": "signature-123"}),
                  "CASE_SOURCE_OR_DECISION_CHANGED_002188.SZ")

    def test_case_verdict_change(self):
        rejection(lambda d, p: case(d, "002178.SZ").update({
                  "reviewer_verdict": "ACCEPTED"}),
                  "CASE_SOURCE_OR_DECISION_CHANGED_002178.SZ")

    def test_case_hold_changed_to_approval(self):
        rejection(lambda d, p: case(d, "002310.SZ").update({
                  "human_decision": "APPROVED"}),
                  "CASE_SOURCE_OR_DECISION_CHANGED_002310.SZ")

    def test_case_apply_enabled(self):
        rejection(lambda d, p: case(d, "002328.SZ").update({
                  "allow_apply": True}), "CASE_002328.SZ_FLAG_allow_apply")

    def test_case_ledger_clear_enabled(self):
        rejection(lambda d, p: case(d, "002388.SZ").update({
                  "allow_pending_clear": True}),
                  "CASE_002388.SZ_FLAG_allow_pending_clear")

    def test_case_dedup_enabled(self):
        rejection(lambda d, p: case(d, "002188.SZ").update({
                  "allow_deduplication": True}),
                  "CASE_002188.SZ_FLAG_allow_deduplication")

    def test_case_new_approval_key(self):
        rejection(lambda d, p: case(d, "002178.SZ").update({
                  "operator_approved": True}),
                  "CASE_FIELDS_CHANGED_002178.SZ")

    def test_case_preview_sha_changed(self):
        rejection(lambda d, p: case(d, "002388.SZ").update({
                  "source_preview_sha256": "a"*64}),
                  "CASE_SOURCE_OR_DECISION_CHANGED_002388.SZ")

    def test_case_source_reference_changed(self):
        rejection(lambda d, p: case(d, "002328.SZ").update({
                  "source_document_names": ["untrusted.json"]}),
                  "CASE_SOURCE_OR_DECISION_CHANGED_002328.SZ")

    def test_evidence_gap_marked_resolved(self):
        rejection(lambda d, p: gap(d, "002188.SZ",
                                  "PROVIDER_IDENTICAL_HOLDER_ROWS_DISTINCT_IDENTITY_UNPROVEN")
                  .update({"gap_resolved": True}),
                  "EVIDENCE_002188.SZ_")

    def test_evidence_received_without_review(self):
        rejection(lambda d, p: gap(d, "002328.SZ",
                                  "SHAREHOLDERA_SEMANTICS_UNPROVEN")
                  .update({"evidence_received": True}),
                  "EVIDENCE_002328.SZ_")

    def test_gap_proof_requirements_deleted(self):
        rejection(lambda d, p: gap(d, "002310.SZ",
                                  "NAME_PUNCTUATION_ISSUER_SOURCE_DISPUTE")
                  .update({"independent_evidence_required": []}),
                  "EVIDENCE_REQUIREMENTS_CHANGED_002310.SZ")

    def test_gap_order_changed(self):
        rejection(lambda d, p: case(d, "002188.SZ")["review_gaps"].reverse(),
                  "EVIDENCE_REQUIREMENTS_CHANGED_002188.SZ")

    def test_gap_unverified_document_attached(self):
        rejection(lambda d, p: gap(d, "002178.SZ",
                                  "NAME_SPACING_AND_TYPE_TAXONOMY_UNRESOLVED")
                  .update({"approval_document": "anything.pdf"}),
                  "EVIDENCE_GAP_FIELDS_CHANGED_002178.SZ")

    def test_missing_a_case(self):
        rejection(lambda d, p: d["cases"].pop(),
                  "FIVE_CASES_MALFORMED")

    def test_reorder_five_cases(self):
        rejection(lambda d, p: d["cases"].reverse(),
                  "FIVE_CASES_NOT_EXACT_OR_SORTED")

    def test_002328_wrong_numeric_issue_code(self):
        rejection(lambda d, p: case(d, "002328.SZ")["review_gaps"][0]
                  .update({"code": "FOUR_PERSON_ROUNDING_APPROVED"}),
                  "EVIDENCE_REQUIREMENTS_CHANGED_002328.SZ")

    def test_002188_string_capital_key_not_authorization(self):
        d, prior = inputs()
        report = P.validate(d, prior)
        self.assertEqual(G.CAPITAL_KEY_JSON, '"20261119"')
        self.assertFalse(report["eligible_to_apply"])


class RunAdmissionTests(unittest.TestCase):
    def test_cli_five_holds_then_no_approval_terminal(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = P.run(DOCS)
        entries = output.getvalue().splitlines()
        self.assertEqual(sum(s.startswith("FINANCE_FIVE_ADJUDICATION_HOLD=")
                             for s in entries), 5)
        self.assertEqual(entries[-1],
                         "FINANCE_FIVE_ADJUDICATION_COMPLETE_NO_APPROVAL_NO_APPLY")
        self.assertEqual(result["human_approved"], 0)

    def test_missing_source_document_no_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            for fn in [*P.FREEZE_INPUT_NAMES.values(), P.DOSSIER_FILE]:
                shutil.copyfile(DOCS / fn, Path(td) / fn)
            (Path(td) / P.FREEZE_INPUT_NAMES["issuer"]).unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                with self.assertRaises(ValueError):
                    P.run(td)
            self.assertEqual(output.getvalue(), "")

    def test_prior_002328_issuer_conflict_tampered_no_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            for fn in [*P.FREEZE_INPUT_NAMES.values(), P.DOSSIER_FILE]:
                shutil.copyfile(DOCS / fn, Path(td) / fn)
            path = Path(td) / P.FREEZE_INPUT_NAMES["issuer"]
            source = json.loads(path.read_text())
            next(x for x in source["cases"] if x["symbol"] == "002328.SZ")[
                "current"]["shareholder"] = 57896
            path.write_text(json.dumps(source), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                with self.assertRaises(ValueError):
                    P.run(td)
            self.assertEqual(output.getvalue(), "")

    def test_no_source_manifest_file_bytes_changed_by_validation(self):
        names = [*P.FREEZE_INPUT_NAMES.values(), P.DOSSIER_FILE]
        before = {n: (DOCS / n).read_bytes() for n in names}
        P.run(DOCS)
        after = {n: (DOCS / n).read_bytes() for n in names}
        self.assertEqual(before, after)

    def test_invalid_directory_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,
                                        "STAGED_DOCS_DIRECTORY_INVALID"):
                P.run(Path(td) / "not_exists")


if __name__ == "__main__":
    unittest.main()
