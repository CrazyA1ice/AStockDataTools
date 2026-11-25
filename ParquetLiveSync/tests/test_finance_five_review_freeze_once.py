"""Fail-closed pure tests for frozen five-stock manual-review evidence.

Historical evidence only; these tests NEVER import QMT, read finance ledger,
touch source Parquet, or grant approval.
"""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

BASE = Path(__file__).resolve().parent.parent
FILE = BASE / "finance_five_review_freeze_once.py"
spec = importlib.util.spec_from_file_location("finance_five_review_freeze", FILE)
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
DOCS = BASE / "docs"
FILES = {
    "freeze": "finance-five-review-freeze-20261125.json",
    "prior": "finance-five-pilot-review-evidence-20261125.json",
    "issuer": "finance-priority-three-adjudication-manifest-20261125.json",
    "duplicate": "finance-002188-top10holder-raw-multiplicity-pin-20261125.json",
}


def evidence():
    return {name: json.loads((DOCS / filename).read_text(encoding="utf-8"))
            for name, filename in FILES.items()}


def reject(changes, expected):
    test = evidence()
    changes(test)
    try:
        G.validate(**test)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError("Expected block " + expected + ", got " + str(error))
    else:
        raise AssertionError("Tampered review evidence passed " + expected)


def case(doc, symbol):
    return next(item for item in doc["freeze"]["cases"]
                if item["symbol"] == symbol)


class SourceReviewFreezeTests(unittest.TestCase):
    def test_success_packet_holds_all_five(self):
        p = G.validate(**evidence())
        self.assertEqual(p["review_only"], 5)
        self.assertEqual(p["human_approved"], 0)
        self.assertEqual(p["pending_entry_count_observed"], 54)
        self.assertEqual([r["symbol"] for r in p["cases"]], sorted(G.CASES))
        self.assertTrue(p["historical_evidence_only"])
        self.assertFalse(p["live_source_revalidation_complete"])
        self.assertFalse(p["eligible_to_apply"])
        self.assertFalse(p["automatic_writes"])
        self.assertFalse(p["allow_auto_clear"])
        self.assertTrue(all(r["decision"] == "HOLD_PENDING" for r in p["cases"]))
        self.assertEqual(len(p["packet_sha256"]), 64)

    def test_deterministic_packet_hash(self):
        self.assertEqual(G.validate(**evidence()), G.validate(**evidence()))

    def test_no_raw_names_or_shareholder_record_fields_in_output(self):
        output = G.canonical(G.validate(**evidence()))
        self.assertNotIn("MORGAN", output)
        self.assertNotIn("current_record_sha256", output)
        self.assertNotIn("shareholderA", output)
        # Quantitative conflict appears as a named review-gap CODE only;
        # original financial row payloads and shareholder names are omitted.
        self.assertIn("ISSUER_57896_VS_PROVIDER_57900_NUMERIC_CONFLICT", output)

    def test_each_case_has_nonempty_blocking_review_gaps(self):
        result = G.validate(**evidence())
        self.assertTrue(all(x["review_gap_codes"] for x in result["cases"]))
        self.assertTrue(all(not x["manual_approval_granted"] for x in result["cases"]))

    def test_frozen_owner_222_is_not_authorization(self):
        result = G.validate(**evidence())
        self.assertEqual(result["verified_owner_offline_tests"]["PR250"], 222)
        self.assertFalse(result["eligible_to_apply"])

    def test_002188_new_review_supersedes_not_erases_old_block(self):
        src = evidence()
        self.assertEqual(next(x for x in src["prior"]["cases"]
                              if x["symbol"] == "002188.SZ")["status"],
                         "BLOCKED_HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY")
        self.assertEqual(case(src, "002188.SZ")["classification"],
                         "CAPITAL_ADDITIVE_REVIEW_REQUIRED")
        self.assertEqual(G.validate(**src)["review_only"], 5)

    def test_002328_provider_issuer_numeric_conflict_retained(self):
        p = G.validate(**evidence())
        row = next(c for c in p["cases"] if c["symbol"] == "002328.SZ")
        self.assertIn("ISSUER_57896_VS_PROVIDER_57900_NUMERIC_CONFLICT",
                      row["review_gap_codes"])
        self.assertEqual(row["decision"], "HOLD_PENDING")


