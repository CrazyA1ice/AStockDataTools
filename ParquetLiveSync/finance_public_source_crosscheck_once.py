#!/usr/bin/env python3
"""Offline verification of a human-observed public-source evidence receipt.

Verifies the source-controlled observations and *historical* P6/P7 evidence
identities. It DOES NOT fetch pages, verify live URLs, call QMT, read production
ledger, approve a case, write a source row, or clear pending entries.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import finance_five_review_freeze_once as G
import finance_five_adjudication_dossier_once as P7

SCHEMA = "astock_finance_public_primary_source_crosscheck_readonly_v1"
P7_SHA = "d461cf2b3dc38e17fb055b0385fc95bdb759250dae8642f531be6ebeb0ba6bd0"
SOURCES = {
    "002178.SZ": (
        "SECONDARY_TRANSCRIPTION_REVIEW_ONLY",
        ("SECONDARY_DISCLOSURE_NAME_AND_NATURE_VISIBLE",),
        ("QMT_QFII_VS_COMPANY_TYPE_MAPPING", "SOURCE_ROW_NAME_WHITESPACE_IDENTITY"),
        (("002178_SINA_2026Q3_NAME_AND_NATURE", "SECONDARY_PUBLISHER_HTML",
          "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12678209&stockid=002178",
          "2026Q3", "Shareholder information; first ten shareholders",
          {"holder_display_name": "J.P.Morgan Securities PLC-自有资金",
           "issuer_described_nature": "境外法人"},
          ("This is Sina-hosted disclosure text, not independently downloaded issuer PDF bytes",
           "Name presentation cannot by itself establish QMT type taxonomy mapping or exact holder-row hash equality")),),
    ),
    "002188.SZ": (
        "NO_NEW_INDEPENDENT_PUBLIC_SOURCE", (), (
            "NINE_IDENTICAL_HOLDER_RAW_ROWS_DISTINCT_OWNER_SEMANTICS",
            "NEW_20261119_CAPITAL_SOURCE_AUTHORITY"), (),
    ),
    "002310.SZ": (
        "PRIMARY_ISSUER_REPORT_LOCATED_ROW_MATCH_UNPROVEN",
        ("PRIMARY_Q3_DISCLOSURE_REPORT_AND_SHAREHOLDER_TABLE_LOCATED",),
        ("ASCII_HYPHEN_VS_HAN_ONE_TARGETED_ROW_EQUIVALENCE",),
        (("002310_CNINFO_2026Q3_REPORT", "PRIMARY_ISSUER_PDF",
          "https://static.cninfo.com.cn/finalpage/2026-10-30/1225641410.PDF",
          "2026Q3", "PDF page 4-5 (1-based), shareholder tables",
          {"stock_code": "002310", "report_end_date": "20260930",
           "has_shareholder_name_table": True},
          ("Specific conflicting QMT holder row was NOT independently mapped to a PDF row by stable ID",
           "PDF extraction and fonts cannot establish ASCII hyphen vs U+4E00 exact byte identity without targeted verification",
           "No authority to normalize provider shareholder names")),),
    ),
    "002328.SZ": (
        "PRIMARY_ISSUER_COUNT_AND_QMT_FIELD_LABEL_VERIFIED_CONFLICT_UNRESOLVED",
        ("ISSUER_20260930_ORDINARY_SHAREHOLDERS_57896_DIRECTLY_VERIFIED",
         "QMT_HOLDERNUM_SHAREHOLDERA_MEANS_A_SHAREHOLDER_ACCOUNTS"),
        ("QMT_57900_ORIGIN_OR_APPROVED_ROUNDING",
         "ACTUAL_STOCK_SHAREHOLDER_VS_SHAREHOLDERA_DATA_SCOPE_EQUIVALENCE"),
        (("002328_CNINFO_2026Q3_57896", "PRIMARY_ISSUER_PDF",
          "https://static.cninfo.com.cn/finalpage/2026-10-29/1225633534.PDF",
          "2026Q3",
          "PDF page 4 (1-based), shareholders section, period-end ordinary shareholder count",
          {"stock_code": "002328", "report_end_date": "20260930",
           "ordinary_shareholders": 57896},
          ("Issuer Q3 figure is not a QMT provider processing-log audit",
           "No PDF text indicates QMT 57900 is a rounded value")),
         ("XUNT0U_STOCK_DICTIONARY_HOLDERNUM", "QMT_PROVIDER_FIELD_DICTIONARY",
          "https://dict.thinktrader.net/dictionary/stock.html",
          "undated documentation accessed 2026-11-25",
          "股东数 / Holdernum fields table",
          {"shareholder": "股东总数", "shareholderA": "A股东户数"},
          ("General QMT schema definition only",
           "It does not establish which exact issuer population QMT counted on 20260930",
           "It does not prove shareholderA and shareholder should match on this stock"))),
    ),
    "002388.SZ": (
        "NO_NEW_INDEPENDENT_PUBLIC_SOURCE", (), (
            "TARGETED_HOLDER_DECLAREDATE_AND_TYPE_OFFICIAL_DISPOSITION",
            "CROSS_CAPITAL_MQUARTER_VERSION_ORIGIN"), (),
    ),
}
EXPECTED_KEYS = {
    "schema", "observed_on", "source_p7_packet_sha256",
    "source_p6_packet_sha256", "historical_epoch_ledger_sha256",
    "provenance_method", "live_qmt_reread", "live_ledger_rechecked",
    "case_count", "unresolved_case_count", "approved_count",
    "data_write_authorized", "pending_clear_authorized",
    "duplicate_collapse_authorized", "public_verifications_not_human_approval",
    "cases", "notice",
}
NOTICE = ("A field dictionary definition is not evidence of equal row-level populations; "
          "an issuer report value does not authorize overwriting provider data; "
          "unverified punctuation is not resolved; no signing, apply, dedup, "
          "or pending-clear tokens.")
METHOD = ("Manual read of online public pages (web text + PDF screenshot). "
          "Source URLs, observations and page locations only; raw external "
          "file SHA256 was not independently captured.")


def fail(reason):
    raise ValueError("FINANCE_PUBLIC_SOURCE_EVIDENCE_BLOCKED " + reason)


def exact_false(mapping, fields, name):
    for field in fields:
        if mapping.get(field) is not False:
            fail(name + "_UNAUTHORIZED_" + field)


def validate(public, p7):
    """Pure validation; signed human approval and live-state proof not accepted."""
    if not isinstance(public, dict) or not isinstance(p7, dict):
        fail("DOCUMENT_NON_MAPPING")
    if p7.get("packet_sha256") != P7_SHA:
        fail("PREVIOUS_P7_RECEIPT_SHA_DRIFT")
    if (p7.get("total_cases") != 5
            or p7.get("unresolved_gap_count") != 7
            or p7.get("human_approved") != 0
            or p7.get("eligible_to_apply") is not False
            or p7.get("eligible_to_clear_pending") is not False
            or p7.get("historical_only") is not True
            or p7.get("live_state_reverified") is not False):
        fail("PREVIOUS_P7_HOLD_STATE_DRIFT")
    if set(public) != EXPECTED_KEYS:
        fail("PUBLIC_OBSERVATION_SCHEMA_CHANGED")
    if (public["schema"] != SCHEMA
            or public["observed_on"] != "2026-11-25"
            or public["source_p7_packet_sha256"] != P7_SHA
            or public["source_p6_packet_sha256"] != P7.SOURCE_PACKET_SHA
            or public["historical_epoch_ledger_sha256"] != G.LEDGER
            or public["provenance_method"] != METHOD
            or public["case_count"] != 5
            or public["unresolved_case_count"] != 5
            or public["approved_count"] != 0
            or public["public_verifications_not_human_approval"] is not True
            or public["notice"] != NOTICE):
        fail("OBSERVATION_EPOCH_OR_SCOPE_CHANGED")
    exact_false(public, (
        "live_qmt_reread", "live_ledger_rechecked", "data_write_authorized",
        "pending_clear_authorized", "duplicate_collapse_authorized",
    ), "PUBLIC")

    cases = public["cases"]
    if not isinstance(cases, list) or len(cases) != 5:
        fail("FIVE_PUBLIC_CASES_MISSING")
    if not all(isinstance(case, dict) for case in cases):
        fail("PUBLIC_CASE_NOT_MAPPING")
    if [x.get("symbol") for x in cases] != sorted(G.CASES):
        fail("PUBLIC_CASE_ORDER_OR_IDENTITY_CHANGED")
    p7cases = p7.get("cases", [])
    if [x.get("symbol") for x in p7cases] != sorted(G.CASES):
        fail("PREVIOUS_P7_CASE_IDENTITY_DRIFT")

    rows = []
    for item, previous in zip(cases, p7cases):
        sym = item["symbol"]
        if set(item) != {
                "symbol", "table", "baseline_preview_sha256", "source_status",
                "observations", "newly_supported", "not_verified", "hold_required"}:
            fail("PUBLIC_CASE_FIELDS_CHANGED_" + sym)
        table, _, digest, _, _, gaps = G.CASES[sym]
        status, support, unknown, sources = SOURCES[sym]
        if (item["table"] != table or item["baseline_preview_sha256"] != digest
                or previous.get("source_preview_sha256") != digest
                or previous.get("human_decision") != "HOLD_PENDING"
                or item["source_status"] != status
                or item["newly_supported"] != list(support)
                or item["not_verified"] != list(unknown)
                or item["hold_required"] is not True):
            fail("PUBLIC_CASE_PROVENANCE_OR_HOLD_DRIFT_" + sym)
        observations = item["observations"]
        if not isinstance(observations, list) or len(observations) != len(sources):
            fail("PUBLIC_SOURCE_OBSERVATION_COUNT_DRIFT_" + sym)
        for observed, expected in zip(observations, sources):
            if not isinstance(observed, dict) or set(observed) != {
                    "id", "source_type", "url", "document_period",
                    "location", "observed_fields", "limits"}:
                fail("PUBLIC_SOURCE_FIELD_SCHEMA_CHANGED_" + sym)
            values = (
                observed["id"], observed["source_type"], observed["url"],
                observed["document_period"], observed["location"],
                observed["observed_fields"], tuple(observed["limits"])
            )
            if values != expected:
                fail("PUBLIC_SOURCE_OBSERVATION_TAMPERED_" + sym)

        rows.append({
            "symbol": sym, "table": table,
            "source_preview_sha256": digest,
            "source_observations": len(sources),
            "newly_supported": list(support),
            "unverified": list(unknown),
            "review_decision": "HOLD_PENDING",
            "approval_granted": False, "allow_apply": False,
            "allow_pending_clear": False,
        })
    result = {
        "format": SCHEMA + "_validated_v1",
        "p7_packet_sha256": P7_SHA,
        "historical_only": True, "external_pages_reverified_by_this_run": False,
        "live_qmt_rechecked": False, "live_pending_rechecked": False,
        "source_observations": sum(len(row["observations"]) for row in cases),
        "case_count": 5, "unresolved_case_count": 5, "human_approved": 0,
        "eligible_to_apply": False, "eligible_to_clear_pending": False,
        "cases": rows,
    }
    result["packet_sha256"] = G.sha256_text(G.canonical(result))
    return result


def run(directory):
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        fail("STAGED_DIRECTORY_INVALID")
    prior = {
        key: G.load_json(directory / name)
        for key, name in P7.FREEZE_INPUT_NAMES.items()
    }
    freeze = G.validate(**prior)
    dossiers = G.load_json(directory / P7.DOSSIER_FILE)
    p7 = P7.validate(dossiers, freeze)
    if p7["packet_sha256"] != P7_SHA:
        fail("P7_REDERIVED_SHA_CHANGED")
    public = G.load_json(directory / "finance-public-source-crosscheck-20261125.json")
    verified = validate(public, p7)
    # Print only after all historical manifests and all public observations
    # have passed fail-closed checks. This is NEVER a signature/permission.
    for item in verified["cases"]:
        print("FINANCE_PUBLIC_SOURCE_HOLD=" + G.canonical(item), flush=True)
    print("FINANCE_PUBLIC_SOURCE_SUMMARY=" + G.canonical({
        k: v for k, v in verified.items() if k != "cases"}), flush=True)
    print("FINANCE_PUBLIC_SOURCE_COMPLETE_NO_APPROVAL_NO_APPLY", flush=True)
    return verified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args(argv)
    return run(args.directory)


if __name__ == "__main__":
    main()
