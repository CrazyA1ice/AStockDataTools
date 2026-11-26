"""Real on-disk SHA receipt chain with synthetic DAY row evidence (no QMT)."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import market_live_day_overlay_audit as O
from market_official_day_content_readonly import DayContentError


def row(day='2026-11-25',symbol='SH605336',*,open=7.62):
    from datetime import datetime,timezone,timedelta
    stamp=int(datetime.fromisoformat(day).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    return {'ts':stamp,'symbol':symbol,'open':open,'high':8.31,'low':7.62,
            'close':7.95,'volume':1535000.,'amount':12337154.}


class OverlayAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'ParquetLiveSync'
        self.work=self.root/'work'
        self.work.mkdir(parents=True)
        self.day='2026-11-25'
        self.symbol='SH605336'
        self.day_rows=[row()]
        self.init_files()

    def init_files(self):
        name=self.day
        rel=f'incremental/day/year={name[:4]}/{name}.parquet'
        parquet=self.work/rel
        parquet.parent.mkdir(parents=True,exist_ok=True)
        parquet.write_bytes(('synthetic Arrow day file '+name).encode())
        dhash=sha256(parquet.read_bytes()).hexdigest()
        zip_sha='b'*64
        rec={'date':name,'file':rel,'sha256':dhash,'rows':len(self.day_rows),
             'raw_zip_sha256':zip_sha,'origin':'declared tdx route',
             'base_dataset_sha256':O.BASE_SHA,
             'original_Parquet_files_unchanged':True,
             'source_values_adj':'none',
             'calibration':{'factor':1.}}
        receipt=parquet.with_suffix('.json')
        receipt.write_text(json.dumps(rec,sort_keys=True),encoding='utf-8')
        state={'format':O.FORMAT,'base_dataset_sha256':O.BASE_SHA,
               'base_day':O.BASE_DAY.isoformat(),'production_activated':False,
               'days':{name:{'file':rel,'rows':len(self.day_rows),'sha256':dhash,
                              'receipt_sha256':sha256(receipt.read_bytes()).hexdigest(),
                              'source_zip_sha256':zip_sha}}}
        (self.work/'state.json').write_text(json.dumps(state,sort_keys=True),encoding='utf-8')
        self.file=parquet;self.receipt=receipt

    def audit(self,reader=None,raw_zip_relative=None):
        return O.inspect(self.root,self.day,self.symbol,raw_zip_relative=raw_zip_relative,
                         day_reader=reader or (lambda path:iter(self.day_rows)))

    def test_valid_full_chain_rechecks_disk_and_provenance_limits(self):
        r=self.audit()
        self.assertEqual(r['status'],O.STATUS)
        self.assertEqual(r['target_ohlcva']['open'],7.62)
        self.assertEqual(r['day_overlay_parquet_bytes_sha256'],sha256(self.file.read_bytes()).hexdigest())
        self.assertEqual(r['day_overlay_receipt_bytes_sha256'],sha256(self.receipt.read_bytes()).hexdigest())
        self.assertFalse(r['tdx_raw_zip_bytes_verified'])
        self.assertFalse(r['provider_identity_authenticated'])
        self.assertFalse(r['whole_exchange_stock_day_universe_certified'])
        self.assertFalse(r['market_files_written'])
        self.assertEqual(r['qmt_history_download_calls'],0)

    def test_bytes_and_directory_contents_unchanged(self):
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.work.rglob('*') if p.is_file()}
        self.audit()
        after={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.work.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_other_valid_postcutoff_dates_and_symbols(self):
        for day,symbol in [('2026-10-14','SZ300119'),('2027-01-08','BJ920021')]:
            with self.subTest(day=day):
                self.day,self.symbol=day,symbol
                self.day_rows=[row(day,symbol)]
                self.init_files()
                self.assertEqual(self.audit()['symbol'],symbol)

    def test_missing_selected_day_fails_even_if_state_other_days_exist(self):
        with self.assertRaisesRegex(O.OverlayError,'DAY_NOT_FOUND'):
            O.inspect(self.root,'2026-11-24',self.symbol,day_reader=lambda _:iter(self.day_rows))

    def test_pre_base_overlay_date_fails(self):
        with self.assertRaisesRegex(O.OverlayError,'DAY_NOT_IN_OVERLAY_WINDOW'):
            O.inspect(self.root,'2026-10-13',self.symbol,day_reader=lambda _:iter(self.day_rows))

    def test_wrong_date_or_symbol_rejected(self):
        for date_,sym in [('2026-02-30',self.symbol),('2026-11-25','invalid')]:
            with self.subTest(date=date_,sym=sym):
                with self.assertRaises(O.OverlayError):
                    O.inspect(self.root,date_,sym,day_reader=lambda _:iter(self.day_rows))

    def test_changed_parquet_sha_rejected(self):
        self.file.write_bytes(b'changed bytes')
        with self.assertRaisesRegex(DayContentError,'DAY_FILE_SHA_CHANGED'):
            self.audit()

    def test_changed_receipt_bytes_without_state_update_rejected(self):
        self.receipt.write_bytes(self.receipt.read_bytes()+b' ')
        with self.assertRaisesRegex(O.OverlayError,'DAY_OVERLAY_RECEIPT_CHAIN'):
            self.audit()

    def test_bad_source_zip_sha_receipt_chain_rejected(self):
        doc=json.loads(self.receipt.read_text());doc['raw_zip_sha256']='f'*64
        self.receipt.write_text(json.dumps(doc))
        state_path=self.work/'state.json'
        state=json.loads(state_path.read_text());state['days'][self.day]['receipt_sha256']=sha256(self.receipt.read_bytes()).hexdigest()
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(O.OverlayError,'DAY_OVERLAY_RECEIPT_CHAIN'):
            self.audit()

    def test_wrong_state_identity_rejected(self):
        path=self.work/'state.json'
        state=json.loads(path.read_text());state['base_dataset_sha256']='f'*64
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(O.OverlayError,'OVERLAY_STATE_IDENTITY'):
            self.audit()

    def test_bad_receipt_row_count_mismatch_proven_by_contents(self):
        doc=json.loads(self.receipt.read_text());doc['rows']=2
        self.receipt.write_text(json.dumps(doc))
        p=self.work/'state.json';state=json.loads(p.read_text())
        state['days'][self.day]['rows']=2
        state['days'][self.day]['receipt_sha256']=sha256(self.receipt.read_bytes()).hexdigest()
        p.write_text(json.dumps(state))
        with self.assertRaisesRegex(O.OverlayError,'DAY_OVERLAY_ROW_COUNT'):
            self.audit()

    def test_wrong_target_symbol_missing(self):
        with self.assertRaisesRegex(DayContentError,'TARGET_EQUITY_NOT_IN_DAY_EXPORT'):
            O.inspect(self.root,self.day,'SH600000',day_reader=lambda _:iter(self.day_rows))

    def test_target_bad_ohlc_fails(self):
        bad=dict(self.day_rows[0]);bad['high']=5.
        with self.assertRaisesRegex(DayContentError,'DAY_OHLC_ENVELOPE'):
            self.audit(reader=lambda _:iter([bad]))

    def test_state_mutated_while_content_read_is_rejected(self):
        def mutate(_):
            path=self.work/'state.json'
            state=json.loads(path.read_text());state['audit_timestamp_note']='changed while reading'
            path.write_text(json.dumps(state))
            return iter(self.day_rows)
        with self.assertRaisesRegex(O.OverlayError,'OVERLAY_STATE_OR_RECEIPT_CHANGED'):
            self.audit(mutate)

    def test_receipt_mutated_during_parquet_content_read_is_rejected(self):
        def mutate(_):
            self.receipt.write_bytes(self.receipt.read_bytes()+b' ')
            return iter(self.day_rows)
        with self.assertRaisesRegex(O.OverlayError,'OVERLAY_STATE_OR_RECEIPT_CHANGED'):
            self.audit(mutate)

    def test_duplicate_json_state_keys_rejected(self):
        p=self.work/'state.json'
        p.write_text('{"format":"FAKE",'+p.read_text()[1:])
        with self.assertRaisesRegex(O.OverlayError,'DUPLICATE_JSON_KEY'):
            self.audit()

    def test_symlinked_receipt_forbidden(self):
        backup=self.work/'backup.json'
        backup.write_bytes(self.receipt.read_bytes())
        self.receipt.unlink()
        try:self.receipt.symlink_to(backup)
        except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_SYMLINK_FORBIDDEN'):
            self.audit()

    def test_explicit_existing_zip_bytes_verified_but_provider_remains_unproven(self):
        zip_path=self.work/'downloads'/'source.zip'
        zip_path.parent.mkdir();zip_path.write_bytes(b'fake-zip-contents-for-sha-only')
        actual=sha256(zip_path.read_bytes()).hexdigest()
        doc=json.loads(self.receipt.read_text());doc['raw_zip_sha256']=actual
        self.receipt.write_text(json.dumps(doc))
        st=self.work/'state.json';state=json.loads(st.read_text())
        state['days'][self.day]['source_zip_sha256']=actual
        state['days'][self.day]['receipt_sha256']=sha256(self.receipt.read_bytes()).hexdigest()
        st.write_text(json.dumps(state))
        output=self.audit(raw_zip_relative='downloads/source.zip')
        self.assertTrue(output['tdx_raw_zip_bytes_verified'])
        self.assertEqual(output['tdx_raw_zip_file_bytes_sha256_if_checked'],actual)
        self.assertFalse(output['provider_identity_authenticated'])
        self.assertFalse(output['market_data_write_authorized'])

    def test_wrong_explicit_zip_sha_refused(self):
        folder=self.work/'downloads';folder.mkdir()
        (folder/'source.zip').write_bytes(b'unrelated zip bytes')
        with self.assertRaisesRegex(O.OverlayError,'DECLARED_RAW_TDX_ZIP_BYTES_MISMATCH'):
            self.audit(raw_zip_relative='downloads/source.zip')

    def test_zip_not_explicitly_given_is_never_searched(self):
        folder=self.work/'downloads';folder.mkdir()
        (folder/'source.zip').write_bytes(b'unrelated zip bytes')
        out=self.audit()
        self.assertIsNone(out['tdx_raw_zip_file_bytes_sha256_if_checked'])
        self.assertFalse(out['tdx_raw_zip_bytes_verified'])

    def test_zip_path_escape_fails_closed(self):
        with self.assertRaises(ValueError):
            self.audit(raw_zip_relative='../other/source.zip')

    def test_no_state_file_refuses_not_silently_empty(self):
        (self.work/'state.json').unlink()
        with self.assertRaisesRegex(ValueError,'ARTIFACT_MISSING_OR_NONFILE'):
            self.audit()

    def test_production_activated_flag_fails_closed(self):
        p=self.work/'state.json';st=json.loads(p.read_text());st['production_activated']=True
        p.write_text(json.dumps(st))
        with self.assertRaisesRegex(O.OverlayError,'OVERLAY_STATE_IDENTITY'):
            self.audit()

    def test_state_entry_redirect_refused_even_if_same_sha(self):
        p=self.work/'state.json';st=json.loads(p.read_text())
        st['days'][self.day]['file']='incremental/day/year=2026/other.parquet'
        p.write_text(json.dumps(st))
        with self.assertRaisesRegex(O.OverlayError,'DAY_OVERLAY_STATE_ENTRY'):
            self.audit()

if __name__=='__main__':unittest.main()

class RealParquetStateReceiptTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib').util.find_spec('pyarrow') is not None,
                         'requires pyarrow for actual Arrow/Parquet end-to-end proof')
    def test_actual_temporary_arrow_day_state_receipt_and_parquet(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'ParquetLiveSync';work=root/'work'
            folder=work/'incremental'/'day'/'year=2026'
            folder.mkdir(parents=True)
            day='2026-11-25';sym='SH605336'
            rel=f'incremental/day/year=2026/{day}.parquet'
            fields=[pa.field('ts',pa.int64()),pa.field('symbol',pa.string())]+[
                pa.field(k,pa.float64()) for k in ('open','high','low','close','volume','amount')]
            table=pa.Table.from_pylist([row()],schema=pa.schema(fields))
            file=folder/(day+'.parquet')
            pq.write_table(table,file)
            data_sha=sha256(file.read_bytes()).hexdigest()
            receipt={'date':day,'file':rel,'sha256':data_sha,'rows':1,
                     'raw_zip_sha256':'b'*64,'origin':'synthetic-local-test',
                     'base_dataset_sha256':O.BASE_SHA,
                     'original_Parquet_files_unchanged':True,
                     'source_values_adj':'none','calibration':{'factor':1.0}}
            rec=file.with_suffix('.json');rec.write_text(json.dumps(receipt))
            state={'format':O.FORMAT,'base_dataset_sha256':O.BASE_SHA,
                   'base_day':O.BASE_DAY.isoformat(),'production_activated':False,
                   'days':{day:{'file':rel,'sha256':data_sha,'rows':1,
                                'receipt_sha256':sha256(rec.read_bytes()).hexdigest(),
                                'source_zip_sha256':'b'*64}}}
            (work/'state.json').write_text(json.dumps(state))
            output=O.inspect(root,day,sym)
            self.assertEqual(output['day_overlay_rows_verified'],1)
            self.assertEqual(output['day_overlay_parquet_bytes_sha256'],data_sha)
            self.assertFalse(output['market_files_written'])
            self.assertFalse(output['provider_identity_authenticated'])
