#!/usr/bin/env python3
"""Read-only nine-table guard for a possible Capital.m_quarter repair pilot.

ALL writes are disabled. Check one to five explicitly named pending securities
using QMT's existing local cache, without financial history downloads.
The full historical ACTIVE union of each of nine financial tables is verified.
No changes to Parquet, private finance ledgers, or pending status.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_semantic_proof as P
import qmt_capital_conflict_census_readonly as C

FORMAT = "qmt_capital_nine_table_preview_v1"
MAX_STOCKS = 5


def plan_symbol(extra, code, asof, tables):
    """Conservative pilot plan: Capital only m_quarter; other 8 tables EXACT."""
    if set(tables) != set(E.FIN_TABLES):
        return {"status": "REVIEW_REQUIRED",
                "blockers": ["MISSING_NINE_TABLE_PAYLOAD"],
                "table_checks": {}, "would_modify_parquet": False}
    checks = {}
    blockers = []
    evidence = {}
    for table in E.FIN_TABLES:
        fresh = tables[table]
        if (not isinstance(fresh, list) or len(fresh) > 100000
                or any(not isinstance(row, dict) or
                       not isinstance(row.get("_index"), str) for row in fresh)):
            blockers.append(table + ":INVALID_SOURCE_RECORDS")
            continue
        old_asof, prior = I._prior_rows(extra, code, table)
        # Frozen preflight evidence, not an authorization. On any later apply
        # the live source and all historical immutable snapshots must be
        # re-read under the SAME writer lock and match these exact hashes.
        prior_payload = (sorted(prior.items()) if prior else [])
        current_payload = sorted(I._rows(fresh).items())
        evidence[table] = {
            "latest_observation_asof": old_asof,
            "historical_selected_union_sha256": hashlib.sha256(
                E.canonical_json(prior_payload).encode("utf-8")).hexdigest(),
            "current_raw_source_sha256": hashlib.sha256(
                E.canonical_json(current_payload).encode("utf-8")).hexdigest(),
            "source_rows": len(fresh)}
        if old_asof is not None and old_asof > asof:
            blockers.append(table + ":SOURCE_OBSERVATION_OLDER_THAN_BASELINE")
            continue
        if table == "Capital":
            proof = P.prove_historical_union(prior or Counter(), fresh)
            checks[table] = {
                "status": proof["classification"],
                "changed_m_quarter_rows": proof["m_quarter_differences"],
                "report_dates": proof["history_report_dates"],
                "historical_raw_variants": proof["historical_raw_variants"],
                "ready_to_commit": False}
            if proof["classification"] != "M_QUARTER_ONLY_CANDIDATE":
                blockers.append(table + ":" + proof["classification"])
            continue
        old = prior or Counter()
        new = I._rows(fresh)
        missing = sum((old - new).values())
        additions = sum((new - old).values())
        checks[table] = {
            "status": ("UNCHANGED" if not missing and not additions
                       else "HISTORY_REMOVED_OR_REVISED" if missing
                       else "NEW_RECORDS_REQUIRE_INDEPENDENT_REVIEW"),
            "prior_rows": sum(old.values()),
            "fresh_rows": sum(new.values()),
            "missing_rows": missing,
            "new_rows": additions}
        if missing or additions:
            blockers.append(table + ":" + checks[table]["status"])
    eligible = not blockers and len(evidence) == len(E.FIN_TABLES)
    candidate_file = None
    if eligible:
        # Predict content-addressed immutable filename entirely in memory.
        # No path creation, no pin changes and no Parquet serialization.
        capital = E.snapshot_table(asof, code, "Capital", tables["Capital"])
        candidate_file = E._snapshot_path(
            extra, "financial/Capital/" + code, asof, capital).name
    frozen = {
        "symbol": code, "asof": asof, "table_evidence": evidence,
        "proposed_capital_immutable_filename": candidate_file}
    digest = (hashlib.sha256(E.canonical_json(frozen).encode("utf-8")).hexdigest()
              if eligible else None)
    return {
        "status": ("ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW" if eligible
                   else "REVIEW_REQUIRED"),
        "blockers": blockers, "table_checks": checks,
        "evidence": evidence if eligible else {},
        "read_only_preflight_digest": digest,
        "proposed_capital_immutable_filename": candidate_file,
        "preflight_digest_is_apply_authorization": False,
        "proposed_action": (
            "VERSIONED_CAPITAL_SNAPSHOT_PLUS_EXPLICIT_AUDIT_AND_PENDING_RELEASE"
            if not blockers else "NONE"),
        "requires_separate_authorization": True,
        "would_modify_parquet": False,
        "pending_modified": False,
        "all_nine_financial_tables_checked": len(checks) == len(E.FIN_TABLES),
        "notes": "Proof is not permission to apply; never delete existing raw versions."
    }


def preview(root, repo, symbols, *, worker=None, progress=print,
            timeout_seconds=180):
    if not 1 <= len(symbols) <= MAX_STOCKS or symbols != sorted(set(symbols)):
        raise ValueError("Provide 1..5 distinct, sorted stock symbols")
    for code in symbols:
        if E.valid_code(code) != code:
            raise ValueError("Invalid symbol: " + str(code))
    if not 30 <= timeout_seconds <= 3600:
        raise ValueError("Invalid worker timeout")
    repo = Path(repo).resolve()
    source_repo = Path(__file__).resolve().parent.parent
    if source_repo != repo:
        raise ValueError("CANONICAL_CHECKOUT_REQUIRED_FOR_CACHE_ONLY_PREVIEW")
    extra = E._storage(Path(root))
    ledger = repo / "ParquetLiveSync" / "work" / "qmt_extra" / I.STATE_FILE
    if not ledger.is_file() or ledger.is_symlink():
        raise ValueError("Missing canonical private finance ledger")
    sha_before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    asof = datetime.now(E.L.UTC8).date().isoformat()
    if worker is None:
        worker = I._worker_batch
    observations = {}
    with tempfile.TemporaryDirectory(prefix="qmt-nine-table-preview-") as tmp:
        with E.LIVE.exclusive_writer():
            # Check under SAME market writer lock as the cache read/verification.
            sha_locked = hashlib.sha256(ledger.read_bytes()).hexdigest()
            if sha_before != sha_locked:
                raise ValueError("Private finance ledger changed before lock")
            state = I._state(extra, repo / "ParquetLiveSync" / "work" / "qmt_extra")
            for code in symbols:
                entry = state["pending"].get(code)
                if not (isinstance(entry, dict)
                        and entry.get("reason") == "SOURCE_HISTORY_CONFLICT"
                        and C.conflict_table(entry) == "Capital"):
                    raise ValueError("Only existing pending Capital conflicts allowed: " + code)
            recovered = I._recover_utf8_group(
                worker, symbols, "cache", asof, 120, Path(tmp),
                timeout_seconds, progress=lambda line: None)
            for code, tables, reason in recovered:
                if reason is not None:
                    observations[code] = {"status": "REVIEW_REQUIRED",
                                          "blockers": ["CACHE:" + reason]}
                else:
                    observations[code] = plan_symbol(extra, code, asof, tables)
                progress("QMT_CAPITAL_NINE_TABLE_STOCK_PREVIEW=" +
                         E.canonical_json({"symbol": code,
                                           **observations[code]}))
            if hashlib.sha256(ledger.read_bytes()).hexdigest() != sha_before:
                raise ValueError("Private finance ledger changed during preview")
    return {
        "format": FORMAT, "asof": asof,
        "status": "READONLY_PREVIEW_COMPLETE",
        "financial_pending_ledger_sha256": sha_before,
        "repair_transaction_implemented": False,
        "symbols": symbols, "sampled": len(observations),
        "eligible_for_separate_manual_pilot": sum(
            x["status"] == "ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW"
            for x in observations.values()),
        "review_required": sum(
            x["status"] != "ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW"
            for x in observations.values()),
        "results": observations, "historical_parquet_modified": False,
        "pending_modified": False, "download_called": False,
        "repair_apply_enabled": False,
        "worker_group_size": len(symbols)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("D:/ChatGPT/AStockDataTools"))
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--symbols", default="002237.SZ",
                        help="1..5 comma-separated sorted existing Capital pending securities")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    symbols = args.symbols.split(",")
    report = preview(args.root, args.repo, symbols,
                     timeout_seconds=args.timeout_seconds)
    print("QMT_CAPITAL_NINE_TABLE_PREVIEW=" + E.canonical_json(report))


if __name__ == "__main__":
    main()
