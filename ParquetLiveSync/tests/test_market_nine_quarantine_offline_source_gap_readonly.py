"""Read-only pinned Nov25 quarantine vs explicitly existing local probe coverage."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import contextlib
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_nine_quarantine_offline_source_gap_readonly as G
import market_native_minute_jsonl_readonly as M
import market_local_evidence_inventory_readonly as I

CN=timezone(timedelta(hours=8))


def original(*, category=None, sha=G.RUN_SHA, accepted=5206):
    stocks=[{'symbol':s,'category':'QMT_RAW_ONE_MINUTE_MISSING'} for s in G.MISSING]
    stocks += [{'symbol':s,'category':'OFFICIAL_DAY_OHLC_MISMATCH'} for s in G.MISMATCH]
    if category is not None:
        stocks[0]['category']=category
    return {'status':'METADATA_MATCH_QUARANTINE_RETAINED','day':G.DAY,
            'run_receipt_sha256':sha,'accepted':accepted,
            'quarantined':9,'expected':5215,'stocks':stocks,
            'parquet_content_sha_verified':True,'data_quality_cleared':False}


def audit(reader=None):
    return lambda module_root, day, sha, verify_parquet=False: (
        reader() if reader is not None else original())


def rows(symbol='000001.SZ', day='2026-11-12', grid=None):
    return [
        {'datetime_cn':datetime.fromisoformat(day).replace(hour=h,minute=m,tzinfo=CN).isoformat(),
         'symbol':symbol,'open':10.,'high':11.,'low':9.,'close':10.5,
         'volume':10.,'amount':105.}
        for h,m in sorted(M.GRID if grid is None else grid)
    ]


def write(root,name,records):
    p=Path(root)/name
    data=b''.join((json.dumps(r,sort_keys=True)+'\n').encode('utf-8') for r in records)
    p.write_bytes(data)
    return sha256(data).hexdigest()


def inspect(root,**kw):
    return G.inspect(root,root,audit_reader=audit(),**kw)


class GapTests(unittest.TestCase):
    def test_empty_explicit_directory_nine_remain_open(self):
        with TemporaryDirectory() as root:
            x=inspect(root)
            self.assertEqual(x['existing_probe_files_content_checked'],0)
            self.assertEqual(x['original_quarantined_stock_days'],9)
            self.assertEqual(x['nine_quarantine_source_status_counts'],
                             {'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY':9})
            self.assertFalse(x['market_files_written'])
            self.assertFalse(x['qmt_cache_queried_or_modified'])

    def test_three_real_format_other_stocks_do_not_cover_nine(self):
        with TemporaryDirectory() as root:
            for code in ('000001.SZ','600000.SH','688001.SH'):
                write(root,code.replace('.','_')+'.jsonl',rows(code))
            x=inspect(root)
            self.assertEqual(x['existing_probe_files_content_checked'],3)
            self.assertEqual(x['nine_quarantine_source_status_counts'],
                             {'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY':9})
            self.assertEqual([q['strictly_checked_minute_rows']
                              for q in x['existing_probe_source_scopes']],[241]*3)
            self.assertFalse(x['original_quarantines_cleared'])

    def test_same_symbol_old_probe_does_not_claim_nov25_data(self):
        with TemporaryDirectory() as root:
            write(root,'qmt.jsonl',rows('300119.SZ','2026-11-12'))
            x=inspect(root)
            r=next(s for s in x['stocks'] if s['quarantined_symbol']=='SZ300119')
            self.assertEqual(r['offline_local_source_status'],
                             'MATCHING_SYMBOL_BUT_NO_20261125_IN_OBSERVED_SPAN')
            self.assertEqual(r['matching_sources'][0]['observed_last_day'],'2026-11-12')
            self.assertFalse(r['native_provider_authenticity_certified'])

    def test_same_symbol_exact_241_target_still_not_admitted(self):
        with TemporaryDirectory() as root:
            write(root,'qmt.jsonl',rows('300119.SZ','2026-11-25'))
            x=inspect(root)
            s=next(q for q in x['stocks'] if q['quarantined_symbol']=='SZ300119')
            self.assertEqual(s['offline_local_source_status'],
                             'LOCAL_TARGET_DAY_EXACT_241_WITH_0930_NOT_ADMITTED')
            self.assertFalse(s['producer_quarantine_closed'])
            self.assertFalse(s['market_repair_authorized'])

    def test_240_missing_opening_remains_review(self):
        with TemporaryDirectory() as root:
            write(root,'probe.jsonl',rows('300119.SZ','2026-11-25',M.GRID_240))
            x=inspect(root)
            s=next(q for q in x['stocks'] if q['quarantined_symbol']=='SZ300119')
            self.assertEqual(s['offline_local_source_status'],
                             'LOCAL_TARGET_DAY_EXACT_240_WITHOUT_0930_REVIEW_REQUIRED_NOT_ADMITTED')

    def test_239_partial_remains_review(self):
        with TemporaryDirectory() as root:
            write(root,'probe.jsonl',rows('300119.SZ','2026-11-25',M.GRID_240-{(10,0)}))
            x=inspect(root)
            s=next(q for q in x['stocks'] if q['quarantined_symbol']=='SZ300119')
            self.assertEqual(s['offline_local_source_status'],
                             'LOCAL_TARGET_DAY_PARTIAL_NATIVE_GRID_REVIEW_REQUIRED_NOT_ADMITTED')

    def test_original_bad_run_sha_rejected(self):
        with TemporaryDirectory() as root:
            with self.assertRaisesRegex(G.GapError,'PRODUCER_RECEIPT_INVALID'):
                G.inspect(root,root,audit_reader=audit(lambda:original(sha='f'*64)))

    def test_original_reason_category_change_rejected(self):
        with TemporaryDirectory() as root:
            with self.assertRaisesRegex(G.GapError,'REASON_CATEGORIES_CHANGED'):
                G.inspect(root,root,audit_reader=audit(lambda:original(category='ACCEPTED')))

    def test_original_accepted_count_change_rejected(self):
        with TemporaryDirectory() as root:
            with self.assertRaisesRegex(G.GapError,'PRODUCER_RECEIPT_INVALID'):
                G.inspect(root,root,audit_reader=audit(lambda:original(accepted=5205)))

    def test_wrong_or_partial_source_file_sha_fails(self):
        with TemporaryDirectory() as root:
            write(root,'probe.jsonl',rows())
            inv=I.inspect(root,'minute')
            inv['files'][0]['observed_local_file_sha256']='f'*64
            with self.assertRaises(G.WINDOW.WindowError):
                G.inspect(root,root,audit_reader=audit(),inventory_reader=lambda r,k:inv)

    def test_corrupt_jsonl_data_fails_closed(self):
        with TemporaryDirectory() as root:
            write(root,'probe.jsonl',[dict(rows()[0],volume=-100.)])
            with self.assertRaises(M.NativeMinuteError):
                inspect(root)

    def test_mixed_symbols_in_single_probe_rejected(self):
        with TemporaryDirectory() as root:
            records=rows()[:5]+rows('600000.SH')[5:]
            write(root,'probe.jsonl',records)
            with self.assertRaisesRegex(G.GapError,'MIXED_SYMBOLS'):
                inspect(root)

    def test_multiple_files_for_same_stock_are_not_picked_arbitrarily(self):
        with TemporaryDirectory() as root:
            write(root,'a.jsonl',rows('300119.SZ','2026-11-24'))
            write(root,'b.jsonl',rows('300119.SZ','2026-11-25'))
            r=inspect(root)
            s=next(x for x in r['stocks'] if x['quarantined_symbol']=='SZ300119')
            self.assertEqual(s['offline_local_source_status'],
                             'MULTIPLE_SAME_SYMBOL_LOCAL_SOURCES_REVIEW_REQUIRED')

    def test_original_run_receipt_mutation_during_scan_rejected(self):
        with TemporaryDirectory() as root:
            calls=[0]
            def changing():
                calls[0]+=1
                out=original()
                if calls[0]>=2:out['stocks'][0]['reason']='changed-in-flight'
                return out
            with self.assertRaisesRegex(G.GapError,'CHANGED_DURING_OFFLINE_SCAN'):
                G.inspect(root,root,audit_reader=audit(changing))

    def test_symlink_private_probe_rejected(self):
        with TemporaryDirectory() as root:
            real=Path(root)/'probe.jsonl'
            write(root,'probe.jsonl',rows())
            alias=Path(root)/'link.jsonl'
            try:alias.symlink_to(real)
            except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
            with self.assertRaises(I.InventoryError):inspect(root)

    def test_invalid_inventory_write_authority_rejected(self):
        with TemporaryDirectory() as root:
            a=I.inspect(root,'minute');a['market_files_written']=True
            with self.assertRaisesRegex(G.GapError,'INVENTORY_INVALID'):
                G.inspect(root,root,audit_reader=audit(),inventory_reader=lambda r,k:a)

    def test_fake_inventory_physical_byte_count_rejected(self):
        with TemporaryDirectory() as root:
            write(root,'probe.jsonl',rows())
            inv=I.inspect(root,'minute')
            inv['files'][0]['observed_file_bytes']+=1
            with self.assertRaisesRegex(G.GapError,'WINDOW_CONTENT_OR_SCOPE_UNVERIFIED'):
                G.inspect(root,root,audit_reader=audit(),inventory_reader=lambda r,k:inv)

    def test_fake_inventory_qmt_cache_mutation_rejected(self):
        with TemporaryDirectory() as root:
            inv=I.inspect(root,'minute')
            inv['qmt_cache_modified']=True
            with self.assertRaisesRegex(G.GapError,'INVENTORY_INVALID'):
                G.inspect(root,root,audit_reader=audit(),inventory_reader=lambda r,k:inv)

    def test_one_file_beyond_p35_budget_rejected_before_decode(self):
        with TemporaryDirectory() as root:
            write(root,'probe.jsonl',rows())
            with mock.patch.object(M,'MAX_BYTES',64):
                with self.assertRaisesRegex(G.GapError,'PROBE_SIZE_OUTSIDE'):
                    inspect(root)

    def test_deterministic_no_access_report_scope(self):
        with TemporaryDirectory() as root:
            a=inspect(root);b=inspect(root)
            self.assertEqual(a,b)
            self.assertEqual(len(a['diagnostic_scope_sha256']),64)

    def test_bounded_number_of_probe_files(self):
        with TemporaryDirectory() as root:
            for i in range(G.MAX_PROBES+1):
                write(root,f'{i:03}.jsonl',rows('000001.SZ'))
            with self.assertRaisesRegex(G.GapError,'INVENTORY_INVALID'):
                inspect(root)

    def test_cli_error_hides_private_absolute_paths(self):
        buf=StringIO()
        with contextlib.redirect_stdout(buf):
            code=G.main(['--module-root','/secret/private-source',
                         '--minute-evidence-root','/secret/private-probes'])
        self.assertEqual(code,3)
        self.assertNotIn('/secret/private',buf.getvalue())

    def test_no_xtquant_qmt_download_or_market_write(self):
        import inspect
        s=inspect.getsource(G)
        for token in ('get_market_data_ex(', 'download_history_data(',
                      'write_bytes(', 'write_table(', 'os.replace(', 'mkdir('):
            self.assertNotIn(token,s)


if __name__=='__main__':
    unittest.main()
