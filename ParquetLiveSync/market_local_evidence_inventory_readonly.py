#!/usr/bin/env python3
"""Enumerate SHA-pinned existing private evidence in one explicit local directory.

An inventory verifies observed local bytes only; it does not authenticate
QMT, official DAY, a stock-date scope, supplier independence or write access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import market_quality_source_proofs as PROOF

FORMAT = 'astock_local_evidence_inventory_readonly_v1'
STATUS = 'LOCAL_SOURCE_FILES_LISTED_BYTES_ONLY_NOT_PROVIDER_AUTHENTICATED'
EXT = {'minute': '.jsonl', 'day': '.parquet'}
MAX_ENTRIES = 256
MAX_MATCHED = 64
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_SINGLE_BYTES = 256 * 1024 * 1024


class InventoryError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise InventoryError(reason)


def inspect(root, kind):
    """Read-only and nonrecursive; no source content/schema is inferred."""
    need(type(kind) is str and kind in EXT, 'EVIDENCE_INVENTORY_KIND_INVALID')
    root = Path(root)
    need(root.is_dir() and not root.is_symlink() and
         root.resolve() != Path(root.anchor).resolve(),
         'EVIDENCE_INVENTORY_ROOT_INVALID')
    observed = []
    seen = 0
    for path in root.iterdir():
        seen += 1
        need(seen <= MAX_ENTRIES, 'EVIDENCE_INVENTORY_ENTRIES_LIMIT')
        if path.suffix.lower() != EXT[kind]:
            continue
        need(path.is_file() and not path.is_symlink(),
             'EVIDENCE_INVENTORY_LINK_OR_NONFILE')
        f = PROOF._secure_relative(root, path.name)
        s = f.stat()
        need(0 < s.st_size <= MAX_SINGLE_BYTES,
             'EVIDENCE_INVENTORY_FILE_SIZE_INVALID')
        observed.append((path.name, s.st_size))
        need(len(observed) <= MAX_MATCHED, 'EVIDENCE_INVENTORY_MATCHED_LIMIT')
    need(sum(size for _,size in observed) <= MAX_TOTAL_BYTES,
         'EVIDENCE_INVENTORY_TOTAL_SIZE_LIMIT')
    result = []
    for rel, declared_size in sorted(observed):
        f = PROOF._secure_relative(root, rel)
        sha, count = PROOF._hash_stable_file(f)
        need(count == declared_size and f.stat().st_size == count,
             'EVIDENCE_INVENTORY_CHANGED_DURING_HASH')
        result.append({'relative_path': rel,
                       'observed_file_bytes': count,
                       'observed_local_file_sha256': sha,
                       'contents_validated': False,
                       'source_provider_authenticated': False})
    return {
        'format': FORMAT, 'status': STATUS, 'kind': kind,
        'file_count': len(result), 'files': result,
        'empty_directory_or_no_matching_files': len(result) == 0,
        'directories_recursively_scanned': 0,
        'directory_entries_examined': seen,
        'complete_directory_snapshot_or_lock_certified': False,
        'exchange_stock_day_universe_certified': False,
        'qmt_native_origin_authenticated': False,
        'official_day_provider_identity_authenticated': False,
        'paid_units_calibrated': False,
        'production_quarantine_cleared': False,
        'market_files_written': False,
        'qmt_cache_modified': False,
        'qmt_download_calls': 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', required=True, type=Path)
    p.add_argument('--kind', choices=sorted(EXT), required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.evidence_root, a.kind), ensure_ascii=False,
                         sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (InventoryError, PROOF.ProofError, ValueError, TypeError,
            OSError, OverflowError, RuntimeError) as exc:
        print('LOCAL_SOURCE_INVENTORY_REVIEW_REQUIRED: ' + type(exc).__name__)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
