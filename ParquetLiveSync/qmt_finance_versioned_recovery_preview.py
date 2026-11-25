#!/usr/bin/env python3
"""Pure, no-write financial-source revision rehearsal (NOT production apply).

The scheduled runner, importer --apply, state ledger, selected Parquet
snapshots and QMT cache are intentionally not modified. Existing verified
historical raw variants must survive; evidence is never approval.

Call preview_symbol(...) with nine-table cache/source records and the
conservative union of already selected, verified snapshot raw records.
This module has no CLI and no QMT imports.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re

FORMAT = "qmt_finance_versioned_recovery_preview_v1"
SPECIAL_CODES = frozenset(("002178.SZ", "002310.SZ", "002328.SZ"))
HOLDER_FIELDS = {
    "Top10Holder": frozenset(("declareDate", "type")),
    "Top10FlowHolder": frozenset(("declareDate", "type")),
    "HolderNum": frozenset(("declareDate",)),
}
MODES = frozenset(("HOLDER_METADATA", "CAPITAL_ADDITIVE", "ISSUER_DISPUTED"))
HASH = re.compile(r"[0-9a-f]{64}\Z")
MAX_PAIRS = 256

# Audit-only 002188 Top10Holder exception: exact records seen in BOTH
# selected immutable history and current existing-cache QMT, 2026-11-25.
# A count=2 is preserved, NEVER collapsed. No other symbol/table can opt in.
PINNED_002188_LEDGER_SHA256 = "4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1"
PINNED_002188_UNION_SHA256 = "664618c29fbdc510fc2155c0657a8cb8c843be45c0e5bfa2affa68f364756359"
# Exact canonical JSON representations of the SAME audited 20261119 date.
# No normalization of source rows: the original type and raw SHA are retained.
# Pandas/QMT may preserve date as integer, whole float, or decimal-free string.
PINNED_002188_NEW_KEY_JSON = frozenset((
    "20261119", "20261119.0", '"20261119"',
))
PINNED_002188_RAW_SHA256 = frozenset((
    "29c7349378b4754a430a640b6307090820c296cc8f3e485d02a904ad6f038f8d",
    "92b1e49b01714a2e7a780ec680c88946492654d2fcc3a7a15d75b70e006a2f6d",
    "5ffc33f692ae321b6cbbd1312859734e0c9b371a30b4f1e435b6bf21abe514aa",
    "9344e0a4aa1010559542b1ee1a0c086c849864c832286cac20aa009ece0311f0",
    "41a5dfa1b63bb8d0b8941f6960f194ba0b6fed417237e15ab2c105c3d4d9183d",
    "af7c88014be7c6565946de3a9eae8968f0aa425f0cb5b2442996ca0451879fe9",
    "0af63f0ca22c9222cee71f3b87152653914b0aa90af5ac0ac03848e555cdfd0a",
    "4a8dc870c9d33c3353b1a6f83bad99362d3b3909d36842e412070c10b81c1c45",
    "3893ebdb22db1e4dff0106363191cf471b15f5c1b7437ae68f83bed76cf20937",
))
PINNED_002188_SNAPSHOTS = {
    "2026-11-17": {
        "filename": "2026-11-17-060479650601cca4.parquet",
        "sha256": "a596176479eb6c99716e6cb56e8cb50bad5885dcf9ea54a818a0992227870113",
        "rows": 779, "distinct_raw_records": 779, "extra_raw_occurrences": 0,
    },
    "2026-11-18": {
        "filename": "2026-11-18-6728bc156bde7c85.parquet",
        "sha256": "ebab890780d46e20dc1d7eaa239bda66e7b8a00c2f119229bba41565e905ba9a",
        "rows": 788, "distinct_raw_records": 779, "extra_raw_occurrences": 9,
    },
}
# Evidence is currently sufficient only for these exact observed
# (symbol, target-table) combinations; this is NOT a generic bypass.
CROSS_CAPITAL_SCOPED_REVIEW = frozenset((
    ("002310.SZ", "Top10Holder"),
    ("002328.SZ", "HolderNum"),
    ("002388.SZ", "Top10FlowHolder"),
))


class ReviewBlocked(ValueError):
    """A mandatory source-history gate failed; no recovery is authorized."""


def refuse(msg):
    raise ReviewBlocked("VERSIONED_RECOVERY_PREVIEW_BLOCKED " + msg)


def digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def encode(row, F):
    if not isinstance(row, dict):
        refuse("NON_MAPPING_RECORD")
    return F.E.canonical_json({k: v for k, v in row.items() if k != "_index"})


def _historical(prior, F):
    if not isinstance(prior, Counter):
        refuse("HISTORICAL_COUNTER_REQUIRED")
    results = []
    for raw, count in prior.items():
        if not isinstance(raw, str) or type(count) is not int or count != 1:
            refuse("HISTORICAL_DUPLICATE_OR_MALFORMED_MULTIPLICITY")
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            refuse("INVALID_HISTORICAL_JSON")
        if not isinstance(parsed, dict) or encode(parsed, F) != raw:
            refuse("HISTORICAL_RAW_IDENTITY_CHANGED")
        results.append(parsed)
    return results


def _check_pinned_002188_multiset(prior, current, F, *,
                                  expected_raw_sha256, expected_union_sha256,
                                  expected_distinct, expected_extra):
    """Pure multiset proof; every occurrence survives and counts must match.

    Public helper with explicit expectations for synthetic regression tests.
    The caller for real 002188 passes ONLY source-code pinned expectations.
    """
    if not isinstance(prior, Counter) or not isinstance(current, list):
        refuse("PINNED_HOLDER_MULTIPLICITY_INPUT_MALFORMED")
    if len(prior) != expected_distinct or sum(prior.values()) != (
            expected_distinct + expected_extra):
        refuse("PINNED_HOLDER_MULTIPLICITY_COUNT_DRIFT")
    duplicates = {}
    parsed = []
    for raw, count in prior.items():
        if not isinstance(raw, str) or type(count) is not int or count not in (1, 2):
            refuse("PINNED_HOLDER_MULTIPLICITY_OUT_OF_SCOPE")
        try:
            row = json.loads(raw)
        except (ValueError, TypeError):
            refuse("PINNED_HOLDER_INVALID_JSON")
        if not isinstance(row, dict) or encode(row, F) != raw:
            refuse("PINNED_HOLDER_RAW_IDENTITY_MISMATCH")
        if count == 2:
            if str(row.get("endDate")) != "20200930":
                refuse("PINNED_HOLDER_DUPLICATE_REPORT_PERIOD_DRIFT")
            fingerprint = digest(raw)
            if fingerprint in duplicates:
                refuse("PINNED_HOLDER_HASH_COLLISION")
            duplicates[fingerprint] = count
        parsed.extend([row] * count)
    if set(duplicates) != set(expected_raw_sha256):
        refuse("PINNED_HOLDER_DUPLICATE_HASH_SET_CHANGED")
    if len(duplicates) != expected_extra:
        refuse("PINNED_HOLDER_DUPLICATE_GROUPS_CHANGED")
    union_digest = digest(F.E.canonical_json(sorted(prior.items())))
    if union_digest != expected_union_sha256:
        refuse("PINNED_HOLDER_HISTORY_UNION_CHANGED")
    current_rows = _current(current, F)
    current_counter = _rawc(current_rows, F)
    if current_counter != prior:
        refuse("PINNED_HOLDER_QMT_CACHE_MULTIPLICITY_CHANGED")
    proof = {
        "table": "Top10Holder",
        "historical_distinct_raw_rows": len(prior),
        "historical_and_current_total_rows": sum(prior.values()),
        "verified_repeated_raw_groups": len(duplicates),
        "verified_extra_occurrences": expected_extra,
        "history_and_cache_multiset_equal": True,
        "historical_union_sha256": union_digest,
        "duplicate_row_sha256": sorted(duplicates),
        "duplicate_occurrences_each": 2,
        "same_day_duplicate_identity_proven": False,
        "source_rows_changed": False,
        "allow_deduplication": False,
        "allow_apply": False,
        "allow_pending_clear": False,
    }
    return parsed, proof


def _pinned_002188_historical(prior, current, F, evidence, ledger_sha256):
    """No waiver unless live-selected file hashes and *all nine* pinned rows match."""
    if ledger_sha256 != PINNED_002188_LEDGER_SHA256:
        refuse("PINNED_HOLDER_AUDIT_LEDGER_CHANGED")
    if (not isinstance(evidence, dict)
            or evidence.get("format") != "qmt_002188_top10holder_exact_multiplicity_pin_v1"
            or evidence.get("symbol") != "002188.SZ"
            or evidence.get("table") != "Top10Holder"
            or evidence.get("allow_deduplication") is not False
            or evidence.get("allow_apply") is not False
            or evidence.get("allow_pending_clear") is not False
            or evidence.get("ledger_sha256") != PINNED_002188_LEDGER_SHA256
            or evidence.get("historical_union_sha256") != PINNED_002188_UNION_SHA256
            or evidence.get("duplicate_row_sha256") != sorted(PINNED_002188_RAW_SHA256)
            or evidence.get("selected_snapshots") != PINNED_002188_SNAPSHOTS):
        refuse("PINNED_HOLDER_EVIDENCE_NOT_EXACT")
    # The launcher must independently obtain this dict by resolving each
    # active snapshot file and hashing its verified bytes. A supplied
    # manifest ALONE cannot establish that live files remained unchanged.
    selected = evidence.get("verified_active_snapshots")
    if selected != PINNED_002188_SNAPSHOTS:
        refuse("PINNED_HOLDER_ACTIVE_SNAPSHOT_CHANGED")
    return _check_pinned_002188_multiset(
        prior, current, F,
        expected_raw_sha256=PINNED_002188_RAW_SHA256,
        expected_union_sha256=PINNED_002188_UNION_SHA256,
        expected_distinct=779,
        expected_extra=9,
    )


def _current(fresh, F):
    if not isinstance(fresh, list) or len(fresh) > 100000:
        refuse("INVALID_CURRENT_SOURCE")
    results = []
    for row in fresh:
        if not isinstance(row, dict) or not isinstance(row.get("_index"), str):
            refuse("INVALID_CURRENT_RAW_INDEX")
        results.append({k: v for k, v in row.items() if k != "_index"})
    return results


def _projection(row, ignored, F):
    return F.E.canonical_json({k: v for k, v in row.items() if k not in ignored})


def _rawc(rows, F):
    return Counter(encode(row, F) for row in rows)


def _pairs(old, new, allowed, F, *, require_exact=False):
    if not allowed or "_index" in allowed or "endDate" in allowed:
        refuse("UNSAFE_FIELD_SCOPE")
    old_raw = _rawc(old, F)
    new_raw = _rawc(new, F)
    removed = old_raw - new_raw
    added = new_raw - old_raw
    if not removed or sum(removed.values()) != sum(added.values()):
        refuse("NO_BALANCED_RAW_REVISIONS")
    if sum(removed.values()) > MAX_PAIRS:
        refuse("TOO_MANY_REVISED_ROWS")
    old_by = defaultdict(list)
    new_by = defaultdict(list)
    for row in old:
        old_by[_projection(row, allowed, F)].append(row)
    for row in new:
        new_by[_projection(row, allowed, F)].append(row)
    if set(old_by) != set(new_by):
        refuse("REPORT_OR_BUSINESS_PROJECTION_CHANGED")
    if any(len(old_by[key]) != len(new_by[key]) for key in old_by):
        refuse("PROJECTION_CARDINALITY_CHANGED")
    changes = []
    for old_raw_value, n in sorted(removed.items()):
        if n != 1:
            refuse("REVISED_RECORD_NOT_UNIQUE")
        old_row = json.loads(old_raw_value)
        key = _projection(old_row, allowed, F)
        a = old_by[key]
        b = new_by[key]
        if len(a) != 1 or len(b) != 1:
            refuse("NONUNIQUE_PAIRING_PROJECTION")
        matched_new = b[0]
        new_raw_value = encode(matched_new, F)
        if added.get(new_raw_value) != 1:
            refuse("REVISED_COUNTERPART_NOT_UNIQUE")
        fields = sorted(k for k in set(old_row) | set(matched_new)
                        if (k not in old_row or k not in matched_new
                            or F.E.canonical_json(old_row[k]) != F.E.canonical_json(matched_new[k])))
        if not fields or not set(fields).issubset(allowed):
            refuse("UNSCOPED_FIELD_CHANGE")
        if any(field not in old_row or field not in matched_new for field in fields):
            refuse("MISSING_REVISED_FIELD")
        if require_exact and set(fields) != allowed:
            refuse("SPECIAL_FIELD_SET_CHANGED")
        changes.append({
            "old_row_sha256": digest(old_raw_value),
            "new_row_sha256": digest(new_raw_value),
            "report_endDate": old_row.get("endDate"),
            "changed_fields": fields,
            "stable_projection_sha256": digest(key),
        })
    if len(changes) != sum(added.values()):
        refuse("INCOMPLETE_REVISION_MAPPING")
    return changes


def _capital(old, new, F):
    by_old = defaultdict(list)
    by_new = defaultdict(list)

    def k(row):
        if "m_timetag" not in row or row["m_timetag"] is None or "m_quarter" not in row:
            refuse("CAPITAL_KEY_OR_QUARTER_MISSING")
        if isinstance(row["m_timetag"], (dict, list, bool)):
            refuse("CAPITAL_REPORT_KEY_INVALID")
        return F.E.canonical_json(row["m_timetag"])

    def economic(row):
        return _projection(row, frozenset(("m_quarter",)), F)

    for row in old:
        by_old[k(row)].append(row)
    for row in new:
        by_new[k(row)].append(row)
    if not by_old:
        refuse("CAPITAL_BASELINE_MISSING")
    if not set(by_old).issubset(by_new):
        refuse("CAPITAL_HISTORICAL_REPORT_KEY_REMOVED")
    added = sorted(set(by_new) - set(by_old))
    if len(added) != 1:
        refuse("CAPITAL_EXPECT_EXACTLY_ONE_ADDED_REPORT_KEY")
    if any(len(rows) != 1 for rows in by_new.values()):
        refuse("CAPITAL_DUPLICATE_CURRENT_REPORT_KEY")
    variants = 0
    for key, old_rows in by_old.items():
        observed = {economic(row) for row in old_rows}
        if len(observed) != 1 or economic(by_new[key][0]) not in observed:
            refuse("CAPITAL_HISTORIC_ECONOMIC_VARIANT_OR_DRIFT")
        variants += len(old_rows)
    candidate = by_new[added[0]][0]
    return {
        "old_report_keys": len(by_old),
        "current_report_keys": len(by_new),
        "added_report_keys": added,
        "removed_report_keys": 0,
        "historical_raw_variants_retained": variants,
        "new_report_row_sha256": digest(encode(candidate, F)),
        "economic_fields_unchanged_on_shared_keys": True,
    }



def _verify_pinned_002188_capital_scope(proof):
    """Strict audited 108->109 scope, with type-preserving date-token check.

    Refuse independently by dimension; print only counts or a hard-coded
    category, never underlying Capital values or shareholder raw records.
    """
    if not isinstance(proof, dict):
        refuse("PINNED_CAPITAL_PROOF_MALFORMED")
    if proof.get("old_report_keys") != 108:
        refuse("PINNED_CAPITAL_HISTORICAL_KEY_COUNT_DRIFT")
    if proof.get("current_report_keys") != 109:
        refuse("PINNED_CAPITAL_CURRENT_KEY_COUNT_DRIFT")
    if proof.get("historical_raw_variants_retained") != 110:
        refuse("PINNED_CAPITAL_HISTORICAL_RAW_VERSION_COUNT_DRIFT")
    if proof.get("removed_report_keys") != 0:
        refuse("PINNED_CAPITAL_REMOVED_REPORT_KEY")
    if proof.get("economic_fields_unchanged_on_shared_keys") is not True:
        refuse("PINNED_CAPITAL_SHARED_ECONOMIC_FIELD_DRIFT")
    keys = proof.get("added_report_keys")
    if not isinstance(keys, list) or len(keys) != 1:
        refuse("PINNED_CAPITAL_ADDED_KEY_COUNT_DRIFT")
    if keys[0] not in PINNED_002188_NEW_KEY_JSON:
        # Keep fail-closed even if new source uses a different date format;
        # never parse or round an unknown value into an approved date.
        refuse("PINNED_CAPITAL_ADDED_KEY_VALUE_OR_TYPE_CHANGED")
    return True


def _cross_table_capital_quarter_proof(old, new, F):
    """Only read-only evidence for m_quarter variants in an UNCHANGED-key Capital table.

    The strict raw record check must stay on all other eight tables.
    A current row may replace a historical m_quarter version only for a
    diagnostic REVIEW, while every previous row remains in immutable snapshots.
    """
    by_old = defaultdict(list)
    by_new = defaultdict(list)

    def k(row):
        value = row.get("m_timetag")
        if ("m_quarter" not in row or value is None
                or isinstance(value, (bool, list, dict))
                or str(value).strip() in ("", "0")):
            refuse("CROSS_CAPITAL_KEY_OR_QUARTER_MALFORMED")
        return F.E.canonical_json(value)

    for row in old:
        by_old[k(row)].append(row)
    for row in new:
        by_new[k(row)].append(row)
    if set(by_old) != set(by_new):
        refuse("CROSS_CAPITAL_REPORT_KEYS_CHANGED")
    if any(len(records) != 1 for records in by_new.values()):
        refuse("CROSS_CAPITAL_CURRENT_DUPLICATE_KEY")
    business = frozenset(("m_quarter",))
    mismatched_raw = 0
    historical_variants = 0
    for key, old_rows in by_old.items():
        old_economics = {_projection(row, business, F) for row in old_rows}
        if len(old_economics) != 1:
            refuse("CROSS_CAPITAL_HISTORICAL_ECONOMIC_CONFLICT")
        if old_economics != {_projection(by_new[key][0], business, F)}:
            refuse("CROSS_CAPITAL_ECONOMIC_FIELD_CHANGED")
        if len(old_rows) > 1:
            historical_variants += len(old_rows) - 1
        if _rawc(old_rows, F) != _rawc(by_new[key], F):
            mismatched_raw += 1
    # A mismatched raw row can only be due to m_quarter after complete
    # equality of all other fields, including m_timetag, on every key.
    return {
        "compatibility": "M_QUARTER_ONLY_IMMUTABLE_HISTORY_REVIEW",
        "historical_report_keys": len(by_old),
        "current_report_keys": len(by_new),
        "historical_raw_variants_extra": historical_variants,
        "raw_mismatch_report_keys": mismatched_raw,
        "report_keys_added": 0,
        "report_keys_removed": 0,
        "shared_economic_fields_equal": True,
        "preserve_original_raw_snapshots": True,
        "review_only": True,
    }

def _special(changes, code, table, evidence):
    if (not isinstance(evidence, dict)
            or evidence.get("format") != "astock_finance_source_disclosure_proof_v1"
            or evidence.get("allow_auto_clear") is not False
            or evidence.get("default_action") != "HOLD_PENDING_NO_COMMIT"):
        refuse("SPECIAL_EVIDENCE_MANIFEST_INVALID")
    matches = [case for case in evidence.get("cases", [])
               if isinstance(case, dict) and case.get("symbol") == code]
    if len(matches) != 1:
        refuse("SPECIAL_EVIDENCE_CASE_MISSING_OR_DUPLICATE")
    info = matches[0]
    if (info.get("table") != table or info.get("endDate") != "20260930"
            or info.get("manual_approval_required") is not True
            or info.get("pairing_unambiguous") is not True):
        refuse("SPECIAL_CASE_SCOPE_CHANGED")
    if len(changes) != 1:
        refuse("SPECIAL_REQUIRE_SINGLE_REVISION")
    change = changes[0]
    for field, got in (
        ("prior_record_sha256", change["old_row_sha256"]),
        ("current_record_sha256", change["new_row_sha256"]),
        ("stable_projection_sha256", change["stable_projection_sha256"])
    ):
        expected = info.get(field)
        if not isinstance(expected, str) or not HASH.fullmatch(expected) or expected != got:
            refuse("SPECIAL_RECORD_FINGERPRINT_CHANGED_" + field)
    if change["report_endDate"] != "20260930":
        refuse("SPECIAL_REPORT_PERIOD_CHANGED")
    if change["changed_fields"] != sorted(info.get("changed_fields", [])):
        refuse("SPECIAL_CHANGE_FIELDS_DIFFER")
    return {
        "source_disclosure_url": info.get("issuer_source", ""),
        "source_confirmation": info.get("issuer_confirmation", ""),
        "manual_approval_required": True,
        "original_source_row_sha256": change["old_row_sha256"],
        "current_source_row_sha256": change["new_row_sha256"],
    }


def preview_symbol(code, mode, table, historical, current_source, F, *,
                   evidence=None, ledger_sha256=None, duplicate_evidence=None):
    """Compile a deterministic *review-only* preview from verified histories.

    historical[table] is the selected immutable snapshot union from
    qmt_extra_financial_cache_import._prior_rows (Counter per table).
    current_source is the nine-table cache already read by the caller.
    Neither argument is modified. No snapshot or pending ledger is written.
    """
    if (not isinstance(code, str) or
            re.fullmatch(r"\d{6}\.(?:SZ|SH)", code) is None):
        refuse("SYMBOL_INVALID")
    if code == "688259.SH":
        refuse("KNOWN_PROVIDER_UTF8_QUARANTINE_NO_PREVIEW")
    if mode not in MODES or table not in F.E.FIN_TABLES:
        refuse("UNSUPPORTED_RECOVERY_MODE")
    if not isinstance(historical, dict) or set(historical) != set(F.E.FIN_TABLES):
        refuse("NINE_TABLE_HISTORICAL_SCOPE_MISSING")
    if not isinstance(current_source, dict) or set(current_source) != set(F.E.FIN_TABLES):
        refuse("NINE_TABLE_CURRENT_SCOPE_MISSING")
    if ledger_sha256 is not None and (not isinstance(ledger_sha256, str)
                                      or not HASH.fullmatch(ledger_sha256)):
        refuse("LEDGER_FINGERPRINT_INVALID")
    if code in SPECIAL_CODES and mode != "ISSUER_DISPUTED":
        refuse("SPECIAL_CASE_CANNOT_USE_GENERIC_POLICY")
    if code not in SPECIAL_CODES and mode == "ISSUER_DISPUTED":
        refuse("UNSCOPED_SPECIAL_CASE")
    if (mode == "CAPITAL_ADDITIVE" and table != "Capital") or (
            mode != "CAPITAL_ADDITIVE" and table == "Capital"):
        refuse("MODE_TABLE_CONFLICT")
    if mode == "HOLDER_METADATA" and table not in HOLDER_FIELDS:
        refuse("NOT_A_HOLDER_METADATA_TABLE")

    # Verify all nine histories, not just the target. Exactly one narrowly
    # pinned non-target Top10Holder multiset is allowed for 002188 Capital,
    # preserving two copies of each of nine original rows rather than
    # silently collapsing them. Every other Counter remains count==1.
    holder_duplicate_proof = None
    pinned_002188 = (code, table, mode) == (
        "002188.SZ", "Capital", "CAPITAL_ADDITIVE")
    # Keep the original Capital-only synthetic/no-duplicate pathway intact.
    # This pinned exception only activates when the historical Top10Holder
    # Counter actually contains a repeated raw record, and then ONLY with
    # the fully pinned snapshot and nine-row evidence.
    top10 = historical["Top10Holder"]
    has_repeats = (isinstance(top10, Counter)
                   and any(type(n) is int and n > 1 for n in top10.values()))
    use_pinned = pinned_002188 and has_repeats
    if duplicate_evidence is not None and not use_pinned:
        refuse("PINNED_HOLDER_EVIDENCE_UNSCOPED_OR_UNNEEDED")
    old_by_table = {}
    for t in F.E.FIN_TABLES:
        if t == "Top10Holder" and use_pinned:
            old_by_table[t], holder_duplicate_proof = _pinned_002188_historical(
                historical[t], current_source[t], F,
                duplicate_evidence, ledger_sha256)
        else:
            old_by_table[t] = _historical(historical[t], F)
    new_by_table = {t: _current(current_source[t], F) for t in F.E.FIN_TABLES}
    unaffected_additions = {}
    cross_table_capital_proof = None
    for t in F.E.FIN_TABLES:
        if t == table:
            continue
        if t == "Capital":
            # This exception applies ONLY to a non-target Capital table,
            # after all nine historical Counters have passed strict parsing.
            # Missing report keys, new report keys, and business changes
            # still BLOCK; source-history variants remain immutable.
            cross_table_capital_proof = _cross_table_capital_quarter_proof(
                old_by_table[t], new_by_table[t], F)
            if (cross_table_capital_proof["raw_mismatch_report_keys"] > 0
                    and (code, table) not in CROSS_CAPITAL_SCOPED_REVIEW):
                refuse("CROSS_CAPITAL_UNREVIEWED_SYMBOL_TABLE_SCOPE")
            unaffected_additions[t] = 0
            continue
        prior = _rawc(old_by_table[t], F)
        recent = _rawc(new_by_table[t], F)
        if prior - recent:
            refuse("OTHER_TABLE_HISTORY_LOSS_" + t)
        unaffected_additions[t] = sum((recent - prior).values())
    if mode == "CAPITAL_ADDITIVE":
        proof = _capital(old_by_table[table], new_by_table[table], F)
        if use_pinned:
            # Review remains bound to the audited 108->109/110-raw scope.
            # Preserve the provider's original m_timetag JSON scalar type.
            _verify_pinned_002188_capital_scope(proof)
        classification = "CAPITAL_ADDITIVE_REVIEW_REQUIRED"
    else:
        if mode == "HOLDER_METADATA":
            fields = HOLDER_FIELDS[table]
            changes = _pairs(old_by_table[table], new_by_table[table], fields, F)
            proof = {"revised_rows": len(changes), "pair_sha256": changes}
            classification = "HOLDER_METADATA_REVIEW_REQUIRED"
        else:
            special_fields = {
                "002178.SZ": ("Top10Holder", frozenset(("name", "type"))),
                "002310.SZ": ("Top10Holder", frozenset(("name",))),
                "002328.SZ": ("HolderNum", frozenset(("declareDate", "shareholder", "shareholderA"))),
            }
            expected_table, fields = special_fields[code]
            if table != expected_table:
                refuse("SPECIAL_CASE_TABLE_CHANGED")
            changes = _pairs(old_by_table[table], new_by_table[table], fields, F,
                             require_exact=True)
            proof = {"revised_rows": len(changes), "pair_sha256": changes,
                     "disclosure": _special(changes, code, table, evidence)}
            classification = "ISSUER_DISPUTED_REVIEW_REQUIRED"
    out = {
        "format": FORMAT,
        "symbol": code,
        "table": table,
        "classification": classification,
        "readiness": "REVIEW_ONLY_NO_APPLY_AUTHORIZATION",
        "source_version_strategy": "NEW_IMMUTABLE_SNAPSHOT_AFTER_SEPARATE_APPROVAL",
        "historical_versions_preserved": True,
        "candidate_is_parquet_snapshot": False,
        "allow_auto_clear": False,
        "allow_apply": False,
        "pending_state_changed": False,
        "snapshot_state_changed": False,
        "current_source_record_count": len(new_by_table[table]),
        "unrelated_table_new_source_rows": dict(sorted(unaffected_additions.items())),
        "cross_table_capital_quarter_proof": cross_table_capital_proof,
        "pinned_top10holder_duplicate_proof": holder_duplicate_proof,
        "ledger_before_sha256": ledger_sha256,
        "proof": proof,
    }
    # Content-addressed reproducible plan only; no actual file snapshot exists.
    out["preview_sha256"] = digest(F.E.canonical_json(out))
    return out


def preview_cohort(case_specs, historical_by_code, current_by_code, F, *,
                   evidence=None, ledger_sha256=None, expected_count=None,
                   duplicate_evidence_by_code=None):
    """Fail closed per stock; compile *only* review/quarantine outcomes.

    The caller supplies previously verified histories and existing cache data.
    No QMT calls, no re-fetch, no files, no mutations; any blocked stock
    remains blocked and is listed with a bounded, non-sensitive reason.
    """
    if not isinstance(case_specs, list) or not 1 <= len(case_specs) <= 10000:
        refuse("INVALID_COHORT_SIZE")
    if not isinstance(historical_by_code, dict) or not isinstance(current_by_code, dict):
        refuse("INVALID_COHORT_SOURCES")
    if expected_count is not None and len(case_specs) != expected_count:
        refuse("EXPECTED_COHORT_SIZE_CHANGED")
    codes = []
    for case in case_specs:
        if not isinstance(case, dict) or set(case) != {"symbol", "mode", "table"}:
            refuse("INVALID_CASE_DESCRIPTOR")
        codes.append(case["symbol"])
    if any(not isinstance(code, str) for code in codes) or len(set(codes)) != len(codes):
        refuse("DUPLICATE_OR_INVALID_COHORT_SYMBOL")
    if set(codes) != set(historical_by_code) or set(codes) != set(current_by_code):
        refuse("COHORT_CACHE_OR_HISTORY_SCOPE_MISMATCH")
    if duplicate_evidence_by_code is not None:
        if (not isinstance(duplicate_evidence_by_code, dict)
                or set(duplicate_evidence_by_code) != {"002188.SZ"}
                or "002188.SZ" not in codes):
            refuse("PINNED_HOLDER_COHORT_EVIDENCE_UNSCOPED")
    passed = []
    blocked = []
    for case in sorted(case_specs, key=lambda item: item["symbol"]):
        code = case["symbol"]
        try:
            p = preview_symbol(
                code, case["mode"], case["table"], historical_by_code[code],
                current_by_code[code], F,
                evidence=evidence, ledger_sha256=ledger_sha256,
                duplicate_evidence=(
                    duplicate_evidence_by_code.get(code)
                    if duplicate_evidence_by_code else None))
            passed.append({
                "symbol": code, "table": case["table"],
                "classification": p["classification"],
                "preview_sha256": p["preview_sha256"],
            })
        except ReviewBlocked as exc:
            blocked.append({"symbol": code, "table": case["table"],
                            "reason": str(exc)[:160]})
    out = {
        "format": FORMAT + "_cohort_v1",
        "symbols": len(codes),
        "review_only": len(passed),
        "blocked": len(blocked),
        "evidence_only": passed,
        "quarantined": blocked,
        "ledger_before_sha256": ledger_sha256,
        "allow_auto_clear": False,
        "allow_apply": False,
        "records_modified": False,
        "snapshots_modified": False,
    }
    out["cohort_sha256"] = digest(F.E.canonical_json(out))
    return out
