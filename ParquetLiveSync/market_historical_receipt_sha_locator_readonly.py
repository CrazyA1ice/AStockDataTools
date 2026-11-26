#!/usr/bin/env python3
"""Bounded read-only exact SHA search for a real archived Nov25 run receipt.

No new files, no copying, no source replacement, no recursive drive search.
A found SHA is physical identity only; must separately verify the old scheduled
run's EIGHT_PERIODS log and candidate Parquet before claiming original evidence.
"""
from __future__ import annotations

import argparse
from collections import deque
from hashlib import sha256
import json
from pathlib import Path

import audit_market_quarantine_readonly as AUDIT
import market_quality_source_proofs as PROOF

FORMAT = 'astock_historical_run_receipt_sha_locator_readonly_v1'
STATUS = 'PINNED_ORIGINAL_RECEIPT_BYTES_FOUND_OR_NOT_FOUND_IN_EXPLICIT_BOUNDED_SCOPE'
TARGET_SHA = '72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837'
MAX_DEPTH = 3
MAX_ENTRIES = 768
MAX_JSON = 128
MAX_BYTES_TOTAL = 64 * 1024 * 1024
MAX_READ_BYTES = 24 * 1024 * 1024

# Only stable, source-authored reason codes may appear on the CLI. In
# particular, never echo an exception message containing a private path.
SAFE_REVIEW_REASONS = frozenset((
    'RECEIPT_EXPECTED_FIXED_SHA_REQUIRED',
    'SEARCH_DEPTH_OUTSIDE_BOUND',
    'SEARCH_MODULE_ROOT_INVALID',
    'SEARCH_WORK_ROOT_INVALID',
    'SEARCH_SUBDIRECTORY_INVALID',
    'SEARCH_SYMLINK_DIRECTORY_REJECTED',
    'SEARCH_SUBDIRECTORY_OUTSIDE_WORK_OR_MISSING',
    'SEARCH_DIRECTORY_ENTRY_BUDGET',
    'SEARCH_SYMLINK_ENTRY_REJECTED',
    'SEARCH_PATH_ESCAPED_WORK',
    'SEARCH_JSON_CANDIDATE_BUDGET',
    'SEARCH_TOTAL_JSON_BYTES_BUDGET',
    'SEARCH_FILE_CHANGED_DURING_HASH',
    'MATCHING_RECEIPT_CHANGED_DURING_SEARCH',
))


class ReceiptLocateError(ValueError):
    pass


def check(value, why):
    if not value:
        raise ReceiptLocateError(why)


def _directory(work, relative):
    check(type(relative) is str and 0 < len(relative) <= 320,
          'SEARCH_SUBDIRECTORY_INVALID')
    if relative == '.':
        return work
    check(not relative.startswith('/') and '\\' not in relative and ':' not in relative
          and all(part not in ('', '.', '..') for part in relative.split('/')),
          'SEARCH_SUBDIRECTORY_INVALID')
    current = work
    for piece in relative.split('/'):
        current = current / piece
        check(not current.is_symlink(), 'SEARCH_SYMLINK_DIRECTORY_REJECTED')
    check(current.is_dir() and current.resolve().is_relative_to(work.resolve()),
          'SEARCH_SUBDIRECTORY_OUTSIDE_WORK_OR_MISSING')
    return current


def _same_identity(a, b):
    return (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns) == (
        b.st_dev, b.st_ino, b.st_size, b.st_mtime_ns)