class FreezeTamperTests(unittest.TestCase):
    def test_approval_injected_at_root_rejected(self):
        reject(lambda d: d["freeze"].update({"approved": True}),
               "UNEXPECTED_FROZEN_TOP_LEVEL_FIELD")

    def test_root_allowed_live_mutations_rejected(self):
        reject(lambda d: d["freeze"].update({"allowed_live_mutations": True}),
               "WRITER_OR_APPROVAL_FLAG")

    def test_root_automated_approval_rejected(self):
        reject(lambda d: d["freeze"].update({"automated_approval": True}),
               "WRITER_OR_APPROVAL_FLAG")

    def test_case_manual_approval_rejected(self):
        reject(lambda d: case(d, "002188.SZ").update({"manual_approval_granted": True}),
               "CASE_UNAUTHORIZED_FLAG")

    def test_case_data_write_rejected(self):
        reject(lambda d: case(d, "002178.SZ").update({"data_write_authorized": True}),
               "CASE_UNAUTHORIZED_FLAG")

    def test_case_auto_clear_rejected(self):
        reject(lambda d: case(d, "002310.SZ").update({"auto_clear_authorized": True}),
               "CASE_UNAUTHORIZED_FLAG")

    def test_case_dedup_rejected(self):
        reject(lambda d: case(d, "002188.SZ").update({"deduplication_authorized": True}),
               "CASE_UNAUTHORIZED_FLAG")

    def test_hold_decision_changed_rejected(self):
        reject(lambda d: case(d, "002388.SZ").update({"decision": "APPROVE"}),
               "FROZEN_CASE_EVIDENCE_OR_DECISION_CHANGED")

    def test_extra_case_field_rejected(self):
        reject(lambda d: case(d, "002178.SZ").update({"signature": "auto-approved"}),
               "FROZEN_FIELDS_ADDED_OR_MISSING")

    def test_wrong_proposal_hash_rejected(self):
        reject(lambda d: case(d, "002188.SZ").update({"preview_sha256": "0"*64}),
               "FROZEN_CASE_EVIDENCE_OR_DECISION_CHANGED")

    def test_target_capital_still_string_key(self):
        self.assertEqual(evidence()["freeze"]["source_observation_receipts"]
                         ["targeted_pr250"]["new_capital_report_key_json"],
                         '"20261119"')

    def test_wrong_provider_key_rejected(self):
        reject(lambda d: d["freeze"]["source_observation_receipts"]
               ["targeted_pr250"].update({"new_capital_report_key_json": "20261119"}),
               "OWNER_OBSERVATION_RECEIPT_CHANGED")

    def test_wrong_number_of_current_rows_rejected(self):
        reject(lambda d: d["freeze"]["source_observation_receipts"]
               ["targeted_pr250"].update({"verified_source_rows_with_multiplicity": 779}),
               "OWNER_OBSERVATION_RECEIPT_CHANGED")

    def test_wrong_current_new_capital_row_hash_rejected(self):
        reject(lambda d: d["freeze"]["source_observation_receipts"]
               ["targeted_pr250"].update({"new_capital_record_sha256": "f"*64}),
               "OWNER_OBSERVATION_RECEIPT_CHANGED")

    def test_another_ledger_epoch_rejected(self):
        reject(lambda d: d["freeze"].update({"asof_ledger_sha256": "f"*64}),
               "FROZEN_EPOCH_OR_SCOPE_CHANGED")

    def test_quarantine_symbol_removed_rejected(self):
        reject(lambda d: d["freeze"].update({"known_quarantine_symbol": ""}),
               "FROZEN_EPOCH_OR_SCOPE_CHANGED")

    def test_54_pending_falsely_cleared_rejected(self):
        reject(lambda d: d["freeze"].update({"pending_ledger_entry_count_unchanged": 49}),
               "FROZEN_EPOCH_OR_SCOPE_CHANGED")

    def test_missing_case_rejected(self):
        reject(lambda d: d["freeze"]["cases"].pop(), "FROZEN_CASE_LIST_MALFORMED")

    def test_reordered_case_list_rejected(self):
        reject(lambda d: d["freeze"]["cases"].reverse(),
               "FROZEN_CASES_NOT_EXACTLY_SORTED")

    def test_added_case_nonmapping_rejected(self):
        reject(lambda d: d["freeze"]["cases"].__setitem__(0, None),
               "FROZEN_CASE_NON_MAPPING")

    def test_prior_002188_block_must_stay_in_archive(self):
        def modify(d):
            next(x for x in d["prior"]["cases"] if x["symbol"] == "002188.SZ")[
                "status"] = "CAPITAL_ADDITIVE_REVIEW_REQUIRED"
        reject(modify, "PR248_002188_PRIOR_BLOCK_ERASED")

    def test_full_002388_review_hash_restored_from_owner_receipt(self):
        d = evidence()
        archived = next(x for x in d["prior"]["cases"]
                        if x["symbol"] == "002388.SZ")
        final = case(d, "002388.SZ")
        self.assertEqual(len(archived["preview_sha256"]), 64)
        self.assertEqual(archived["preview_sha256"], final["preview_sha256"])
        self.assertEqual(archived["preview_sha256"], G.CASES["002388.SZ"][2])

    def test_missing_hash_correction_provenance_blocks(self):
        reject(lambda d: d["prior"].pop("archival_correction"),
               "PR248_ARCHIVAL_HASH_CORRECTION_NOT_ATTESTED")

    def test_hash_correction_not_silent_approval(self):
        reject(lambda d: d["prior"]["archival_correction"]
               .update({"authorizes_live_mutation": True}),
               "PR248_ARCHIVAL_HASH_CORRECTION_NOT_ATTESTED")

    def test_prior_truncated_002388_hash_cannot_be_accepted(self):
        def change(d):
            next(x for x in d["prior"]["cases"] if x["symbol"] == "002388.SZ")[
                "preview_sha256"] = d["prior"]["archival_correction"]["incorrect_previous_value"]
        reject(change, "PR248_PRIOR_REVIEW_PROOF_CHANGED_002388.SZ")

    def test_prior_002310_hash_must_stay_pinned(self):
        def modify(d):
            next(x for x in d["prior"]["cases"] if x["symbol"] == "002310.SZ")[
                "preview_sha256"] = "0"*64
        reject(modify, "PR248_PRIOR_REVIEW_PROOF_CHANGED")

    def test_issuer_002328_numeric_change_not_approved(self):
        def modify(d):
            next(x for x in d["issuer"]["cases"] if x["symbol"] == "002328.SZ")[
                "current"]["shareholder"] = 57896
        reject(modify, "ISSUER_002328_NUMERIC_CONFLICT_ERASED")

    def test_issuer_type_taxonomy_uncertainty_retained(self):
        def modify(d):
            next(x for x in d["issuer"]["cases"] if x["symbol"] == "002178.SZ")[
                "issuer_confirmation"] = "CONFIRMED"
        reject(modify, "ISSUER_UNRESOLVED_DISPUTES_ERASED")

    def test_issuer_disclosure_not_auto_approved(self):
        reject(lambda d: d["issuer"].update({"allow_auto_clear": True}),
               "ISSUER_WRITER_FLAG")

    def test_one_of_nine_raw_hashes_changed_rejected(self):
        reject(lambda d: d["duplicate"]["duplicate_row_sha256"].__setitem__(0, "0"*64),
               "002188_NINE_RAW_HASHES_CHANGED")

    def test_002188_raw_duplicate_count_modified_rejected(self):
        reject(lambda d: d["duplicate"].update({"historical_extra_occurrences": 8}),
               "002188_DUPLICATE_PROVENANCE_CHANGED")

    def test_002188_original_snapshot_hash_modified_rejected(self):
        reject(lambda d: d["duplicate"]["selected_snapshots"]["2026-11-18"]
               .update({"sha256": "0"*64}), "002188_SELECTED_SNAPSHOT_PIN_CHANGED")

    def test_002188_only_one_duplicate_count_not_accepted(self):
        reject(lambda d: d["duplicate"].update({"each_duplicate_current_count": 1}),
               "002188_DUPLICATE_PROVENANCE_CHANGED")

    def test_002188_new_capital_report_scope_must_not_change(self):
        reject(lambda d: d["duplicate"]["capital_additive_review_scope"]
               .update({"current_report_keys": 110}),
               "002188_CAPITAL_EXACT_SCOPE_CHANGED")

    def test_002388_metadata_review_not_auto_approved(self):
        reject(lambda d: case(d, "002388.SZ").update({"review_gaps": []}),
               "FROZEN_CASE_EVIDENCE_OR_DECISION_CHANGED")


class CliGuardTests(unittest.TestCase):
    def test_cli_success_prints_only_post_validation(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            packet = G.main(["--directory", str(DOCS)])
        lines = stream.getvalue().splitlines()
        self.assertEqual(sum(x.startswith("FINANCE_FIVE_REVIEW_HOLD=") for x in lines), 5)
        self.assertEqual(lines[-1], "FINANCE_FIVE_REVIEW_FREEZE_COMPLETE_NO_APPLY")
        self.assertEqual(packet["human_approved"], 0)

    def test_cli_invalid_docs_directory_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "MALFORMED|INVALID_EVIDENCE_FILE"):
                G.main(["--directory", td])

    def test_zero_io_side_effect_evidence(self):
        before = {x: (DOCS / f).read_bytes() for x, f in FILES.items()}
        G.validate(**evidence())
        after = {x: (DOCS / f).read_bytes() for x, f in FILES.items()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
