#!/usr/bin/env python3
"""Bounded read-only byte proofs for explicitly provided market-source exports.

Hashing declared files does not authenticate their provider, trading content,
source independence, official-day correctness, or market admission. No QMT IO.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

FORMAT = 'astock_source_byte_evidence_v1'
STATUS = 'DECLARED_MARKET_SOURCE_ARTIFACT_BYTES_VERIFIED_ONLY'
ROLES = frozenset(('native_minute', 'official_day', 'purchased_reference'))
PERIODS = frozenset(('1min', '5min', '15min', '30min', '60min', 'day', 'week', 'month'))
SYMBOL = re.compile(r'^(SH|SZ|BJ)[0-9]{6}$')
SOURCE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
HEX64 = re.compile(r'^[0-9a-fA-F]{64}$')
MAX_MANIFEST = 65536
MAX_ARTIFACT = 1 << 30  # One GiB per file; smaller than unbounded full-market scans


class ProofError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ProofError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _pairs(entries):
    found = {}
    for key, val in entries:
        require(key not in found, 'DUPLICATE_MANIFEST_JSON_KEY')
        found[key] = val
    return found


def _secure_relative(root: Path, rel: str) -> Path:
    require(isinstance(rel, str) and len(rel) <= 512 and '\\' not in rel,
            'INVALID_RELATIVE_ARTIFACT_PATH')
    path = PurePosixPath(rel)
    require(not path.is_absolute() and len(path.parts) >= 1
            and all(part not in ('', '.', '..') for part in rel.split('/'))
            and ':' not in rel and not rel.startswith('//'),
            'ARTIFACT_PATH_ESCAPE_REJECTED')
    current = root
    for piece in path.parts:
        current = current / piece
        require(not current.is_symlink(), 'ARTIFACT_SYMLINK_FORBIDDEN')
    require(current.is_file(), 'ARTIFACT_MISSING_OR_NONFILE')
    require(current.resolve().is_relative_to(root.resolve()),
            'ARTIFACT_PATH_OUTSIDE_ROOT')
    return current


def _hash_stable_file(path: Path) -> tuple[str, int]:
    try:
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode)
                    and 0 < before.st_size <= MAX_ARTIFACT,
                    'ARTIFACT_EMPTY_OVERSIZE_OR_NONREGULAR')
            checksum = sha256()
            while True:
                data = stream.read(1 << 20)
                if not data:
                    break
                checksum.update(data)
            after = os.fstat(stream.fileno())
        disk = path.stat()
    except OSError as exc:
        raise ProofError('ARTIFACT_READ_FAILED') from exc
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    require(identity(before) == identity(after) == identity(disk),
            'ARTIFACT_CHANGED_DURING_HASH')
    return checksum.hexdigest(), before.st_size


def verify(root: Path, manifest_relative: str) -> dict:
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'EVIDENCE_ROOT_UNAVAILABLE')
    manifest_path = _secure_relative(root, manifest_relative)
    require(manifest_path.stat().st_size <= MAX_MANIFEST, 'MANIFEST_OVERSIZE')
    # Parse exactly the same bytes that are hashed; do not reopen after hash.
    with manifest_path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        raw_manifest = stream.read(MAX_MANIFEST + 1)
        after = os.fstat(stream.fileno())
    require(0 < len(raw_manifest) <= MAX_MANIFEST and
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) ==
            (manifest_path.stat().st_dev, manifest_path.stat().st_ino,
             manifest_path.stat().st_size, manifest_path.stat().st_mtime_ns),
            'MANIFEST_CHANGED_DURING_READ')
    manifest_sha = sha256(raw_manifest).hexdigest()
    try:
        manifest = json.loads(raw_manifest.decode('utf-8-sig'),
                              object_pairs_hook=_pairs)
    except ProofError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise ProofError('MANIFEST_INVALID_JSON') from exc
    require(isinstance(manifest, dict) and set(manifest) ==
            {'format', 'scope', 'artifacts'} and manifest['format'] == FORMAT,
            'UNKNOWN_MANIFEST_FORMAT')
    scope = manifest['scope']
    require(isinstance(scope, dict) and set(scope) ==
            {'trading_day', 'symbol', 'period'}, 'INVALID_PROOF_SCOPE')
    day, ticker, period = (scope[k] for k in ('trading_day', 'symbol', 'period'))
    require(isinstance(day, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)),
            'INVALID_PROOF_DATE')
    try:
        require(date.fromisoformat(day).isoformat() == day, 'INVALID_PROOF_DATE')
    except ValueError as exc:
        raise ProofError('INVALID_PROOF_DATE') from exc
    require(isinstance(ticker, str) and bool(SYMBOL.fullmatch(ticker)),
            'INVALID_PROOF_SYMBOL')
    require(isinstance(period, str) and period in PERIODS,
            'INVALID_PROOF_PERIOD')
    items = manifest['artifacts']
    require(isinstance(items, list) and 2 <= len(items) <= 3,
            'INVALID_ARTIFACT_COUNT')
    roles, paths, identities, records = set(), set(), set(), []
    for item in items:
        require(isinstance(item, dict) and set(item) ==
                {'role', 'source_id', 'relative_path', 'expected_sha256'},
                'INVALID_ARTIFACT_FIELDS')
        role, source, rel, expected = (item[k] for k in
            ('role', 'source_id', 'relative_path', 'expected_sha256'))
        require(role in ROLES if isinstance(role, str) else False,
                'INVALID_ARTIFACT_ROLE')
        require(role not in roles, 'DUPLICATE_ARTIFACT_ROLE')
        require(isinstance(source, str) and bool(SOURCE.fullmatch(source)),
                'INVALID_SOURCE_IDENTIFIER')
        require(isinstance(expected, str) and bool(HEX64.fullmatch(expected)),
                'INVALID_ARTIFACT_SHA')
        filename = _secure_relative(root, rel)
        require(filename not in paths, 'DUPLICATE_ARTIFACT_PATH')
        file_id = (filename.stat().st_dev, filename.stat().st_ino)
        require(file_id not in identities, 'DUPLICATE_ARTIFACT_INODE')
        actual, size = _hash_stable_file(filename)
        require(actual == expected.lower(), 'ARTIFACT_BYTES_SHA_MISMATCH')
        roles.add(role);paths.add(filename);identities.add(file_id)
        records.append({'role': role, 'declared_source_id': source,
                        'bytes_sha256': actual, 'bytes': size,
                        'local_file_bytes_verified': True,
                        'provider_identity_independently_authenticated': False})
    require('native_minute' in roles and 'official_day' in roles,
            'NATIVE_AND_OFFICIAL_ROLES_REQUIRED')
    require(len({x['declared_source_id'] for x in records}) == len(records),
            'DUPLICATE_DECLARED_SOURCE_ID')
    require(len({x['bytes_sha256'] for x in records}) == len(records),
            'IDENTICAL_ARTIFACT_CONTENTS_NOT_INDEPENDENT_PROOF')
    records.sort(key=lambda x: x['role'])
    result = {
        'status': STATUS, 'scope': scope, 'manifest_bytes_sha256': manifest_sha,
        'manifest_digest_scope': 'LOCAL_DECLARED_MANIFEST_BYTES_NOT_TRUSTED_SIGNATURE',
        'artifacts': records,
        'verified_local_file_count': len(records),
        'official_day_content_or_trading_universe_validated': False,
        'provider_identity_independently_authenticated': False,
        'distinct_declared_provider_labels_do_not_prove_independence': True,
        'native_qmt_origin_proven': False,
        'market_data_content_validated': False,
        'production_admission_authorized': False,
        'qmt_download_calls': 0, 'market_files_written': False,
    }
    result['report_sha256'] = digest(result)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--manifest-relative', required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(verify(a.evidence_root, a.manifest_relative),
                         ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ProofError, OSError, TypeError, ValueError) as exc:
        # No absolute private path or source document content in printed error.
        print('MARKET_SOURCE_BYTE_PROOF_REVIEW_REQUIRED: ' +
              type(exc).__name__ + ': ' + str(exc)[:100])
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