def locate(module_root, *, search_subdir='.', max_depth=2,
           target_sha256=TARGET_SHA):
    check(type(target_sha256) is str and target_sha256 == TARGET_SHA,
          'RECEIPT_EXPECTED_FIXED_SHA_REQUIRED')
    check(type(max_depth) is int and 0 <= max_depth <= MAX_DEPTH,
          'SEARCH_DEPTH_OUTSIDE_BOUND')
    module = Path(module_root)
    check(module.is_dir() and not module.is_symlink(),
          'SEARCH_MODULE_ROOT_INVALID')
    work = module / 'work'
    check(work.is_dir() and not work.is_symlink(), 'SEARCH_WORK_ROOT_INVALID')
    start = _directory(work, search_subdir)
    queue = deque([(start, 0)])
    seen = 0
    json_count = 0
    hashed_bytes = 0
    oversize = []
    matches = []
    while queue:
        directory, depth = queue.popleft()
        check(not directory.is_symlink(), 'SEARCH_SYMLINK_DIRECTORY_REJECTED')
        # Bound the directory enumeration BEFORE sorting. Sorting the raw
        # directory iterator would first materialize an unbounded file list.
        bounded_entries = []
        for entry in directory.iterdir():
            seen += 1
            check(seen <= MAX_ENTRIES, 'SEARCH_DIRECTORY_ENTRY_BUDGET')
            bounded_entries.append(entry)
        for entry in sorted(bounded_entries, key=lambda p: p.name):
            check(not entry.is_symlink(), 'SEARCH_SYMLINK_ENTRY_REJECTED')
            check(entry.resolve().is_relative_to(work.resolve()),
                  'SEARCH_PATH_ESCAPED_WORK')
            if entry.is_dir():
                if depth < max_depth:
                    queue.append((entry, depth + 1))
                continue
            if not entry.is_file() or entry.suffix.lower() != '.json':
                continue
            json_count += 1
            check(json_count <= MAX_JSON, 'SEARCH_JSON_CANDIDATE_BUDGET')
            before = entry.stat()
            relative = entry.relative_to(work).as_posix()
            if not (0 < before.st_size <= MAX_READ_BYTES):
                oversize.append(relative)
                continue
            hashed_bytes += before.st_size
            check(hashed_bytes <= MAX_BYTES_TOTAL, 'SEARCH_TOTAL_JSON_BYTES_BUDGET')
            digest, count = PROOF._hash_stable_file(entry)
            after = entry.stat()
            check(count == before.st_size and _same_identity(before, after),
                  'SEARCH_FILE_CHANGED_DURING_HASH')
            if digest == TARGET_SHA:
                # Hash again on actual physical bytes to narrow read races.
                digest_again, second_size = PROOF._hash_stable_file(entry)
                check(digest_again == digest and second_size == count and
                      _same_identity(before, entry.stat()),
                      'MATCHING_RECEIPT_CHANGED_DURING_SEARCH')
                matches.append({'receipt_relative_within_work':relative,
                                'receipt_bytes_sha256':digest,
                                'receipt_bytes':count,
                                'scheduled_log_candidate_checked':False,
                                'original_private_candidate_parquet_checked':False})
    # Absence applies strictly to the explicit scoped walk. Other folders,
    # unsearched depth or oversize JSON may still contain the old receipt.
    return {
        'format':FORMAT, 'status':STATUS,
        'expected_original_receipt_sha256':TARGET_SHA,
        'search_subdir_relative_to_installed_work':search_subdir,
        'maximum_child_directory_depth_explored':max_depth,
        'directory_entries_examined':seen,
        'json_candidates_examined':json_count,
        'json_bytes_hashed':hashed_bytes,
        'oversize_or_empty_json_relative_paths_not_hashed':oversize,
        'exact_original_receipt_sha_matches':matches,
        'matching_file_count':len(matches),
        'scope_exhaustive':len(oversize)==0,
        'no_match_in_scoped_files_only':len(matches)==0,
        'original_run_and_stage_log_chain_verified':False,
        'producer_quarantine_cleared':False,
        'market_candidate_validated':False,
        'qmt_provider_authenticated':False,
        'production_market_write_authorized':False,
        'market_files_written':False,
        'qmt_cache_queried_or_modified':False,
        'qmt_download_calls':0,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root',type=Path,required=True)
    p.add_argument('--search-subdir',default='.')
    p.add_argument('--max-depth',default=2,type=int)
    a=p.parse_args(argv)
    try:
        r=locate(a.module_root,search_subdir=a.search_subdir,
                 max_depth=a.max_depth)
        print(json.dumps(r,indent=2,sort_keys=True,ensure_ascii=False,
                         allow_nan=False))
        return 0
    except ReceiptLocateError as exc:
        reason = str(exc)
        if reason not in SAFE_REVIEW_REASONS:
            reason = 'SEARCH_DIAGNOSTIC_REASON_WITHHELD'
        print('PINNED_HISTORICAL_RECEIPT_LOCATION_REVIEW_REQUIRED: ' + reason)
        return 3
    except (AUDIT.EvidenceError, PROOF.ProofError, OSError,
            ValueError, TypeError, RuntimeError) as exc:
        print('PINNED_HISTORICAL_RECEIPT_LOCATION_REVIEW_REQUIRED: '+type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
