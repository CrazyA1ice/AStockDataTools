#!/usr/bin/env python3
"""Validate pinned five-symbol historical REVIEW-ONLY evidence, without QMT.

This tool only reads four Git-staged evidence JSON files and prints a
deterministic HOLD_PENDING decision packet. It never reads production state,
loads QMT, imports a stock, clears pending or writes a document. Re-running
historical evidence cannot prove that today's live source/ledger is unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

FORMAT = "astock_finance_five_readonly_review_freeze_v1"
LEDGER = "4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1"
HOLDER_UNION = "664618c29fbdc510fc2155c0657a8cb8c843be45c0e5bfa2affa68f364756359"
CAPITAL_NEW_ROW = "32c01e03bb442c6de6df075e735bcddf4e669061a626bccf491e798a1d7251cb"
CAPITAL_KEY_JSON = '"20261119"'
OLD_COHORT = "124bff95dfde683beb282dba89d3bc5ed71cd9c65909183823f86b7fe92fb540"
HEX = re.compile(r"[0-9a-f]{64}\Z")

CASES = {
    "002178.SZ": ("Top10Holder", "ISSUER_DISPUTED_REVIEW_REQUIRED",
                  "1e43a595a91fa23963d947a2959ce591891facc3bebbf233c544d6e24c4367fe",
                  762, "0e16003fd4a5835f6ade2f3709a185e83d3199ac457aab99c2b333fd9f6141ec",
                  ("NAME_SPACING_AND_TYPE_TAXONOMY_UNRESOLVED",)),
    "002188.SZ": ("Capital", "CAPITAL_ADDITIVE_REVIEW_REQUIRED",
                  "426ffd9ad947bf320625f337e59b3e21baa47fd196fe6a3e1403a40536e0a25d",
                  110, None,
                  ("PROVIDER_IDENTICAL_HOLDER_ROWS_DISTINCT_IDENTITY_UNPROVEN",
                   "NEW_CAPITAL_REPORT_KEY_NO_WRITE_AUTHORIZATION")),
    "002310.SZ": ("Top10Holder", "ISSUER_DISPUTED_REVIEW_REQUIRED",
                  "6ffba8c7c21a7810a1c02dd8e89aa81d563763f11892b32064630c96fee42401",
                  888, "2152b1d668daf9813b7bef73fe3ce97a230265389d12983f87beb3607cf54797",
                  ("NAME_PUNCTUATION_ISSUER_SOURCE_DISPUTE",)),
    "002328.SZ": ("HolderNum", "ISSUER_DISPUTED_REVIEW_REQUIRED",
                  "6f87d4ef0aaaa4fa93c39ef55aa9794b441f57bfc257a9fea791c9189256892e",
                  238, "4a90694baeb937e258f18b842e7489270ee0bac85f1779d50c6fa46cdafeb415",
                  ("ISSUER_57896_VS_PROVIDER_57900_NUMERIC_CONFLICT",
                   "SHAREHOLDERA_SEMANTICS_UNPROVEN")),
    "002388.SZ": ("Top10FlowHolder", "HOLDER_METADATA_REVIEW_REQUIRED",
                  "f0e0601ff35d1eb683a8401aca16bc9e3800eec618083b0ec6f37f0c984ed05c",
                  660, "ada40e5504652b5dfbb5f65c850dceb33ec6c97cffe5a485511e0e46b4a918ba",
                  ("HOLDER_DISCLOSURE_DATE_AND_TYPE_REVISION_UNADJUDICATED",)),
}
OLD_REVIEW_CODES = frozenset(("002178.SZ", "002310.SZ", "002328.SZ", "002388.SZ"))
ISSUER_CODES = frozenset(("002178.SZ", "002310.SZ", "002328.SZ"))
PINNED_DUPLICATES = frozenset((
    "0af63f0ca22c9222cee71f3b87152653914b0aa90af5ac0ac03848e555cdfd0a",
    "29c7349378b4754a430a640b6307090820c296cc8f3e485d02a904ad6f038f8d",
    "3893ebdb22db1e4dff0106363191cf471b15f5c1b7437ae68f83bed76cf20937",
    "41a5dfa1b63bb8d0b8941f6960f194ba0b6fed417237e15ab2c105c3d4d9183d",
    "4a8dc870c9d33c3353b1a6f83bad99362d3b3909d36842e412070c10b81c1c45",
    "5ffc33f692ae321b6cbbd1312859734e0c9b371a30b4f1e435b6bf21abe514aa",
    "92b1e49b01714a2e7a780ec680c88946492654d2fcc3a7a15d75b70e006a2f6d",
    "9344e0a4aa1010559542b1ee1a0c086c849864c832286cac20aa009ece0311f0",
    "af7c88014be7c6565946de3a9eae8968f0aa425f0cb5b2442996ca0451879fe9",
))
PINNED_HOLDER_SNAPSHOTS = {
    "2026-11-17": (
        "2026-11-17-060479650601cca4.parquet",
        "a596176479eb6c99716e6cb56e8cb50bad5885dcf9ea54a818a0992227870113", 779, 779, 0),
    "2026-11-18": (
        "2026-11-18-6728bc156bde7c85.parquet",
        "ebab890780d46e20dc1d7eaa239bda66e7b8a00c2f119229bba41565e905ba9a", 788, 779, 9),
}


def block(code):
    raise ValueError("FINANCE_FIVE_REVIEW_FREEZE_BLOCKED " + code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_bool_false(value, reason):
    if value is not False:
        block(reason)


def validate(freeze, prior, issuer, duplicate):
    """Validate a frozen historical decision packet, not the live finance DB."""
    if any(not isinstance(v, dict) for v in (freeze, prior, issuer, duplicate)):
        block("NON_MAPPING_EVIDENCE")
    # Do not let an extra approval-looking field survive on a frozen packet.
    if set(freeze) != {
            "schema", "produced_from_observations", "asof_ledger_daily_date",
            "asof_ledger_sha256", "historical_evidence_only",
            "live_data_state_revalidated_for_apply",
            "source_observation_receipts", "source_documents", "case_count",
            "review_required_count", "approved_count",
            "pending_ledger_entry_count_unchanged", "known_quarantine_symbol",
            "default_decision", "allowed_live_mutations", "automated_approval",
            "cases", "note"}:
        block("UNEXPECTED_FROZEN_TOP_LEVEL_FIELD")
    if (freeze.get("schema") != FORMAT
            or freeze.get("produced_from_observations") != "2026-11-25"
            or freeze.get("asof_ledger_daily_date") != "2026-11-24"
            or freeze.get("asof_ledger_sha256") != LEDGER
            or freeze.get("historical_evidence_only") is not True
            or freeze.get("live_data_state_revalidated_for_apply") is not False
            or freeze.get("case_count") != 5
            or freeze.get("review_required_count") != 5
            or freeze.get("approved_count") != 0
            or freeze.get("pending_ledger_entry_count_unchanged") != 54
            or freeze.get("known_quarantine_symbol") != "688259.SH"
            or freeze.get("default_decision") != "HOLD_PENDING_NO_COMMIT"):
        block("FROZEN_EPOCH_OR_SCOPE_CHANGED")
    for field in ("allowed_live_mutations", "automated_approval"):
        require_bool_false(freeze.get(field), "WRITER_OR_APPROVAL_FLAG_" + field)
    sources = freeze.get("source_documents")
    if sources != {
        "prior_five_pilot": "finance-five-pilot-review-evidence-20261125.json",
        "disclosure_manifest": "finance-priority-three-adjudication-manifest-20261125.json",
        "exact_holder_pin": "finance-002188-top10holder-raw-multiplicity-pin-20261125.json",
    }:
        block("SOURCE_FILE_REFS_CHANGED")
    receipts = freeze.get("source_observation_receipts")
    if not isinstance(receipts, dict):
        block("RECEIPTS_MALFORMED")
    batch = receipts.get("five_stock_pr248")
    targeted = receipts.get("targeted_pr250")
    if (batch != {
            "offline_tests_passed": 162,
            "qmt_existing_cache_symbols_present": 5,
            "cohort_sha256": OLD_COHORT,
        } or targeted != {
            "offline_tests_passed": 222,
            "existing_cache_only_symbol": "002188.SZ",
            "capital_preview_sha256": CASES["002188.SZ"][2],
            "verified_duplicate_raw_groups": 9,
            "verified_source_rows_with_multiplicity": 788,
            "new_capital_report_key_json": CAPITAL_KEY_JSON,
            "new_capital_record_sha256": CAPITAL_NEW_ROW,
            "raw_holder_union_sha256": HOLDER_UNION,
        }):
        block("OWNER_OBSERVATION_RECEIPT_CHANGED")

    if (prior.get("format") != "finance_five_pilot_non_authorizing_observation_v1"
            or prior.get("ledger_daily_date") != "2026-11-24"
            or prior.get("ledger_sha256") != LEDGER
            or prior.get("overall_preview_sha256") != OLD_COHORT
            or prior.get("offline_tests_passed") != 162
            or prior.get("qmt_cache_symbols_present") != 5
            or prior.get("readiness") != "REVIEW_ONLY_NO_APPLY_AUTHORIZATION"):
        block("PR248_EVIDENCE_MISMATCH")
    for flag in ("allow_apply", "allow_auto_clear", "has_human_approval"):
        require_bool_false(prior.get(flag), "PR248_WRITER_FLAG_" + flag)
    # The original source-controlled archive accidentally truncated 002388's
    # preview SHA256 to 54 hex digits. P6 records an explicit correction
    # from the user's full PR248 run rather than treating a guessed prefix
    # as cryptographic provenance.
    if prior.get("archival_correction") != {
            "case": "002388.SZ / Top10FlowHolder",
            "field": "preview_sha256",
            "incorrect_previous_value":
                "f0e0601ff35d1eb683a8401aca16bc9e3800eec6f37f0c984ed05c",
            "verified_full_value": CASES["002388.SZ"][2],
            "verification":
                "Owner supplied successful PR248 162/162 offline and five QMT existing-cache preview output on 2026-11-25",
            "changes_historical_review_outcome": False,
            "authorizes_live_mutation": False,
        }:
        block("PR248_ARCHIVAL_HASH_CORRECTION_NOT_ATTESTED")
    if prior.get("original_snapshots_immutable") is not True:
        block("PR248_SNAPSHOT_IMMUTABILITY_CHANGED")
    old_cases = prior.get("cases")
    if (not isinstance(old_cases, list) or len(old_cases) != 5
            or not all(isinstance(item, dict) for item in old_cases)):
        block("PR248_FIVE_CASES_MALFORMED")
    old = {x.get("symbol"): x for x in old_cases}
    if len(old) != 5 or set(old) != set(CASES):
        block("PR248_CASE_SCOPE_CHANGED")
    for code in OLD_REVIEW_CODES:
        item = old[code]
        expected = CASES[code]
        if (item.get("table") != expected[0] or item.get("status") != expected[1]
                or not isinstance(item.get("preview_sha256"), str)
                or HEX.fullmatch(item["preview_sha256"]) is None
                or item["preview_sha256"] != expected[2]):
            block("PR248_PRIOR_REVIEW_PROOF_CHANGED_" + code)
    if (old["002188.SZ"].get("table") != "Capital"
            or old["002188.SZ"].get("status") !=
            "BLOCKED_HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY"
            or old["002188.SZ"].get("duplicate_cause_table") != "Top10Holder"
            or old["002188.SZ"].get("historical_distinct_raw_rows") != 779
            or old["002188.SZ"].get("historical_extra_raw_occurrences") != 9):
        block("PR248_002188_PRIOR_BLOCK_ERASED")

    if (issuer.get("schema") != "astock_finance_source_disclosure_proof_v1"
            or issuer.get("purpose") != "EVIDENCE_ONLY_NOT_AN_IMPORT_APPROVAL"
            or issuer.get("ledger_sha256_unchanged") != LEDGER
            or issuer.get("default_action") != "HOLD_PENDING_NO_COMMIT"):
        block("ISSUER_EVIDENCE_SCOPE_CHANGED")
    for flag in ("allow_auto_clear", "allow_snapshot_mutation",
                  "allow_provider_cache_mutation"):
        require_bool_false(issuer.get(flag), "ISSUER_WRITER_FLAG_" + flag)
    src_cases = issuer.get("cases")
    if (not isinstance(src_cases, list) or len(src_cases) != 3
            or any(not isinstance(x, dict) for x in src_cases)
            or {x.get("symbol") for x in src_cases} != ISSUER_CODES):
        block("ISSUER_CASES_SCOPE_CHANGED")
    for record in src_cases:
        code = record["symbol"]
        if (record.get("table") != CASES[code][0]
                or record.get("endDate") != "20260930"
                or record.get("pairing_unambiguous") is not True
                or record.get("manual_approval_required") is not True
                or not all(isinstance(record.get(k), str)
                           and HEX.fullmatch(record[k])
                           for k in ("prior_record_sha256",
                                     "current_record_sha256",
                                     "stable_projection_sha256"))):
            block("ISSUER_RECORD_PROVENANCE_CHANGED_" + code)
    proven = {x["symbol"]: x for x in src_cases}
    if (proven["002178.SZ"].get("issuer_confirmation") !=
            "NAME_ONLY_TYPE_TAXONOMY_UNVERIFIED"
            or proven["002310.SZ"].get("issuer_confirmation") !=
            "ISSUER_NAME_USES_DASH_NOT_HAN_ONE"
            or proven["002328.SZ"].get("issuer_confirmation") !=
            "PRIOR_SHAREHOLDER_AND_QUARTER_REPORT_DATE_CORROBORATED"):
        block("ISSUER_UNRESOLVED_DISPUTES_ERASED")
    n328 = proven["002328.SZ"]
    if (n328.get("issuer_ordinary_shareholder_count") != 57896
            or n328.get("current", {}).get("shareholder") != 57900
            or n328.get("shareholderA_semantics") != "NOT_INDEPENDENTLY_PROVEN"
            or n328.get("current_57900_source_explanation") !=
            "UNVERIFIED_ROUNDING_ONLY_HYPOTHESIS"):
        block("ISSUER_002328_NUMERIC_CONFLICT_ERASED")

    if (duplicate.get("format") != "qmt_002188_top10holder_exact_multiplicity_pin_v1"
            or duplicate.get("symbol") != "002188.SZ"
            or duplicate.get("table") != "Top10Holder"
            or duplicate.get("report_endDate") != "20200930"
            or duplicate.get("ledger_sha256") != LEDGER
            or duplicate.get("historical_union_sha256") != HOLDER_UNION
            or duplicate.get("historical_distinct_raw_records") != 779
            or duplicate.get("historical_rows_with_multiplicity") != 788
            or duplicate.get("current_qmt_distinct_raw_records") != 779
            or duplicate.get("current_qmt_rows_with_multiplicity") != 788
            or duplicate.get("historical_duplicate_raw_groups") != 9
            or duplicate.get("historical_extra_occurrences") != 9
            or duplicate.get("each_duplicate_historical_count") != 2
            or duplicate.get("each_duplicate_current_count") != 2
            or duplicate.get("human_approval_granted") is not False):
        block("002188_DUPLICATE_PROVENANCE_CHANGED")
    for flag in ("allow_deduplication", "allow_apply", "allow_pending_clear"):
        require_bool_false(duplicate.get(flag), "002188_WRITER_FLAG_" + flag)
    rows = duplicate.get("duplicate_row_sha256")
    if (not isinstance(rows, list) or rows != sorted(PINNED_DUPLICATES)
            or len(PINNED_DUPLICATES) != 9):
        block("002188_NINE_RAW_HASHES_CHANGED")
    snapshots = duplicate.get("selected_snapshots")
    if not isinstance(snapshots, dict) or set(snapshots) != set(PINNED_HOLDER_SNAPSHOTS):
        block("002188_SELECTED_SNAPSHOT_DATES_CHANGED")
    for day, expected in PINNED_HOLDER_SNAPSHOTS.items():
        item = snapshots[day]
        if not isinstance(item, dict) or (
                item.get("filename"), item.get("sha256"),
                item.get("rows"), item.get("distinct_raw_records"),
                item.get("extra_raw_occurrences")) != expected:
            block("002188_SELECTED_SNAPSHOT_PIN_CHANGED_" + day)
    if duplicate.get("capital_additive_review_scope") != {
            "historical_report_keys": 108,
            "current_report_keys": 109,
            "exact_new_report_key": "20261119",
            "historical_capital_raw_versions": 110,
            "removed_report_keys": 0,
            "shared_economic_changed_keys": 0,
        }:
        block("002188_CAPITAL_EXACT_SCOPE_CHANGED")

    cases = freeze.get("cases")
    if not isinstance(cases, list) or len(cases) != 5:
        block("FROZEN_CASE_LIST_MALFORMED")
    if not all(isinstance(item, dict) for item in cases):
        block("FROZEN_CASE_NON_MAPPING")
    codes = [c.get("symbol") for c in cases]
    if codes != sorted(CASES):
        block("FROZEN_CASES_NOT_EXACTLY_SORTED")
    summary = []
    for case in cases:
        code = case["symbol"]
        table, classification, hash_value, versions, nine_union, gaps = CASES[code]
        wanted_keys = {
            "symbol", "table", "classification", "preview_sha256",
            "verified_target_historical_versions", "evidence_source",
            "source_epoch_ledger_sha256", "review_gaps", "decision",
            "manual_approval_granted", "data_write_authorized",
            "auto_clear_authorized", "deduplication_authorized",
        }
        if nine_union is not None:
            wanted_keys.add("nine_table_selected_union_sha256")
        if set(case) != wanted_keys:
            block("FROZEN_FIELDS_ADDED_OR_MISSING_" + code)
        if (case["table"] != table
                or case["classification"] != classification
                or case["preview_sha256"] != hash_value
                or case["verified_target_historical_versions"] != versions
                or case.get("nine_table_selected_union_sha256") != nine_union
                or case["source_epoch_ledger_sha256"] != LEDGER
                or case["evidence_source"] != (
                    "PR250_222_OFFLINE_ONE_STOCK_QMT" if code == "002188.SZ"
                    else "PR248_162_OFFLINE_FIVE_STOCK_QMT")
                or case["review_gaps"] != list(gaps)
                or case["decision"] != "HOLD_PENDING"):
            block("FROZEN_CASE_EVIDENCE_OR_DECISION_CHANGED_" + code)
        for flag in ("manual_approval_granted", "data_write_authorized",
                     "auto_clear_authorized", "deduplication_authorized"):
            require_bool_false(case[flag], "CASE_UNAUTHORIZED_FLAG_" + code + "_" + flag)
        summary.append({
            "symbol": code, "table": table, "decision": "HOLD_PENDING",
            "classification": classification, "review_gap_codes": list(gaps),
            "preview_sha256": hash_value,
            "manual_approval_granted": False,
            "allow_apply": False,
            "allow_auto_clear": False,
        })

    # Packet is deterministic and only represents historical owner-observed
    # provenance. It can NEVER replace an active-state CAS or human approval.
    packet = {
        "format": FORMAT + "_packet_v1",
        "historical_evidence_only": True,
        "live_source_revalidation_complete": False,
        "source_ledger_sha256": LEDGER,
        "verified_owner_offline_tests": {"PR248": 162, "PR250": 222},
        "review_only": 5, "human_approved": 0,
        "pending_entry_count_observed": 54,
        "automatic_writes": False, "allow_auto_clear": False,
        "eligible_to_apply": False,
        "cases": summary,
    }
    packet["packet_sha256"] = sha256_text(canonical(packet))
    return packet


def load_json(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        block("INVALID_EVIDENCE_FILE")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        block("MALFORMED_EVIDENCE_JSON")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True,
                        help="Git-blob-staged docs only, never a production data folder")
    args = parser.parse_args(argv)
    folder = args.directory
    if not folder.is_dir() or folder.is_symlink():
        block("EVIDENCE_DIRECTORY_INVALID")
    names = {
        "freeze": "finance-five-review-freeze-20261125.json",
        "prior": "finance-five-pilot-review-evidence-20261125.json",
        "issuer": "finance-priority-three-adjudication-manifest-20261125.json",
        "duplicate": "finance-002188-top10holder-raw-multiplicity-pin-20261125.json",
    }
    evidence = {key: load_json(folder / name) for key, name in names.items()}
    packet = validate(**evidence)
    # Full validation above must finish before any claim of success.
    for case in packet["cases"]:
        print("FINANCE_FIVE_REVIEW_HOLD=" + canonical(case), flush=True)
    print("FINANCE_FIVE_REVIEW_FREEZE_SUMMARY=" + canonical({
        k: v for k, v in packet.items() if k != "cases"
    }), flush=True)
    print("FINANCE_FIVE_REVIEW_FREEZE_COMPLETE_NO_APPLY", flush=True)
    return packet


if __name__ == "__main__":
    main()
