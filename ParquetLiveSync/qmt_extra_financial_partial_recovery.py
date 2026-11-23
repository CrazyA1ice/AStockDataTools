#!/usr/bin/env python3
"""One-stock, one-table-excluded QMT finance recovery.

A known source UTF-8 decoding failure must not prevent independent healthy
financial tables from being captured. No downloads; never clear pending.
Official eight-cycle / H5 files and the pending JSON are not modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import re

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

KNOWN_SYMBOL = "688259.SH"
KNOWN_BAD_TABLE = "Top10Holder"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PartialRecoveryBlocked(ValueError):
    pass


def _ledger_identity(root, workspace, expected_sha):
    extra = E._storage(Path(root))
    ledger = I._state_file(workspace)
    if not ledger.is_file() or ledger.is_symlink():
        raise PartialRecoveryBlocked("MISSING_CANONICAL_FINANCIAL_LEDGER")
    digest = hashlib.sha256(ledger.read_bytes()).hexdigest()
    if digest != expected_sha:
        raise PartialRecoveryBlocked("FINANCIAL_LEDGER_SHA_CHANGED")
    state = I._state(extra, workspace)
    pending = state["pending"]
    if (len(pending) != 1 or KNOWN_SYMBOL not in pending or
            pending[KNOWN_SYMBOL]["reason"] != "CACHE_DECODE_ERROR"):
        raise PartialRecoveryBlocked("ONLY_KNOWN_TOP10HOLDER_DECODE_PENDING_ALLOWED")
    return extra, ledger


def _allow_time(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise PartialRecoveryBlocked("TIMEZONE_AWARE_CLOCK_REQUIRED")
    market = now.astimezone(E.L.UTC8)
    minute = market.hour * 60 + market.minute
    if 19 * 60 + 20 <= minute < 20 * 60 + 40:
        raise PartialRecoveryBlocked("PROTECTED_2005_MARKET_WRITER_WINDOW")
    return market.date().isoformat()


def _read_healthy_tables(xt, code=KNOWN_SYMBOL):
    source = {}
    counts = {}
    for table in E.FIN_TABLES:
        if table in (KNOWN_BAD_TABLE, "PerShare"):
            # PerShare is independently observed as optional/empty. Retain any
            # earlier version without spending another QMT cache API read.
            source[table] = []
            continue
        # Explicitly independent API requests: do not use the all-nine
        # get_financial_data call that fails on the one damaged Top10Holder.
        received = xt.get_financial_data(
            [code], [table], start_time="", end_time="",
            report_type="report_time")
        if (type(received) is not dict or
                set(received) - {code}):
            raise PartialRecoveryBlocked("BAD_SINGLE_TABLE_PROVIDER_ENVELOPE")
        group = received.get(code)
        if group is None:
            rows = []
        else:
            if type(group) is not dict or set(group) - {table}:
                raise PartialRecoveryBlocked("BAD_SINGLE_TABLE_PROVIDER_REPLY")
            rows = E.dataframe_records(group.get(table))
        if (len(rows) > 100000 or any(
                type(row) is not dict or
                type(row.get("_index")) is not str for row in rows)):
            raise PartialRecoveryBlocked("BAD_SINGLE_TABLE_SOURCE_SHAPE")
        source[table] = rows
        counts[table] = len(rows)
    if (set(source) != set(E.FIN_TABLES)
            or not any(counts[name] for name in E.FIN_TABLES
                       if name not in (KNOWN_BAD_TABLE, "PerShare"))):
        raise PartialRecoveryBlocked("NO_VERIFIED_HEALTHY_CORE_TABLES")
    return source, counts


def recover(root, workspace, expected_sha, *, xt, apply=False,
            now=None, progress=print):
    if not SHA_RE.fullmatch(expected_sha):
        raise PartialRecoveryBlocked("BAD_EXPECTED_FINANCIAL_LEDGER_SHA")
    workspace = Path(workspace)
    asof = _allow_time(now or datetime.now(E.L.UTC8))
    extra, ledger = _ledger_identity(root, workspace, expected_sha)
    preflight = {
        "status": "QMT_FINANCE_PARTIAL_TOP10HOLDER_PREFLIGHT",
        "symbol": KNOWN_SYMBOL, "bad_table": KNOWN_BAD_TABLE,
        "pending_reason": "CACHE_DECODE_ERROR",
        "ledger_sha256_verified": True, "can_download": False,
        "market_files_modified": False, "pending_unchanged": True,
        "source_completeness_verified": False, "asof": asof,
    }
    if not apply:
        progress("QMT_FINANCE_PARTIAL_PREFLIGHT=" + E.canonical_json(preflight))
        return preflight
    # If run from a detached worktree, share the canonical main-repository
    # lock adjacent to the official financial ledger rather than an unrelated
    # review-worktree lock.
    former_writer_workspace = E.LIVE.WORK
    E.LIVE.WORK = workspace.parent
    try:
        with E.LIVE.exclusive_writer():
            _ledger_identity(root, workspace, expected_sha)
            source, counts = _read_healthy_tables(xt)
            if _allow_time(datetime.now(E.L.UTC8)) != asof:
                raise PartialRecoveryBlocked("MARKET_DATE_CHANGED_DURING_CACHE_READ")
            _ledger_identity(root, workspace, expected_sha)
            # Existing, tested immutable writer. Top10Holder is deliberately []
            # and its old snapshot is retained by QMT-primary-versioned policy.
            report = I._commit_symbol(
                extra, workspace, KNOWN_SYMBOL, asof, source,
                qmt_primary_versioned=True)
            # The pending ledger MUST retain the bad Top10Holder identity.
            _ledger_identity(root, workspace, expected_sha)
    finally:
        E.LIVE.WORK = former_writer_workspace
    result = {
        "status": "QMT_FINANCE_PARTIAL_HEALTHY_TABLES_COMMITTED",
        "symbol": KNOWN_SYMBOL, "excluded_bad_table": KNOWN_BAD_TABLE,
        "readable_table_rows": counts, "excluded_table_read_calls": 0,
        "optional_pershare_read_calls": 0,
        "download_calls": 0, "new_snapshots": sum(
            item["action"] == "CREATE_VERSION" for item in report.values()),
        "bad_table_action": report[KNOWN_BAD_TABLE]["action"],
        "pending_remaining": True,
        "pending_reason": "CACHE_DECODE_ERROR",
        "financial_original_values_emitted": False,
        "source_completeness_verified": False,
        "market_eight_cycles_modified": False, "h5_modified": False,
    }
    progress("QMT_FINANCE_PARTIAL_COMMIT=" + E.canonical_json(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected-progress-sha256", required=True)
    parser.add_argument("--symbol", choices=(KNOWN_SYMBOL,), required=True)
    parser.add_argument("--excluded-table", choices=(KNOWN_BAD_TABLE,),
                        required=True)
    parser.add_argument("--explicit-qmt-primary", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and not args.explicit_qmt_primary:
        parser.error("Explicit --explicit-qmt-primary required for writing")
    if args.apply:
        from xtquant import xtdata
        xt = xtdata
    else:
        xt = None
    recover(args.root, args.workspace, args.expected_progress_sha256,
            xt=xt, apply=args.apply)


if __name__ == "__main__":
    main()
