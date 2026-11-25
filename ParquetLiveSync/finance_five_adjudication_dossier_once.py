#!/usr/bin/env python3
"""Offline five-case unresolved-question dossiers, NEVER an approval gate.

Uses previously owner-tested PR251 freeze packet and three original evidence
manifests. Does not load QMT or inspect current finance ledger, Parquet files,
scheduled task, mutex, pending cursor, or active pins. No write entrypoint.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import finance_five_review_freeze_once as G

FORMAT = "astock_finance_five_adjudication_dossiers_hold_only_v1"
SOURCE_PACKET_SHA = "5cc5aca739e19b9426ae2fc1fa398e5b9c11af5fc8a0344d0be8abfa58988dc3"
NOTICE = ("This file lists unresolved evidence requests only. It contains no "
          "signatures, approval slots, executable remediation instructions, "
          "or live-state validation. No field can turn a review into approval.")

NEEDED = {
    "NAME_SPACING_AND_TYPE_TAXONOMY_UNRESOLVED": (
        "ISSUER_HOLDER_NAME_ALIGNMENT",
        "PROVIDER_QFII_VS_COMPANY_CLASSIFICATION_ORIGIN",
        "ISSUER_FOREIGN_LEGAL_PERSON_TAXONOMY_MAPPING",
    ),
    "PROVIDER_IDENTICAL_HOLDER_ROWS_DISTINCT_IDENTITY_UNPROVEN": (
        "NINE_RAW_SHA256_COUNT_TWO_ORIGIN",
        "PROVIDER_DUPLICATE_ROW_IDENTITY_SEMANTICS",
        "ISSUER_OR_PROVIDER_DISTINCT_HOLDER_PROOF",
    ),
    "NEW_CAPITAL_REPORT_KEY_NO_WRITE_AUTHORIZATION": (
        "QMT_STRING_KEY_20261119_ORIGIN",
        "NEW_CAPITAL_ROW_SHA256_PROVENANCE",
        "SEPARATE_IMMUTABLE_VERSION_WRITER_APPROVAL",
    ),
    "NAME_PUNCTUATION_ISSUER_SOURCE_DISPUTE": (
        "ISSUER_ASCII_HYPHEN_SOURCE_EVIDENCE",
        "QMT_HAN_ONE_SOURCE_EVIDENCE",
        "EXACT_HOLDER_IDENTITY_DISPOSITION",
    ),
    "ISSUER_57896_VS_PROVIDER_57900_NUMERIC_CONFLICT": (
        "ISSUER_20260930_COUNT_57896_EVIDENCE",
        "QMT_20260930_COUNT_57900_PROVENANCE",
        "FOUR_COUNT_DIFFERENCE_EXPLANATION_AND_ADJUDICATION",
    ),
    "SHAREHOLDERA_SEMANTICS_UNPROVEN": (
        "SHAREHOLDERA_OFFICIAL_FIELD_SEMANTICS",
        "SHAREHOLDER_VS_SHAREHOLDERA_COMPARABILITY_PROOF",
    ),
    "HOLDER_DISCLOSURE_DATE_AND_TYPE_REVISION_UNADJUDICATED": (
        "TOP10FLOWHOLDER_ISSUER_DISCLOSURE_DATE",
        "PROVIDER_HOLDER_TYPE_TAXONOMY_MAPPING",
        "CROSS_CAPITAL_MQUARTER_HISTORY_PRESERVATION",
    ),
}
SOURCE_NAMES = {
    "002178.SZ": (
        "finance-priority-three-adjudication-manifest-20261125.json",
        "finance-five-review-freeze-20261125.json",
    ),
    "002188.SZ": (
        "finance-002188-top10holder-raw-multiplicity-pin-20261125.json",
        "finance-five-review-freeze-20261125.json",
    ),
    "002310.SZ": (
        "finance-priority-three-adjudication-manifest-20261125.json",
        "finance-five-review-freeze-20261125.json",
    ),
    "002328.SZ": (
        "finance-priority-three-adjudication-manifest-20261125.json",
        "finance-five-review-freeze-20261125.json",
    ),
    "002388.SZ": (
        "finance-five-review-freeze-20261125.json",
        "finance-five-pilot-review-evidence-20261125.json",
    ),
}
FREEZE_INPUT_NAMES = {
    "freeze": "finance-five-review-freeze-20261125.json",
    "prior": "finance-five-pilot-review-evidence-20261125.json",
    "issuer": "finance-priority-three-adjudication-manifest-20261125.json",
    "duplicate": "finance-002188-top10holder-raw-multiplicity-pin-20261125.json",
}
DOSSIER_FILE = "finance-five-adjudication-dossiers-20261125.json"


def block(detail):
    raise ValueError("FINANCE_FIVE_ADJUDICATION_HOLD_GATE_BLOCKED " + detail)


def require_false(obj, keys, scope):
    for key in keys:
        if obj.get(key) is not False:
            block(scope + "_FLAG_" + key)


def validate(dossier, frozen_packet):
    """Pure, closed-schema evidence-request check with ZERO authorization."""
    if not isinstance(dossier, dict) or not isinstance(frozen_packet, dict):
        block("EVIDENCE_MALFORMED")
    if frozen_packet.get("packet_sha256") != SOURCE_PACKET_SHA:
        block("PR251_FROZEN_PACKET_SHA_CHANGED")
    if (frozen_packet.get("format") != G.FORMAT + "_packet_v1"
            or frozen_packet.get("review_only") != 5
            or frozen_packet.get("human_approved") != 0
            or frozen_packet.get("eligible_to_apply") is not False
            or frozen_packet.get("live_source_revalidation_complete") is not False
            or frozen_packet.get("pending_entry_count_observed") != 54):
        block("PR251_INELIGIBLE_HISTORICAL_PACKET_CHANGED")
    require_false(frozen_packet, ("automatic_writes", "allow_auto_clear"),
                  "PR251")

    if set(dossier) != {
            "schema", "observation_date", "source_pr251_packet_sha256",
            "source_epoch_ledger_sha256", "historical_only",
            "live_state_reverified", "manual_approval_count", "case_count",
            "approval_records_supported", "may_trigger_live_write",
            "may_clear_pending", "may_deduplicate", "default_decision",
            "cases", "notice"}:
        block("DOSSIER_TOP_LEVEL_FIELDS_CHANGED")
    if (dossier["schema"] != FORMAT
            or dossier["observation_date"] != "2026-11-25"
            or dossier["source_pr251_packet_sha256"] != SOURCE_PACKET_SHA
            or dossier["source_epoch_ledger_sha256"] != G.LEDGER
            or dossier["historical_only"] is not True
            or dossier["manual_approval_count"] != 0
            or dossier["case_count"] != 5
            or dossier["default_decision"] != "HOLD_PENDING"
            or dossier["notice"] != NOTICE):
        block("DOSSIER_SCOPE_OR_HOLD_POLICY_CHANGED")
    require_false(dossier, (
        "live_state_reverified", "approval_records_supported",
        "may_trigger_live_write", "may_clear_pending", "may_deduplicate",
    ), "DOSSIER")
    cases = dossier["cases"]
    if (not isinstance(cases, list) or len(cases) != 5
            or not all(isinstance(item, dict) for item in cases)):
        block("FIVE_CASES_MALFORMED")
    if [c.get("symbol") for c in cases] != sorted(G.CASES):
        block("FIVE_CASES_NOT_EXACT_OR_SORTED")
    frozen_cases = frozen_packet["cases"]
    if ([c["symbol"] for c in frozen_cases] != sorted(G.CASES)
            or not all(c["decision"] == "HOLD_PENDING" for c in frozen_cases)):
        block("PR251_FROZEN_HOLD_CASES_CHANGED")

    output_cases = []
    for item, frozen in zip(cases, frozen_cases):
        symbol = item["symbol"]
        if set(item) != {
                "symbol", "table", "source_preview_sha256",
                "source_document_names", "review_gaps", "human_decision",
                "reviewer_verdict", "approval_reference", "allow_apply",
                "allow_pending_clear", "allow_deduplication"}:
            block("CASE_FIELDS_CHANGED_" + symbol)
        table, classification, fingerprint, versions, union, gaps = G.CASES[symbol]
        if (item["table"] != table
                or item["source_preview_sha256"] != fingerprint
                or frozen["preview_sha256"] != fingerprint
                or frozen["classification"] != classification
                or frozen["review_gap_codes"] != list(gaps)
                or item["source_document_names"] != list(SOURCE_NAMES[symbol])
                or item["human_decision"] != "HOLD_PENDING"
                or item["reviewer_verdict"] != "UNRECORDED"
                or item["approval_reference"] is not None):
            block("CASE_SOURCE_OR_DECISION_CHANGED_" + symbol)
        require_false(item, ("allow_apply", "allow_pending_clear",
                             "allow_deduplication"), "CASE_" + symbol)
        questions = item["review_gaps"]
        if (not isinstance(questions, list) or len(questions) != len(gaps)
                or not all(isinstance(q, dict) for q in questions)):
            block("CASE_EVIDENCE_GAPS_MALFORMED_" + symbol)
        for q, gap in zip(questions, gaps):
            if set(q) != {
                    "code", "independent_evidence_required",
                    "evidence_received", "gap_resolved"}:
                block("EVIDENCE_GAP_FIELDS_CHANGED_" + symbol)
            if (q["code"] != gap
                    or q["independent_evidence_required"] != list(NEEDED[gap])):
                block("EVIDENCE_REQUIREMENTS_CHANGED_" + symbol)
            require_false(q, ("evidence_received", "gap_resolved"),
                          "EVIDENCE_" + symbol + "_" + gap)
        output_cases.append({
            "symbol": symbol, "table": table,
            "source_preview_sha256": fingerprint,
            "human_decision": "HOLD_PENDING",
            "unresolved_gap_codes": list(gaps),
            "required_independent_proof_count": sum(len(NEEDED[x]) for x in gaps),
            "human_approval_granted": False,
            "allow_apply": False,
            "allow_auto_clear": False,
        })
    packet = {
        "format": FORMAT + "_validated_packet_v1",
        "source_pr251_packet_sha256": SOURCE_PACKET_SHA,
        "source_epoch_ledger_sha256": G.LEDGER,
        "historical_only": True,
        "live_state_reverified": False,
        "total_cases": 5,
        "unresolved_gap_count": sum(len(G.CASES[x][5]) for x in sorted(G.CASES)),
        "human_approved": 0, "eligible_to_apply": False,
        "eligible_to_clear_pending": False,
        "can_deduplicate": False,
        "cases": output_cases,
    }
    packet["packet_sha256"] = G.sha256_text(G.canonical(packet))
    return packet


def run(directory):
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        block("STAGED_DOCS_DIRECTORY_INVALID")
    docs = {key: G.load_json(directory / name)
            for key, name in FREEZE_INPUT_NAMES.items()}
    # Recheck every PR251 original source, not just a claimed digest.
    frozen = G.validate(**docs)
    if frozen["packet_sha256"] != SOURCE_PACKET_SHA:
        block("PR251_PACKET_DIGEST_DRIFT")
    dossier = G.load_json(directory / DOSSIER_FILE)
    report = validate(dossier, frozen)
    # A receipt is emitted ONLY after all five dossiers and four independent
    # prior source manifests have passed the full no-approval checks.
    for item in report["cases"]:
        print("FINANCE_FIVE_ADJUDICATION_HOLD=" + G.canonical(item), flush=True)
    print("FINANCE_FIVE_ADJUDICATION_SUMMARY=" + G.canonical(
        {k: v for k, v in report.items() if k != "cases"}), flush=True)
    print("FINANCE_FIVE_ADJUDICATION_COMPLETE_NO_APPROVAL_NO_APPLY", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args(argv)
    return run(args.directory)


if __name__ == "__main__":
    main()
