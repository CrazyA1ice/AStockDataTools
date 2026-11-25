#!/usr/bin/env python3
"""P9 disclosure vintage and U+FF0D issuer observation HOLD-only validation.

Revalidates P6, P7, P8 historical source documents then compares a fixed
source-observation manifest. This does not open original investor-interaction
API records, prove QMT provenance, fetch PDFs, or write any live data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import finance_five_review_freeze_once as G
import finance_five_adjudication_dossier_once as P7
import finance_public_source_crosscheck_once as P8

FORMAT = "astock_finance_disclosure_vintage_exact_character_hold_only_v1"
P8_PACKET_SHA = "a704a50174e143141cc91a668a0898fd8ca9d725ea27206aa780a0e80647b117"
DOC_FILENAME = "finance-disclosure-vintage-codepoint-20261125.json"
EXPECTED = json.loads(r'''{"schema":"astock_finance_disclosure_vintage_exact_character_hold_only_v1","observation_date":"2026-11-25","source_p8_packet_sha256":"a704a50174e143141cc91a668a0898fd8ca9d725ea27206aa780a0e80647b117","source_p7_packet_sha256":"d461cf2b3dc38e17fb055b0385fc95bdb759250dae8642f531be6ebeb0ba6bd0","historical_ledger_sha256":"4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1","source_method":"Online published source text and primary PDF page screenshot cross-check; no authenticated original investor-interaction API record or QMT ingestion provenance; external bytes not hashed.","case_count":5,"evidence_focus_count":2,"approved_count":0,"human_approval_granted":false,"live_source_or_ledger_revalidated":false,"allow_apply":false,"allow_pending_clear":false,"allow_deduplication":false,"cases":[{"symbol":"002178.SZ","table":"Top10Holder","decision":"HOLD_PENDING","new_evidence":"NO_CHANGE_FROM_P8","source_preview_sha256":"1e43a595a91fa23963d947a2959ce591891facc3bebbf233c544d6e24c4367fe","unresolved":["QMT_TYPE_TAXONOMY_MAPPING","ROW_NAME_IDENTITY"]},{"symbol":"002188.SZ","table":"Capital","decision":"HOLD_PENDING","new_evidence":"NO_CHANGE_FROM_P8","source_preview_sha256":"426ffd9ad947bf320625f337e59b3e21baa47fd196fe6a3e1403a40536e0a25d","unresolved":["NINE_SOURCE_IDENTICAL_RAW_ROWS_OWNER_SEMANTICS","NEW_CAPITAL_PERIOD_PROVIDER_LINEAGE"]},{"symbol":"002310.SZ","table":"Top10Holder","decision":"HOLD_PENDING","new_evidence":"ISSUER_PDF_FULLWIDTH_DASH_OBSERVED_TARGET_ROW_UNMATCHED","source_preview_sha256":"6ffba8c7c21a7810a1c02dd8e89aa81d563763f11892b32064630c96fee42401","unresolved":["QMT_TARGET_HOLDER_IDENTITY_NOT_MATCHED_TO_ISSUER_ROW","PDF_GLYPH_VS_RAW_SOURCE_CHARACTER_NOT_PROVEN"],"focused_evidence":{"source_type":"ISSUER_PRIMARY_PDF_TEXT_AND_PAGE_IMAGE","source_url":"https://static.cninfo.com.cn/finalpage/2026-10-30/1225641410.PDF","source_pdf_page_one_based":4,"source_stock_code":"002310","issuer_sample_name":"北京朝投发投资管理有限公司－北京市盈润汇民基金管理中心（有限合伙）","issuer_sample_separator":"－","issuer_sample_separator_codepoint":"U+FF0D","qmt_old_name_sha256":"ee1477b0b158cd0482a0e105eed893936d3b68b60edd2b307beb208285fffef3","qmt_current_name_sha256":"e14ebf59a2359a032c152b480b841e1772a394971c6d31404b2f2c40de775151","qmt_diff_old_codepoint":"U+002D","qmt_diff_current_codepoint":"U+4E00","sample_row_equals_disputed_hashed_qmt_row":false,"source_pdf_raw_byte_sha256_verified":false,"allowed_to_normalize_holder_names":false,"limit":"Fullwidth issuer connector is visible in the issuer PDF, but the exact hashed target QMT row has NOT been independently paired to that displayed issuer sample; no codepoint normalization or holder identity approval."}},{"symbol":"002328.SZ","table":"HolderNum","decision":"HOLD_PENDING","new_evidence":"EARLIER_APPROXIMATE_VS_LATER_EXACT_DISCLOSURE_VINTAGE_HYPOTHESIS","source_preview_sha256":"6f87d4ef0aaaa4fa93c39ef55aa9794b441f57bfc257a9fea791c9189256892e","unresolved":["QMT_INGEST_SOURCE_LINEAGE_UNVERIFIED","APPROXIMATE_57900_NOT_EXACT_ISSUER_COUNT","SHAREHOLDERA_PERIOD_POPULATION_MAPPING_UNVERIFIED"],"focused_evidence":{"report_period":"20260930","historical_qmt_declareDate":"20261029","historical_qmt_shareholder":57896,"current_qmt_declareDate":"20261012","current_qmt_shareholder":57900,"issuer_original_document_url":"https://static.cninfo.com.cn/finalpage/2026-10-29/1225633534.PDF","issuer_report_date":"2026-10-29","issuer_report_shareholder_exact":57896,"issuer_report_page_one_based":4,"early_approximate_secondary_url":"https://stock.quote.stockstar.com/info/notice_002328.shtml","early_approximate_mentioned_on":"2026-10-12","early_approximate_shareholder_reported":"约57900户","early_approximate_secondary_source_type":"THIRD_PARTY_INVESTOR_INTERACTION_REPOST","early_approximate_separate_repost_url":"https://webf10.gw.com.cn/SZ/B1/SZ002328_B1.html","early_company_reply_repost_text":"根据中国证券登记结算有限责任公司提供的数据，截至2026年9月30日，公司股东户数约5.79万户","qmt_field_definition_url":"https://dict.thinktrader.net/dictionary/stock.html","qmt_shareholder_field_label":"股东总数","qmt_shareholderA_field_label":"A股东户数","reported_numerical_difference":4,"early_value_exact_source_count_proven":false,"authenticated_original_interaction_record_verified":false,"provider_qmt_source_lineage_proven":false,"historical_qmt_exact_cas_verified_now":false,"automatic_rounding_explanation_allowed":false,"allowed_to_overwrite_either_version":false,"limit":"Timing and approximate-vs-exact representations match the two observed QMT declareDate values; source propagation and exact feed lineage remain unproven, and 57900 is explicitly an approximation, not an issuer-certified exact count."}},{"symbol":"002388.SZ","table":"Top10FlowHolder","decision":"HOLD_PENDING","new_evidence":"NO_CHANGE_FROM_P8","source_preview_sha256":"f0e0601ff35d1eb683a8401aca16bc9e3800eec618083b0ec6f37f0c984ed05c","unresolved":["HOLDER_METADATA_VERSION_ORIGIN","CROSS_CAPITAL_MQUARTER_PROVENANCE"]}],"notice":"P9 records publicly observed disclosure vintages and character codepoints without proving QMT row-level lineage. A positive test is evidence-integrity only. No candidate is authorized to write, normalize, deduplicate or clear pending."}''')


def block(reason):
    raise ValueError("FINANCE_VINTAGE_PROVENANCE_BLOCKED " + reason)


def validate(dossier, p8):
    if not isinstance(p8, dict) or p8.get("packet_sha256") != P8_PACKET_SHA:
        block("PR253_P8_PACKET_CHANGED")
    if (p8.get("format") != P8.SCHEMA + "_validated_v1"
            or p8.get("case_count") != 5
            or p8.get("unresolved_case_count") != 5
            or p8.get("source_observations") != 4
            or p8.get("human_approved") != 0
            or p8.get("eligible_to_apply") is not False
            or p8.get("eligible_to_clear_pending") is not False
            or p8.get("historical_only") is not True
            or p8.get("external_pages_reverified_by_this_run") is not False):
        block("PR253_P8_HOLD_STATE_CHANGED")
    if not isinstance(dossier, dict):
        block("P9_NON_MAPPING")
    if dossier.get("schema") != FORMAT:
        block("P9_SCHEMA_CHANGED")
    if dossier.get("source_p8_packet_sha256") != P8_PACKET_SHA:
        block("P9_PRIOR_PACKET_REF_CHANGED")
    if dossier.get("case_count") != 5 or dossier.get("evidence_focus_count") != 2:
        block("P9_CASE_SCOPE_CHANGED")
    if dossier.get("approved_count") != 0:
        block("P9_APPROVAL_COUNT_CHANGED")
    for flag in ("human_approval_granted", "live_source_or_ledger_revalidated",
                 "allow_apply", "allow_pending_clear", "allow_deduplication"):
        if dossier.get(flag) is not False:
            block("P9_FORBIDDEN_FLAG_" + flag)
    cases = dossier.get("cases")
    if not isinstance(cases, list) or len(cases) != 5 or any(
            not isinstance(x, dict) for x in cases):
        block("P9_FIVE_CASES_MISSING")
    if [x.get("symbol") for x in cases] != sorted(G.CASES):
        block("P9_CASE_ORDER_OR_IDENTITY_CHANGED")
    prior_cases = p8.get("cases", [])
    if not isinstance(prior_cases, list) or len(prior_cases) != 5:
        block("PR253_CASE_COUNT_DRIFT")
    for case, prior in zip(cases, prior_cases):
        code = case["symbol"]
        if (case.get("table") != G.CASES[code][0]
                or case.get("source_preview_sha256") != G.CASES[code][2]
                or prior.get("symbol") != code
                or prior.get("source_preview_sha256") != case.get("source_preview_sha256")
                or prior.get("review_decision") != "HOLD_PENDING"
                or case.get("decision") != "HOLD_PENDING"):
            block("P9_CASE_NOT_HELD_" + code)
    # No approvals can be smuggled through narrative or fields:
    # each observation and disclaimer must equal the source-reviewed pin,
    # down to exact 'approximate', Unicode and not-proven distinctions.
    if dossier != EXPECTED:
        block("P9_PINNED_PUBLIC_SOURCE_CLAIM_TAMPERED")
    q310 = cases[2]["focused_evidence"]
    q328 = cases[3]["focused_evidence"]
    if (q310["issuer_sample_separator"] != "－"
            or ord(q310["issuer_sample_separator"]) != 0xFF0D
            or q310["issuer_sample_separator_codepoint"] != "U+FF0D"
            or q310["sample_row_equals_disputed_hashed_qmt_row"] is not False):
        block("P9_002310_ISSUER_GLYPH_OR_PAIRING_DRIFT")
    if (q328["current_qmt_shareholder"] != 57900
            or q328["historical_qmt_shareholder"] != 57896
            or q328["current_qmt_declareDate"] != "20261012"
            or q328["historical_qmt_declareDate"] != "20261029"
            or q328["reported_numerical_difference"] != 4
            or q328["early_approximate_shareholder_reported"] != "约57900户"
            or q328["provider_qmt_source_lineage_proven"] is not False
            or q328["automatic_rounding_explanation_allowed"] is not False):
        block("P9_002328_SOURCE_VINTAGE_OR_UNPROVEN_LINEAGE_CHANGED")

    report_cases = []
    for case in cases:
        report_cases.append({
            "symbol": case["symbol"], "table": case["table"],
            "prior_preview_sha256": case["source_preview_sha256"],
            "observation_scope": case["new_evidence"],
            "unresolved": list(case["unresolved"]),
            "decision": "HOLD_PENDING", "human_approval": False,
            "allow_apply": False, "allow_pending_clear": False,
        })
    report = {
        "format": FORMAT + "_receipt_v1",
        "source_p8_packet_sha256": P8_PACKET_SHA,
        "historical_only": True,
        "external_sources_currently_refetched": False,
        "qmt_ingestion_lineage_proven": False,
        "five_cases": 5, "focused_cases": 2,
        "approved": 0, "can_apply": False, "can_clear_pending": False,
        "issuer_002310_codepoint": "U+FF0D",
        "provider_002328_preliminary_rounded_count": 57900,
        "issuer_002328_quarterly_exact_count": 57896,
        "case_decisions": report_cases,
    }
    report["packet_sha256"] = G.sha256_text(G.canonical(report))
    return report


def run(directory):
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        block("STAGED_DIRECTORY_INVALID")
    sources = {k: G.load_json(directory / name)
               for k, name in P7.FREEZE_INPUT_NAMES.items()}
    freeze = G.validate(**sources)
    p7 = P7.validate(G.load_json(directory / P7.DOSSIER_FILE), freeze)
    p8 = P8.validate(
        G.load_json(directory / "finance-public-source-crosscheck-20261125.json"), p7)
    if p8["packet_sha256"] != P8_PACKET_SHA:
        block("PR253_DERIVED_PACKET_DRIFT")
    packet = validate(G.load_json(directory / DOC_FILENAME), p8)
    for item in packet["case_decisions"]:
        print("FINANCE_VINTAGE_PROVENANCE_HOLD=" + G.canonical(item), flush=True)
    print("FINANCE_VINTAGE_PROVENANCE_SUMMARY=" + G.canonical(
        {k: v for k, v in packet.items() if k != "case_decisions"}), flush=True)
    print("FINANCE_VINTAGE_PROVENANCE_COMPLETE_NO_APPROVAL_NO_APPLY",
          flush=True)
    return packet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.directory)


if __name__ == "__main__":
    main()
