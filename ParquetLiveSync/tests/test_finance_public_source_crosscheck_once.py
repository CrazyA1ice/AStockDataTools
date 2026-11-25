"""Offline P8 public issuer + provider dictionary source observations, HOLD-only."""
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

DOCS = BASE / "docs"
PUBLIC = "finance-public-source-crosscheck-20261125.json"
STAGED = [*P7.FREEZE_INPUT_NAMES.values(), P7.DOSSIER_FILE, PUBLIC]


def original():
    p6docs = {
        name: G.load_json(DOCS / path)
        for name, path in P7.FREEZE_INPUT_NAMES.items()
    }
    p6 = G.validate(**p6docs)
    p7 = P7.validate(G.load_json(DOCS / P7.DOSSIER_FILE), p6)
    return G.load_json(DOCS / PUBLIC), p7


def case(doc, symbol):
    return next(row for row in doc["cases"] if row["symbol"] == symbol)


def expect_block(mutate, reason):
    doc, old = original()
    mutate(doc, old)
    with unittest.TestCase().assertRaisesRegex(ValueError, reason):
        P8.validate(doc, old)


class VerifiedPublicSourceFactsTests(unittest.TestCase):
    def test_all_five_holds_and_four_external_observations(self):
        doc, parent = original()
        got = P8.validate(doc, parent)
        self.assertEqual(got["case_count"], 5)
        self.assertEqual(got["source_observations"], 4)
        self.assertEqual(got["unresolved_case_count"], 5)
        self.assertEqual(got["human_approved"], 0)
        self.assertFalse(got["eligible_to_apply"])
        self.assertFalse(got["eligible_to_clear_pending"])

    def test_exact_p7_packet_hash(self):
        _, p = original()
        self.assertEqual(p["packet_sha256"], P8.P7_SHA)

    def test_public_data_does_not_claim_online_refresh(self):
        doc, p = original()
        r = P8.validate(doc, p)
        self.assertFalse(r["external_pages_reverified_by_this_run"])
        self.assertFalse(r["live_qmt_rechecked"])
        self.assertFalse(r["live_pending_rechecked"])
        self.assertTrue(r["historical_only"])

    def test_report_stable_on_reordering_python_dicts(self):
        doc, p = original()
        self.assertEqual(P8.validate(doc, p),
                         P8.validate(deepcopy(doc), deepcopy(p)))

    def test_002328_exact_issuer_count_57896_not_57900(self):
        doc, _ = original()
        x = case(doc, "002328.SZ")["observations"][0]
        self.assertEqual(x["observed_fields"]["ordinary_shareholders"], 57896)
        self.assertEqual(x["source_type"], "PRIMARY_ISSUER_PDF")
        self.assertIn("cninfo.com.cn", x["url"])

    def test_002328_QMT_documented_distinct_field_labels(self):
        doc, _ = original()
        fields = case(doc, "002328.SZ")["observations"][1]["observed_fields"]
        self.assertEqual(fields, {"shareholder": "股东总数",
                                  "shareholderA": "A股东户数"})

    def test_002328_count_conflict_not_adjudicated(self):
        doc, p = original()
        row = case(doc, "002328.SZ")
        self.assertIn("QMT_57900_ORIGIN_OR_APPROVED_ROUNDING", row["not_verified"])
        self.assertTrue(P8.validate(doc, p)["cases"][3]["review_decision"] ==
                        "HOLD_PENDING")

    def test_002178_sina_secondary_not_primary(self):
        doc, _ = original()
        row = case(doc, "002178.SZ")
        self.assertEqual(row["source_status"],
                         "SECONDARY_TRANSCRIPTION_REVIEW_ONLY")
        self.assertEqual(row["observations"][0]["source_type"],
                         "SECONDARY_PUBLISHER_HTML")
        self.assertTrue(row["not_verified"])

    def test_002310_specific_hyphen_character_not_verified(self):
        doc, _ = original()
        row = case(doc, "002310.SZ")
        self.assertEqual(row["observations"][0]["source_type"], "PRIMARY_ISSUER_PDF")
        self.assertIn("ASCII_HYPHEN_VS_HAN_ONE_TARGETED_ROW_EQUIVALENCE",
                      row["not_verified"])

    def test_002188_no_fabricated_public_source(self):
        doc, _ = original()
        row = case(doc, "002188.SZ")
        self.assertEqual(row["observations"], [])
        self.assertTrue(row["not_verified"])

    def test_002388_no_fabricated_public_source(self):
        doc, _ = original()
        row = case(doc, "002388.SZ")
        self.assertEqual(row["observations"], [])
        self.assertTrue(row["not_verified"])

    def test_source_preview_hashes_original(self):
        doc, old = original()
        for item in P8.validate(doc, old)["cases"]:
            self.assertEqual(item["source_preview_sha256"],
                             G.CASES[item["symbol"]][2])
            self.assertFalse(item["approval_granted"])
            self.assertFalse(item["allow_pending_clear"])


