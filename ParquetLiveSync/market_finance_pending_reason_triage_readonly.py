#!/usr/bin/env python3
"""Pinned, read-only physical triage of one existing finance-cache pending ledger.

Aggregates known reasons, immutable-union conflict detail patterns, retry
attempts, and saved asof dates. No stock lists, QMT, downloads or writes.
This is NOT provider authentication or any repair/approval/waiver.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import re

import market_finance_adjustment_progress_readonly as LEDGER
import qmt_extra_data as EXTRA

FORMAT = 'astock_finance_pending_reason_triage_readonly_v1'
STATUS = 'PINNED_SAVED_FINANCE_PENDING_CATEGORIES_ONLY_NO_HISTORY_REPAIR'
NAME = 'financial-cache-progress.json'
HEX = re.compile(r'^[0-9a-fA-F]{64}$')
RAW_CONFLICT = re.compile(
    r'^SOURCE_HISTORY_CONFLICT (?P<symbol>\d{6}\.(?:SH|SZ|BJ)) '
    r'table=(?P<table>[A-Za-z][A-Za-z0-9]*) '
    r'removed_or_revised=(?P<count>\d+)$')
SCOPED_CONFLICT = re.compile(
    r'^SOURCE_HISTORY_CONFLICT (?P<symbol>\d{6}\.(?:SH|SZ|BJ)) '
    r'table=Capital scoped_m_quarter_proof=(?P<proof>[A-Z0-9_]+)$')
KNOWN_SCOPED_PROOFS = frozenset((
    'BASELINE_MISSING', 'HISTORICAL_DUPLICATE_RAW_RECORD',
    'M_QUARTER_FIELD_MISSING', 'FRESH_DUPLICATE_REPORT_KEY',
    'REPORT_KEYS_ADDED_OR_REMOVED', 'HISTORICAL_BUSINESS_FIELD_REVISION',
    'BUSINESS_OR_DATE_FIELD_CHANGED', 'M_QUARTER_ONLY_CANDIDATE',
    'NO_CHANGE', 'UNVERIFIED_MALFORMED_OR_UNKEYED_RECORD'))
MAX_PENDING = 10000


class TriageError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise TriageError(code)


def _asof(value):
    if value is None:
        return None
    need(type(value) is str and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)),
         'PENDING_ASOF_INVALID')
    try:
        need(date.fromisoformat(value).isoformat() == value,
             'PENDING_ASOF_INVALID')
    except ValueError as exc:
        raise TriageError('PENDING_ASOF_INVALID') from exc
    return value


def _attempt_bucket(value):
    need(type(value) is int and value >= 1, 'PENDING_ATTEMPTS_INVALID')
    return ('1' if value == 1 else '2-3' if value <= 3
            else '4-9' if value <= 9 else '10+')


def _conflict_kind(symbol, detail):
    # Only a fully anchored exact code/table pattern is strong enough to
    # classify a source-history conflict from untrusted mutable detail text.
    if type(detail) is not str or len(detail) > 300:
        return 'UNCLASSIFIED_DETAIL', None
    raw = RAW_CONFLICT.fullmatch(detail)
    if (raw and raw['symbol'] == symbol
            and raw['table'] in EXTRA.FIN_TABLES
            and int(raw['count']) > 0):
        return 'RAW_HISTORICAL_VARIANT_REMOVED_OR_REVISED', raw['table']
    scoped = SCOPED_CONFLICT.fullmatch(detail)
    if scoped and scoped['symbol'] == symbol and scoped['proof'] in KNOWN_SCOPED_PROOFS:
        return 'SCOPED_CAPITAL_PROOF_' + scoped['proof'], 'Capital'
    return 'UNCLASSIFIED_DETAIL', None


def inspect(module_root, stock_root, expected_sha256):
    need(type(expected_sha256) is str and bool(HEX.fullmatch(expected_sha256)),
         'EXPECTED_LEDGER_SHA_REQUIRED')
    directory, expected_root = LEDGER._roots(module_root, stock_root)
    dir_before = LEDGER._identity(os.stat(directory, follow_symlinks=False))
    before = LEDGER._bytes(directory, NAME)
    need(before is not None, 'EXPLICIT_FINANCIAL_CACHE_LEDGER_MISSING')
    need(before['sha256'] == expected_sha256.lower(),
         'PINNED_FINANCIAL_CACHE_LEDGER_SHA_MISMATCH')
    state = LEDGER._cache(before['data'], expected_root)
    pending = before['data']['pending']
    need(type(pending) is dict and len(pending) <= MAX_PENDING,
         'PENDING_BUDGET_INVALID')
    reasons, attempts, attempts_by_reason = Counter(), Counter(), {}
    asof_months, observed_dates = Counter(), []
    asof_missing = 0
    details, tables = Counter(), Counter()
    for symbol, entry in pending.items():
        # _cache validated base reason and attempts, and the strict root.
        need(type(symbol) is str and symbol and
             type(entry) is dict, 'PENDING_ENTRY_INVALID')
        reason = entry['reason']
        reasons[reason] += 1
        bucket = _attempt_bucket(entry['attempts'])
        attempts[bucket] += 1
        attempts_by_reason.setdefault(reason, Counter())[bucket] += 1
        asof = _asof(entry.get('asof'))
        if asof is None:
            asof_missing += 1
        else:
            observed_dates.append(asof)
            asof_months[asof[:7]] += 1
        if reason == 'SOURCE_HISTORY_CONFLICT':
            classification, table = _conflict_kind(symbol, entry.get('detail'))
            details[classification] += 1
            if table is not None:
                tables[table] += 1
    need(sum(reasons.values()) == len(pending)
         and sum(attempts.values()) == len(pending)
         and sum(details.values()) == reasons['SOURCE_HISTORY_CONFLICT']
         and asof_missing + len(observed_dates) == len(pending),
         'PENDING_AGGREGATE_CONSERVATION_FAILED')

    after = LEDGER._bytes(directory, NAME)
    need(after is not None
         and after['sha256'] == before['sha256']
         and after['identity'] == before['identity']
         and after['bytes'] == before['bytes']
         and LEDGER._identity(os.stat(directory, follow_symlinks=False))
         == dir_before,
         'PINNED_FINANCIAL_CACHE_LEDGER_CHANGED_DURING_TRIAGE')
    return {
        'format': FORMAT, 'status': STATUS,
        'explicit_ledger_relative_to_module': 'work/qmt_extra/' + NAME,
        'physical_ledger_sha256': before['sha256'],
        'physical_ledger_bytes': before['bytes'],
        'ledger_saved_daily_date': state['daily_date'],
        'ledger_saved_daily_cursor': state['daily_cursor'],
        'ledger_saved_daily_sweep_reached_end':
            state['daily_sweep_reached_end'],
        'ledger_saved_pending_count': state['pending_count'],
        'pending_reason_counts': dict(sorted(reasons.items())),
        'pending_attempts_buckets': dict(sorted(attempts.items())),
        'pending_attempts_by_reason': {
            reason: dict(sorted(buckets.items()))
            for reason, buckets in sorted(attempts_by_reason.items())},
        'pending_asof_month_counts': dict(sorted(asof_months.items())),
        'pending_asof_earliest': min(observed_dates) if observed_dates else None,
        'pending_asof_latest': max(observed_dates) if observed_dates else None,
        'pending_asof_missing': asof_missing,
        'source_history_conflict_detail_classes': dict(sorted(details.items())),
        'source_history_conflict_table_counts_if_exact_detail':
            dict(sorted(tables.items())),
        'unparsed_source_conflicts_not_assumed_safe':
            details['UNCLASSIFIED_DETAIL'],
        'raw_history_data_compared': False,
        'financial_source_provider_authenticated': False,
        'full_history_coverage_certified': False,
        'mutable_ledger_is_original_20261125_receipt': False,
        'original_run_receipt_authenticated': False,
        'original_quarantines_cleared': False,
        'financial_repair_authorized': False,
        'market_files_written': False,
        'qmt_cache_queried_or_modified': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--stock-root', type=Path, required=True)
    parser.add_argument('--expected-ledger-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(args.module_root, args.stock_root,
                                 args.expected_ledger_sha256),
                         ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False))
        return 0
    except (TriageError, LEDGER.ProgressError, ValueError, TypeError,
            OSError, RuntimeError, KeyError) as exc:
        # Do not reveal stock codes, pending contents or absolute private paths.
        print('FINANCIAL_PENDING_REASON_TRIAGE_REVIEW_REQUIRED: '
              + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
