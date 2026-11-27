#!/usr/bin/env python3
"""Read-only exact Nov25 receipt SHA check in ONE dense existing direct JSON directory.

A bounded metadata-only direct-entry pass is separate from the old P3.12
768-entry walker. JSON contents are hashed in deterministic, disjoint shards:
at most 128 JSON files and 64 MiB per shard, 24 MiB per file.
No QMT, recursion, source writing, receipt fabrication or market admission.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

import market_historical_receipt_sha_locator_readonly as OLD
import market_quality_source_proofs as PROOF

FORMAT = 'astock_pinned_nov25_dense_direct_json_shards_readonly_v1'
STATUS = 'EXPLICIT_DENSE_DIRECT_JSON_PHYSICAL_SHA_SHARDS_CHECKED_ONLY'
TARGET_SHA = OLD.TARGET_SHA
DIRECT_SUBDIR = 'qmt_1min_market/20261014_20261112/receipts'
MAX_DIRECT_ENTRIES_METADATA_ONLY = 65536
MAX_DIRECT_JSON_METADATA = 8192
MAX_PER_SHARD_JSON = OLD.MAX_JSON
MAX_PER_SHARD_BYTES = OLD.MAX_BYTES_TOTAL
MAX_SINGLE_JSON_BYTES = OLD.MAX_READ_BYTES
MAX_GLOBAL_HASH_BYTES = 512 * 1024 * 1024
MAX_SHARDS = 256

SAFE_REASONS = frozenset((
    'DENSE_MODULE_ROOT_INVALID', 'DENSE_WORK_ROOT_INVALID',
    'DENSE_DIRECT_ENTRY_METADATA_BUDGET', 'DENSE_DIRECT_JSON_METADATA_BUDGET',
    'DENSE_JSON_LINK_OR_NONREGULAR', 'DENSE_SHARD_JSON_CANDIDATE_BUDGET',
    'DENSE_SHARD_COUNT_BUDGET', 'DENSE_FILE_BYTES_BUDGET',
    'DENSE_SHARD_BYTES_BUDGET', 'DENSE_GLOBAL_HASH_BYTES_BUDGET',
    'DENSE_FILE_CHANGED_DURING_HASH', 'DENSE_DIRECTORY_CHANGED_DURING_HASH',
    'DENSE_SHARD_PARTITION_INCOMPLETE', 'DENSE_PINNED_SHA_INVALID',
))


class DenseReceiptError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise DenseReceiptError(reason)


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode)


def _root(module_root):
    module = Path(module_root)
    need(module.is_dir() and not module.is_symlink(),
         'DENSE_MODULE_ROOT_INVALID')
    work = module / 'work'
    need(work.is_dir() and not work.is_symlink(), 'DENSE_WORK_ROOT_INVALID')
    # Reuse the same strict work-relative path and symlink protections
    # as the P3.12 immutable historical receipt locator.
    return OLD._directory(work, DIRECT_SUBDIR)


def _snapshot(directory):
    """Bounded, nonrecursive directory metadata; never read a non-JSON file."""
    json_files = []
    entries_count = 0
    with os.scandir(directory) as stream:
        for item in stream:
            entries_count += 1
            need(entries_count <= MAX_DIRECT_ENTRIES_METADATA_ONLY,
                 'DENSE_DIRECT_ENTRY_METADATA_BUDGET')
            if not item.name.lower().endswith('.json'):
                continue
            need(not item.is_symlink() and item.is_file(follow_symlinks=False),
                 'DENSE_JSON_LINK_OR_NONREGULAR')
            info = item.stat(follow_symlinks=False)
            need(stat.S_ISREG(info.st_mode), 'DENSE_JSON_LINK_OR_NONREGULAR')
            json_files.append((item.name, _identity(info)))
            need(len(json_files) <= MAX_DIRECT_JSON_METADATA,
                 'DENSE_DIRECT_JSON_METADATA_BUDGET')
    json_files.sort(key=lambda r: r[0])
    need(len({name for name, _ in json_files}) == len(json_files),
         'DENSE_JSON_LINK_OR_NONREGULAR')
    canonical = json.dumps(json_files, ensure_ascii=True,
                           separators=(',', ':')).encode('ascii')
    fingerprint = sha256(canonical).hexdigest()
    return entries_count, json_files, fingerprint


def _bucket(name, slots):
    return sha256(name.encode('utf-8')).digest()[0] % slots


def _groups(files):
    """Partition the FULL direct JSON set, refining oversized 16-way shards."""
    primary = [[] for _ in range(16)]
    for name, identity in files:
        primary[_bucket(name, 16)].append((name, identity))
    chunks = []
    for i, group in enumerate(primary):
        if len(group) <= MAX_PER_SHARD_JSON:
            chunks.append(('16:' + str(i), group))
            continue
        subdivisions = [[] for _ in range(16)]
        for item in group:
            slot256 = _bucket(item[0], 256)
            need(slot256 % 16 == i, 'DENSE_SHARD_PARTITION_INCOMPLETE')
            subdivisions[slot256 // 16].append(item)
        for part, subgroup in enumerate(subdivisions):
            need(len(subgroup) <= MAX_PER_SHARD_JSON,
                 'DENSE_SHARD_JSON_CANDIDATE_BUDGET')
            chunks.append(('256:' + str(i + 16 * part), subgroup))
    need(len(chunks) <= MAX_SHARDS, 'DENSE_SHARD_COUNT_BUDGET')
    flattened = [name for _, group in chunks for name, _ in group]
    need(len(flattened) == len(files) and
         len(set(flattened)) == len(files) and
         set(flattened) == {name for name, _ in files},
         'DENSE_SHARD_PARTITION_INCOMPLETE')
    return chunks


def inspect(module_root, *, expected_sha=TARGET_SHA):
    # A test may replace this constant only inside a synthetic fixture scope.
    need(type(expected_sha) is str and expected_sha == TARGET_SHA,
         'DENSE_PINNED_SHA_INVALID')
    directory = _root(module_root)
    dir_before = directory.stat()
    total_entries, files, manifest_sha = _snapshot(directory)
    chunks = _groups(files)
    total_hashed = 0
    matches = []
    hashed = 0
    empty_shards = 0
    for shard_name, items in chunks:
        if not items:
            empty_shards += 1
        per_shard = 0
        for name, original_identity in items:
            file = directory / name
            need(not file.is_symlink() and file.is_file(),
                 'DENSE_JSON_LINK_OR_NONREGULAR')
            current_identity = _identity(file.stat())
            need(current_identity == original_identity,
                 'DENSE_FILE_CHANGED_DURING_HASH')
            size = original_identity[2]
            need(0 < size <= MAX_SINGLE_JSON_BYTES,
                 'DENSE_FILE_BYTES_BUDGET')
            per_shard += size
            need(per_shard <= MAX_PER_SHARD_BYTES,
                 'DENSE_SHARD_BYTES_BUDGET')
            total_hashed += size
            need(total_hashed <= MAX_GLOBAL_HASH_BYTES,
                 'DENSE_GLOBAL_HASH_BYTES_BUDGET')
            digest, actual_bytes = PROOF._hash_stable_file(file)
            need(not file.is_symlink() and actual_bytes == size and
                 _identity(file.stat()) == original_identity,
                 'DENSE_FILE_CHANGED_DURING_HASH')
            hashed += 1
            if digest == TARGET_SHA:
                second_digest, second_bytes = PROOF._hash_stable_file(file)
                need(second_digest == digest and second_bytes == size and
                     not file.is_symlink() and
                     _identity(file.stat()) == original_identity,
                     'DENSE_FILE_CHANGED_DURING_HASH')
                matches.append({
                    'receipt_relative_within_work': DIRECT_SUBDIR + '/' + name,
                    'receipt_bytes_sha256': digest,
                    'receipt_bytes': size,
                    'stage_log_verified': False,
                    'candidate_parquet_verified': False,
                })
    after_entries, after_files, after_sha = _snapshot(directory)
    need(_identity(directory.stat()) == _identity(dir_before) and
         after_entries == total_entries and after_files == files and
         after_sha == manifest_sha, 'DENSE_DIRECTORY_CHANGED_DURING_HASH')
    need(hashed == len(files), 'DENSE_SHARD_PARTITION_INCOMPLETE')
    return {
        'format': FORMAT, 'status': STATUS,
        'expected_original_receipt_sha256': TARGET_SHA,
        'scan_scope_relative_to_work': DIRECT_SUBDIR,
        'direct_only_no_recursion': True,
        'directory_entries_examined_metadata_only': total_entries,
        'direct_json_candidates': len(files),
        'direct_json_manifest_sha256': manifest_sha,
        'shards_checked': len(chunks),
        'empty_shards': empty_shards,
        'shard_max_json_files': MAX_PER_SHARD_JSON,
        'shard_max_bytes': MAX_PER_SHARD_BYTES,
        'single_file_max_bytes': MAX_SINGLE_JSON_BYTES,
        'global_max_bytes': MAX_GLOBAL_HASH_BYTES,
        'physically_hashed_json_files': hashed,
        'json_bytes_physically_hashed': total_hashed,
        'exact_original_receipt_matches': matches,
        'matching_file_count': len(matches),
        'scope_exhaustive': True,
        'producer_receipt_stage_log_verified': False,
        'original_private_candidate_parquet_verified': False,
        'data_quality_cleared': False,
        'producer_quarantine_cleared': False,
        'market_files_written': False,
        'qmt_cache_queried_or_modified': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.module_root), ensure_ascii=False,
                         indent=2, sort_keys=True, allow_nan=False))
        return 0
    except DenseReceiptError as exc:
        reason = str(exc)
        if reason not in SAFE_REASONS:
            reason = 'DENSE_UNRECOGNIZED_REASON_WITHHELD'
        print('DENSE_HISTORICAL_RECEIPT_REVIEW_REQUIRED: ' + reason)
        return 3
    except (OLD.ReceiptLocateError, PROOF.ProofError, OSError, TypeError,
            ValueError, UnicodeError, RuntimeError) as exc:
        print('DENSE_HISTORICAL_RECEIPT_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