class PublicEvidenceTamperFailsTests(unittest.TestCase):
    def test_claim_one_case_approved(self):
        expect_block(lambda d, p: d.update({"approved_count": 1}),
                     "OBSERVATION_EPOCH_OR_SCOPE_CHANGED")

    def test_claim_live_ledger_rechecked(self):
        expect_block(lambda d, p: d.update({"live_ledger_rechecked": True}),
                     "PUBLIC_UNAUTHORIZED_live_ledger_rechecked")

    def test_claim_QMT_reread(self):
        expect_block(lambda d, p: d.update({"live_qmt_reread": True}),
                     "PUBLIC_UNAUTHORIZED_live_qmt_reread")

    def test_claim_data_write_authorized(self):
        expect_block(lambda d, p: d.update({"data_write_authorized": True}),
                     "PUBLIC_UNAUTHORIZED_data_write_authorized")

    def test_claim_pending_clear_authorized(self):
        expect_block(lambda d, p: d.update({"pending_clear_authorized": True}),
                     "PUBLIC_UNAUTHORIZED_pending_clear_authorized")

    def test_claim_deduplication_authorized(self):
        expect_block(lambda d, p: d.update({"duplicate_collapse_authorized": True}),
                     "PUBLIC_UNAUTHORIZED_duplicate_collapse_authorized")

    def test_insert_extra_approval_field(self):
        expect_block(lambda d, p: d.update({"reviewer_signed": True}),
                     "PUBLIC_OBSERVATION_SCHEMA_CHANGED")

    def test_change_prior_p7_hash(self):
        expect_block(lambda d, p: p.update({"packet_sha256": "f" * 64}),
                     "PREVIOUS_P7_RECEIPT_SHA_DRIFT")

    def test_change_p7_human_approval(self):
        expect_block(lambda d, p: p.update({"human_approved": 1}),
                     "PREVIOUS_P7_HOLD_STATE_DRIFT")

    def test_change_p7_case_decision(self):
        expect_block(lambda d, p: p["cases"][0].update({
                     "human_decision": "APPROVED"}),
                     "PUBLIC_CASE_PROVENANCE_OR_HOLD_DRIFT_002178")

    def test_change_public_case_preview_hash(self):
        expect_block(lambda d, p: case(d, "002188.SZ").update({
                     "baseline_preview_sha256": "0" * 64}),
                     "PUBLIC_CASE_PROVENANCE_OR_HOLD_DRIFT_002188")

    def test_change_002328_issuer_shareholder_count(self):
        expect_block(lambda d, p: case(d, "002328.SZ")["observations"][0]
                     ["observed_fields"].update({"ordinary_shareholders": 57900}),
                     "PUBLIC_SOURCE_OBSERVATION_TAMPERED_002328")

    def test_change_field_semantics_to_total_shareholders(self):
        expect_block(lambda d, p: case(d, "002328.SZ")["observations"][1]
                     ["observed_fields"].update({"shareholderA": "股东总数"}),
                     "PUBLIC_SOURCE_OBSERVATION_TAMPERED_002328")

    def test_remove_002328_provider_limitation(self):
        expect_block(lambda d, p: case(d, "002328.SZ")["observations"][1]
                     ["limits"].clear(),
                     "PUBLIC_SOURCE_OBSERVATION_TAMPERED_002328")

    def test_change_002310_to_claim_confirmed_identity(self):
        expect_block(lambda d, p: case(d, "002310.SZ").update({
                     "not_verified": []}),
                     "PUBLIC_CASE_PROVENANCE_OR_HOLD_DRIFT_002310")

    def test_change_002178_source_to_primary_pdf(self):
        expect_block(lambda d, p: case(d, "002178.SZ")["observations"][0]
                     .update({"source_type": "PRIMARY_ISSUER_PDF"}),
                     "PUBLIC_SOURCE_OBSERVATION_TAMPERED_002178")

    def test_insert_unreviewed_url(self):
        expect_block(lambda d, p: case(d, "002388.SZ")["observations"].append({
                     "id": "FAKE"}),
                     "PUBLIC_SOURCE_OBSERVATION_COUNT_DRIFT_002388")

    def test_reorder_case_list_rejected(self):
        expect_block(lambda d, p: d["cases"].reverse(),
                     "PUBLIC_CASE_ORDER_OR_IDENTITY_CHANGED")

    def test_extra_case_approval(self):
        expect_block(lambda d, p: case(d, "002328.SZ").update({
                     "human_approval": True}), "PUBLIC_CASE_FIELDS_CHANGED_002328")

    def test_002328_no_contrived_rounded_count(self):
        expect_block(lambda d, p: case(d, "002328.SZ")["observations"][0]
                     ["observed_fields"].update({"ordinary_shareholders": 57900}),
                     "PUBLIC_SOURCE_OBSERVATION_TAMPERED_002328")


class AdmissionFromStagedDocsTests(unittest.TestCase):
    def test_cli_prints_only_after_complete_validation(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = P8.run(DOCS)
        lines = buf.getvalue().splitlines()
        self.assertEqual(sum(x.startswith("FINANCE_PUBLIC_SOURCE_HOLD=")
                             for x in lines), 5)
        self.assertEqual(lines[-1],
                         "FINANCE_PUBLIC_SOURCE_COMPLETE_NO_APPROVAL_NO_APPLY")
        self.assertEqual(result["human_approved"], 0)

    def test_mutated_prior_issuer_doc_blocks_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            for filename in STAGED:
                shutil.copyfile(DOCS / filename, Path(td) / filename)
            source = Path(td) / P7.FREEZE_INPUT_NAMES["issuer"]
            json_obj = json.loads(source.read_text(encoding="utf-8"))
            next(x for x in json_obj["cases"] if x["symbol"] == "002328.SZ")[
                "current"]["shareholder"] = 57896
            source.write_text(json.dumps(json_obj), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(ValueError):
                    P8.run(td)
            self.assertEqual(buf.getvalue(), "")

    def test_missing_docs_block_without_success_output(self):
        with tempfile.TemporaryDirectory() as td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(ValueError):
                    P8.run(td)
            self.assertEqual(buf.getvalue(), "")

    def test_invalid_directory_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "STAGED_DIRECTORY_INVALID"):
                P8.run(Path(td) / "not-a-folder")

    def test_source_files_unchanged(self):
        before = {f: (DOCS / f).read_bytes() for f in STAGED}
        with redirect_stdout(io.StringIO()):
            P8.run(DOCS)
        after = {f: (DOCS / f).read_bytes() for f in STAGED}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
