#!/usr/bin/env python3
"""Bounded read-only physical inventory of PRIOR immutable financial snapshots.

Only table+stock scopes derived from exactly SHA-pinned existing conflict
entries. No QMT, fresh financial data, Parquet payload parsing or mutations.
A physical snapshot is NOT proof that a source/revision can be admitted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

import market_finance_adjustment_progress_readonly as LEDGER
import market_finance_pending_reason_triage_readonly as TRIAGE
import qmt_extra_data as EXTRA

FORMAT = 'astock_prior_financial_snapshot_census_readonly_v1'
STATUS = 'PRIOR_SNAPSHOT_PHYSICAL_BYTES_ONLY_NO_FINANCE_SOURCE_RECONCILIATION'
NAME = TRIAGE.NAME
SNAPSHOT = re.compile(r'^(\d{4}-\d{2}-\d{2})-[0-9a-f]{16}\.parquet$')
MAX_CONFLICT_SCOPES = 128
MAX_DIRECT_ENTRIES = 256
MAX_TOTAL_FILES = 4096
MAX_SINGLE_FILE_BYTES = 24 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 512 * 1024 * 1024
MAX_PIN_FILE_BYTES = 16384


class SnapshotError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise SnapshotError(reason)


def _identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode


def _dir(directory, *, optional=False):
    need(not directory.is_symlink(), 'PRIOR_SNAPSHOT_LINKED_DIRECTORY')
    if not directory.exists():
        if optional:
            return False
        raise SnapshotError('PRIOR_SNAPSHOT_PARENT_DIRECTORY_MISSING')
    need(directory.is_dir(), 'PRIOR_SNAPSHOT_NON_DIRECTORY')
    return True


def _read_file(path, limit, *, with_data=False):
    need(not path.is_symlink(), 'PRIOR_SNAPSHOT_SYMLINK_FORBIDDEN')
    info = os.stat(path, follow_symlinks=False)
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit,
         'PRIOR_SNAPSHOT_FILE_SIZE_OR_TYPE_INVALID')
    try:
        with path.open('rb') as reader:
            opened = os.fstat(reader.fileno())
            need(_identity(info) == _identity(opened),
                 'PRIOR_SNAPSHOT_FILE_CHANGED')
            h = sha256()
            consumed = 0
            buffer = bytearray() if with_data else None
            while True:
                blob = reader.read(1024 * 1024)
                if not blob:
                    break
                consumed += len(blob)
                need(consumed <= limit, 'PRIOR_SNAPSHOT_FILE_BUDGET_EXCEEDED')
                h.update(blob)
                if with_data:
                    buffer.extend(blob)
            closed = os.fstat(reader.fileno())
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SnapshotError('PRIOR_SNAPSHOT_FILE_READ_FAILED') from exc
    need(consumed == info.st_size
         and _identity(info) == _identity(opened)
         == _identity(closed) == _identity(after)
         and not path.is_symlink(),
         'PRIOR_SNAPSHOT_FILE_CHANGED')
    return (h.hexdigest(), consumed, bytes(buffer)) if with_data else (
        h.hexdigest(), consumed)


def _snapshot_names(folder):
    before = _identity(os.stat(folder, follow_symlinks=False))
    names = []
    with os.scandir(folder) as entries:
        for entry in entries:
            names.append(entry.name)
            need(len(names) <= MAX_DIRECT_ENTRIES,
                 'PRIOR_SNAPSHOT_DIRECT_ENTRY_LIMIT')
            need(not entry.name.startswith('.'),
                 'PRIOR_SNAPSHOT_UNEXPECTED_DIRECT_ENTRY')
            m = SNAPSHOT.fullmatch(entry.name)
            need(m is not None, 'PRIOR_SNAPSHOT_UNEXPECTED_DIRECT_ENTRY')
            try:
                need(date.fromisoformat(m.group(1)).isoformat() == m.group(1),
                     'PRIOR_SNAPSHOT_FILENAME_DATE_INVALID')
            except ValueError as exc:
                raise SnapshotError('PRIOR_SNAPSHOT_FILENAME_DATE_INVALID') from exc
    need(_identity(os.stat(folder, follow_symlinks=False)) == before,
         'PRIOR_SNAPSHOT_DIRECTORY_CHANGED')
    return sorted(names), before


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        need(key not in obj, 'PRIOR_SNAPSHOT_ACTIVE_PIN_DUPLICATE_JSON_KEY')
        obj[key] = value
    return obj


def _active_pin(folder, stock, table, day, files):
    active = folder.parent / 'active'
    if not _dir(active, optional=True):
        return 'LEGACY_UNPINNED_UNIQUE' if len(files) == 1 else 'MULTIPLE_VERSIONS_NO_PIN_REVIEW'
    pin = active / (day + '.json')
    need(not pin.is_symlink(), 'PRIOR_SNAPSHOT_ACTIVE_PIN_LINK')
    if not pin.exists():
        return 'LEGACY_UNPINNED_UNIQUE' if len(files) == 1 else 'MULTIPLE_VERSIONS_NO_PIN_REVIEW'
    digest, size, raw_pin = _read_file(
        pin, MAX_PIN_FILE_BYTES, with_data=True)
    need(0 < size <= MAX_PIN_FILE_BYTES and len(digest) == 64,
         'PRIOR_SNAPSHOT_ACTIVE_PIN_BYTES_INVALID')
    try:
        data = json.loads(raw_pin.decode('utf-8-sig'),
                          object_pairs_hook=_unique_pairs)
    except SnapshotError:
        raise
    except (UnicodeError, ValueError, OSError) as exc:
        raise SnapshotError('PRIOR_SNAPSHOT_ACTIVE_PIN_INVALID_JSON') from exc
    need(type(data) is dict
         and set(data) == {'format', 'symbol', 'table', 'asof', 'filename', 'sha256'}
         and data['format'] == 'qmt_financial_active_v1'
         and data['symbol'] == stock
         and data['table'] == table
         and data['asof'] == day
         and type(data['filename']) is str
         and data['filename'] in files
         and type(data['sha256']) is str
         and bool(TRIAGE.HEX.fullmatch(data['sha256'])),
         'PRIOR_SNAPSHOT_ACTIVE_PIN_FIELDS_INVALID')
    return data


def inspect(module_root, stock_root, expected_ledger_sha256):
    need(type(expected_ledger_sha256) is str
         and bool(TRIAGE.HEX.fullmatch(expected_ledger_sha256)),
         'PINNED_LEDGER_SHA_REQUIRED')
    directory, extra_string = LEDGER._roots(module_root, stock_root)
    extra = Path(extra_string)
    ledger = LEDGER._bytes(directory, NAME)
    need(ledger is not None
         and ledger['sha256'] == expected_ledger_sha256.lower(),
         'PINNED_LEDGER_SHA_MISMATCH')
    state = LEDGER._cache(ledger['data'], extra_string)
    scopes = []
    for stock, entry in ledger['data']['pending'].items():
        if entry['reason'] != 'SOURCE_HISTORY_CONFLICT':
            continue
        classification, table = TRIAGE._conflict_kind(stock, entry.get('detail'))
        need(classification != 'UNCLASSIFIED_DETAIL'
             and table in EXTRA.FIN_TABLES,
             'PINNED_SOURCE_CONFLICT_SCOPE_UNCLASSIFIED')
        scopes.append((table, stock, classification))
    need(len(scopes) <= MAX_CONFLICT_SCOPES,
         'PRIOR_SNAPSHOT_STOCK_SCOPE_BUDGET')
    scopes.sort()

    by_table = defaultdict(Counter)
    pin_status = Counter()
    physical_files = 0
    physical_bytes = 0
    scope_present = 0
    scope_missing = 0
    physical_manifest = sha256()
    base = extra / 'financial'
    if scopes:
        _dir(base, optional=False)
    for table, stock, classification in scopes:
        table_dir = base / table
        stock_dir = table_dir / stock
        folder = stock_dir / 'snapshots'
        exists = True
        for part in (table_dir, stock_dir, folder):
            if not _dir(part, optional=True):
                exists = False
                break
        counts = by_table[table]
        counts['source_conflict_scopes'] += 1
        if not exists:
            counts['no_snapshot_directory'] += 1
            scope_missing += 1
            continue
        names, dir_before = _snapshot_names(folder)
        scope_present += 1
        counts['existing_snapshot_directory'] += 1
        if not names:
            counts['empty_snapshot_directory'] += 1
            continue
        sha_by_file = {}
        by_day = defaultdict(list)
        for name in names:
            need(physical_files < MAX_TOTAL_FILES,
                 'PRIOR_SNAPSHOT_TOTAL_FILE_BUDGET')
            path = folder / name
            need(not path.is_symlink(), 'PRIOR_SNAPSHOT_SYMLINK_FORBIDDEN')
            info = os.stat(path, follow_symlinks=False)
            need(stat.S_ISREG(info.st_mode)
                 and 0 < info.st_size <= MAX_SINGLE_FILE_BYTES
                 and physical_bytes + info.st_size <= MAX_TOTAL_FILE_BYTES,
                 'PRIOR_SNAPSHOT_TOTAL_BYTES_OR_SINGLE_FILE_BUDGET')
            digest, size = _read_file(path, MAX_SINGLE_FILE_BYTES)
            physical_files += 1
            physical_bytes += size
            sha_by_file[name] = digest
            by_day[name[:10]].append(name)
            physical_manifest.update(json.dumps(
                [table, stock, name, digest, size],
                separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\n')
        counts['physical_snapshot_files_sha_verified'] += len(names)
        counts['historical_asof_dates_observed'] += len(by_day)
        for day, names_for_day in sorted(by_day.items()):
            selected = _active_pin(folder, stock, table, day, names_for_day)
            if isinstance(selected, dict):
                need(sha_by_file[selected['filename']] == selected['sha256'],
                     'PRIOR_SNAPSHOT_ACTIVE_PIN_PHYSICAL_SHA_MISMATCH')
                status = 'ACTIVE_PIN_SELECTED_BYTES_MATCH'
            else:
                status = selected
            pin_status[status] += 1
            counts['asof_'+status] += 1
        need(_identity(os.stat(folder, follow_symlinks=False)) == dir_before,
             'PRIOR_SNAPSHOT_DIRECTORY_CHANGED')
        # The filename's short hash names canonical Arrow row data, NOT the
        # SHA of the physical Parquet bytes; never equate them.

    final_ledger = LEDGER._bytes(directory, NAME)
    need(final_ledger is not None
         and final_ledger['sha256'] == ledger['sha256']
         and final_ledger['identity'] == ledger['identity'],
         'PINNED_LEDGER_CHANGED_DURING_SNAPSHOT_CENSUS')
    need(sum(v['source_conflict_scopes'] for v in by_table.values())
         == len(scopes), 'PRIOR_SNAPSHOT_SCOPE_COUNT_INCONSISTENT')
    return {
        'format': FORMAT, 'status': STATUS,
        'pinned_ledger_sha256': ledger['sha256'],
        'pinned_ledger_pending_count': state['pending_count'],
        'scopes_from_exact_conflict_details': len(scopes),
        'conflict_scopes_with_snapshot_directory': scope_present,
        'conflict_scopes_missing_snapshot_directory': scope_missing,
        'physical_snapshot_files_sha_verified': physical_files,
        'physical_snapshot_bytes_hashed': physical_bytes,
        'physical_snapshot_manifest_sha256': physical_manifest.hexdigest(),
        'asof_active_pin_resolution_status_counts': dict(sorted(pin_status.items())),
        'table_scoped_counts': {
            table: dict(sorted(values.items()))
            for table, values in sorted(by_table.items())},
        'only_existing_prior_snapshots_scanned': True,
        'new_finance_source_consulted': False,
        'parquet_row_or_history_union_verified': False,
        'original_qmt_source_authenticated': False,
        'all_source_history_conflicts_resolved': False,
        'financial_repair_authorized': False,
        'original_run_receipt_authenticated': False,
        'original_quarantines_cleared': False,
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
                         sort_keys=True, indent=2, ensure_ascii=False,
                         allow_nan=False))
        return 0
    except (SnapshotError, LEDGER.ProgressError, TRIAGE.TriageError,
            ValueError, OSError, RuntimeError, TypeError, OverflowError) as exc:
        print('PRIOR_FINANCIAL_SNAPSHOT_READONLY_REVIEW_REQUIRED: '
              + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
