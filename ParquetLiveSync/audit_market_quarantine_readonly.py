#!/usr/bin/env python3
"""Read-only evidence audit for quarantined A-share stock-days.

Reads only the pinned scheduled-run receipt, its EIGHT_PERIODS log, and
SHA-linked private daily candidate metadata. QMT, market state and provider
files are never modified. Optional --verify-parquet hashes candidate bytes.
"""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re

MARKER = 'MARKET_DAILY_STAGED='
SYMBOL = re.compile(r'^(SH|SZ)\d{6}$')
SHA = re.compile(r'^[0-9a-fA-F]{64}$')

class EvidenceError(ValueError):
    pass


def bounded_bytes(path, limit=24 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise EvidenceError('MISSING_LINKED_OR_OVERSIZE_FILE: ' + path.name)
    with path.open('rb') as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise EvidenceError('FILE_TOO_LARGE: ' + path.name)
    return data


def sha_file(path):
    if path.is_symlink() or not path.is_file():
        raise EvidenceError('PARQUET_MISSING_OR_LINKED')
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def classify(reason):
    if reason.startswith('ValueError: QMT returned no original OHLCVA 1m:'):
        return 'QMT_RAW_ONE_MINUTE_MISSING'
    if reason.startswith('ValueError: Independent official DAY materialized OHLC discrepancy:'):
        return 'OFFICIAL_DAY_OHLC_MISMATCH'
    if reason.startswith('ValueError: QMT materialized minute extrema exceed official DAY envelope'):
        return 'OFFICIAL_DAY_ENVELOPE_MISMATCH'
    return 'OTHER_QUARANTINE'


def secure_receipt_in_work(work, relative):
    """Caller-selected existing local receipt; never follow work path aliases."""
    if relative is None:
        relative = 'last-afternoon-unified.json'
    if (type(relative) is not str or not (0 < len(relative) <= 320)
            or '\\' in relative or ':' in relative or not relative.endswith('.json')
            or relative.startswith('/') or
            any(x in ('', '.', '..') for x in relative.split('/'))):
        raise EvidenceError('RUN_RECEIPT_RELATIVE_PATH_INVALID')
    path = work
    for piece in relative.split('/'):
        path = path / piece
        if path.is_symlink():
            raise EvidenceError('RUN_RECEIPT_SYMLINK_FORBIDDEN')
    if not path.is_file() or not path.resolve().is_relative_to(work.resolve()):
        raise EvidenceError('RUN_RECEIPT_OUTSIDE_WORK_OR_MISSING')
    return path


def audit(module_root, day, expected_run_sha, verify_parquet=False,
          *, receipt_relative=None):
    if not SHA.fullmatch(expected_run_sha):
        raise EvidenceError('EXPECTED_RUN_SHA_REQUIRED')
    try:
        target = date.fromisoformat(day)
    except ValueError as exc:
        raise EvidenceError('INVALID_DATE') from exc
    if target.isoformat() != day:
        raise EvidenceError('INVALID_DATE')
    module_root = Path(module_root)
    if module_root.is_symlink() or not module_root.is_dir():
        raise EvidenceError('BAD_MODULE_ROOT')
    work = module_root / 'work'
    if work.is_symlink() or not work.is_dir():
        raise EvidenceError('BAD_WORK_DIR')
    run_file = secure_receipt_in_work(work, receipt_relative)
    raw = bounded_bytes(run_file)
    run_digest = hashlib.sha256(raw).hexdigest()
    if run_digest.lower() != expected_run_sha.lower():
        raise EvidenceError('RUN_RECEIPT_SHA_MISMATCH')
    if hashlib.sha256(bounded_bytes(run_file)).hexdigest() != run_digest:
        raise EvidenceError('RUN_RECEIPT_CHANGED_DURING_READ')
    run = json.loads(raw.decode('utf-8-sig'))
    if (not isinstance(run, dict) or run.get('format') != 'qmt_daily_single_trigger_v3'
            or run.get('invocation') != 'Scheduled'
            or run.get('run_scope') != 'ALL_FOUR_SECTIONS'
            or run.get('history_only') is not False
            or not str(run.get('china_start','')).startswith(day + 'T')):
        raise EvidenceError('WRONG_SCHEDULED_RUN')
    stages = run.get('stage_records')
    stage = stages.get('EIGHT_PERIODS') if isinstance(stages, dict) else None
    if not isinstance(stage, dict) or type(stage.get('exit_code')) is not int:
        raise EvidenceError('EIGHT_PERIOD_STAGE_MISSING')
    logfile = stage.get('log_path')
    if not isinstance(logfile, str) or not Path(logfile).is_absolute():
        raise EvidenceError('BAD_STAGE_LOG_PATH')
    log = Path(logfile)
    if log.is_symlink() or os.path.commonpath((str(log.resolve()), str(work.resolve()))) != str(work.resolve()):
        raise EvidenceError('STAGE_LOG_OUTSIDE_WORK')
    stage_bytes = bounded_bytes(log)
    lines = stage_bytes.decode('utf-8-sig', errors='replace').splitlines()
    staged = []
    for line in lines:
        if line.startswith(MARKER):
            entry = json.loads(line[len(MARKER):])
            if not isinstance(entry, dict):
                raise EvidenceError('MALFORMED_STAGED_ENTRY')
            if entry.get('date') == day:
                staged.append(entry)
    if len(staged) != 1:
        raise EvidenceError('STAGED_TARGET_DATE_COUNT_' + str(len(staged)))
    entry = staged[0]
    if (type(entry.get('accepted')) is not int or entry['accepted'] < 0
            or type(entry.get('quarantine')) is not int or entry['quarantine'] < 0
            or not isinstance(entry.get('sha256'), str) or not SHA.fullmatch(entry['sha256'])
            or type(entry.get('rows')) is not int or entry['rows'] != entry['accepted'] * 240):
        raise EvidenceError('STAGED_FIELDS_INVALID')
    private_dir = work / 'market_update' / 'daily'
    if private_dir.is_symlink():
        raise EvidenceError('PRIVATE_DAILY_LINKED')
    meta = json.loads(bounded_bytes(private_dir / (day + '.json')).decode('utf-8-sig'))
    if not isinstance(meta, dict):
        raise EvidenceError('PRIVATE_DAILY_NOT_OBJECT')
    quarantined = meta.get('quarantined')
    if not isinstance(quarantined, dict):
        raise EvidenceError('QUARANTINE_MAP_MISSING')
    if (meta.get('format') != 'one_command_qmt_market_update_v1'
            or meta.get('date') != day or meta.get('sha256') != entry['sha256']
            or type(meta.get('stock_days_accepted')) is not int
            or meta['stock_days_accepted'] != entry['accepted']
            or type(meta.get('expected_stock_days')) is not int
            or meta['expected_stock_days'] != entry['accepted'] + entry['quarantine']
            or type(meta.get('rows')) is not int or meta['rows'] != entry['rows']
            or len(quarantined) != entry['quarantine']):
        raise EvidenceError('DAILY_METADATA_DISAGREES_WITH_STAGE')
    items = []
    counts = Counter()
    for symbol, reason in sorted(quarantined.items()):
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise EvidenceError('BAD_QUARANTINED_SYMBOL')
        if not isinstance(reason, str) or len(reason) > 320 or not reason:
            raise EvidenceError('BAD_QUARANTINE_REASON')
        category = classify(reason)
        counts[category] += 1
        items.append({'symbol':symbol, 'category':category, 'reason':reason})
    result = {'status':'METADATA_MATCH_QUARANTINE_RETAINED', 'day':day,
              'run_receipt_sha256':run_digest,
              'accepted':entry['accepted'], 'quarantined':len(items),
              'expected':meta['expected_stock_days'],
              'stage_exit_code':stage['exit_code'],
              'reason_groups':dict(sorted(counts.items())),
              'stocks':items, 'parquet_content_sha_verified':False,
              'data_quality_cleared':False}
    if verify_parquet:
        if sha_file(private_dir / (day + '.parquet')) != entry['sha256']:
            raise EvidenceError('PHYSICAL_PARQUET_SHA_MISMATCH')
        result['parquet_content_sha_verified'] = True
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    p.add_argument('--day', required=True)
    p.add_argument('--expected-run-sha256', required=True)
    p.add_argument('--verify-parquet', action='store_true')
    p.add_argument('--receipt-relative', default=None)
    args = p.parse_args(argv)
    try:
        print(json.dumps(audit(args.module_root,args.day,args.expected_run_sha256,
                               args.verify_parquet,receipt_relative=args.receipt_relative),
                         ensure_ascii=False,indent=2))
        return 0
    except (EvidenceError, OSError, UnicodeError, ValueError, TypeError) as exc:
        print('MARKET_QUARANTINE_AUDIT_REVIEW_REQUIRED: ' + str(exc))
        return 3

if __name__ == '__main__':
    raise SystemExit(main())
