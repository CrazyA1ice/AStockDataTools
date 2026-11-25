"""Pure offline contract checks; no QMT, network, TaskScheduler or provider."""
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / 'market_wecom_report.py'
spec = importlib.util.spec_from_file_location('market_wecom_report', MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def receipt(date='2026-11-26'):
    return {
        'format': 'qmt_daily_single_trigger_v3', 'invocation': 'Scheduled',
        'mode': 'UNIFIED_SINGLE_RUN', 'run_scope': 'ALL_FOUR_SECTIONS',
        'history_only': False, 'china_start': date+'T20:05:05+08:00',
        'finished_local': date+'T22:30:00+08:00', 'status': 'SUCCESS',
        'qmt_preflight_status': 'CONNECTED',
        'stage_records': {n:{'exit_code':0} for n in m.STAGES},
        'steps_completed': list(m.STAGES), 'errors': [],
        'validation': {'execution':'PASS','data_validation':'PARTIAL',
                       'cross_validation':'UNVERIFIED','routine_continuation':True},
        'operational_classification':'ROUTINE_CONTINUATION',
    }


class MarketWecomReportTests(unittest.TestCase):
    def setUp(self):
        self.d = receipt()
        self.now = datetime.fromisoformat('2026-11-26T23:00:00+08:00')

    def test_valid_scheduled_receipt(self):
        self.assertEqual(m.check_contract(self.d,'2026-11-26',self.now).hour,20)

    def test_task_start_matches_scheduled_receipt(self):
        task={'state':'Ready','last_result':0,'last_run':'2026-11-26T20:05:05+08:00'}
        m.validate_task_completion(task,m.receipt_date(self.d))
        task['last_run']='2026-11-26T18:05:05+08:00'
        with self.assertRaisesRegex(m.UnsafeReport,'DIVERGED'):
            m.validate_task_completion(task,m.receipt_date(self.d))

    def test_preview_does_not_write_intent_or_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'receipt.json';p.write_text(json.dumps(self.d),encoding='utf-8')
            intent=Path(tmp)/'intent'
            args=type('Args',(),{'date':'2026-11-26','mode':'preview','receipt':str(p),
                                 'intent_dir':str(intent)})()
            task={'state':'Ready','last_result':0,'last_run':'2026-11-26T20:05:05+08:00'}
            with mock.patch.object(m,'now_china',return_value=self.now), \
                 mock.patch.object(m,'market_task_info',return_value=task), \
                 mock.patch.object(m,'dispatch') as d:
                self.assertEqual(m.run(args),0)
                d.assert_not_called()
                self.assertFalse(intent.exists())

    def test_once_reserves_and_dispatches_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'receipt.json';p.write_text(json.dumps(self.d),encoding='utf-8')
            key=Path(tmp)/'key';key.write_text('fake-key')
            intent=Path(tmp)/'intent'
            args=type('Args',(),{'date':'2026-11-26','mode':'once','receipt':str(p),
                                 'intent_dir':str(intent),'ssh_key':str(key),'approve_self_send':True,
                                 'server':'ubuntu@43.142.32.208','remote':m.DEFAULT_REMOTE})()
            task={'state':'Ready','last_result':0,'last_run':'2026-11-26T20:05:05+08:00'}
            with mock.patch.object(m,'now_china',return_value=self.now), \
                 mock.patch.object(m,'market_task_info',return_value=task), \
                 mock.patch.object(m,'dispatch',return_value=(0,['WECOM_MARKET_API_ACK_NOT_DEVICE_PROOF'])) as d:
                self.assertEqual(m.run(args),0)
                d.assert_called_once()
                with self.assertRaises(FileExistsError):
                    m.run(args)
                self.assertEqual(d.call_count,1)
                self.assertTrue((intent/'2026-11-26.intent.json').exists())

    def test_stale_receipt_does_not_send(self):
        with self.assertRaisesRegex(m.UnsafeReport,'TODAYS'):
            m.check_contract(self.d,'2026-11-27',self.now)

    def test_manual_run_rejected(self):
        self.d['invocation'] = 'Manual'
        with self.assertRaises(m.UnsafeReport):
            m.check_contract(self.d,'2026-11-26',self.now)

    def test_history_only_rejected(self):
        self.d['history_only'] = True
        with self.assertRaises(m.UnsafeReport):
            m.check_contract(self.d,'2026-11-26',self.now)

    def test_wrong_run_scope_rejected(self):
        self.d['run_scope']='EIGHT_PERIODS'
        with self.assertRaises(m.UnsafeReport):
            m.check_contract(self.d,'2026-11-26',self.now)

    def test_stale_ten_hour_window(self):
        with self.assertRaises(m.UnsafeReport):
            m.check_contract(self.d,'2026-11-26',self.now + timedelta(hours=15))

    def test_real_powershell_china_wall_clock_timestamp_is_accepted(self):
        # Observed same-run canonical 20:05 receipt:
        # 2026-11-25T20:05:02.9370848 (no timezone suffix).
        self.d['china_start'] = '2026-11-26T20:05:02.9370848'
        dt = m.check_contract(self.d,'2026-11-26',self.now)
        self.assertEqual(dt.utcoffset(),timedelta(hours=8))
        self.assertEqual(dt.minute,5)

    def test_naive_timestamp_must_still_match_real_windows_task(self):
        self.d['china_start'] = '2026-11-26T20:05:02.9370848'
        task={'state':'Ready','last_result':1,'last_run':'2026-11-26T20:05:05+08:00'}
        m.validate_task_completion(task,m.receipt_date(self.d))
        task['last_run']='2026-11-25T20:05:05+08:00'
        with self.assertRaisesRegex(m.UnsafeReport,'DIVERGED'):
            m.validate_task_completion(task,m.receipt_date(self.d))

    def test_wrong_explicit_timezone_rejected(self):
        self.d['china_start'] = '2026-11-26T20:05:05+09:00'
        with self.assertRaisesRegex(m.UnsafeReport,'OFFSET_NOT_PLUS8'):
            m.check_contract(self.d,'2026-11-26',self.now)

    def test_real_partial_report_exposes_quarantine_financial_and_adjustment(self):
        self.d['china_start'] = '2026-11-26T20:05:02.9370848'
        self.d['status'] = 'PARTIAL'
        self.d['validation'] = {
            'execution':'PASS','data_validation':'PARTIAL',
            'cross_validation':'UNVERIFIED','routine_continuation':False,
            'sections':{
                'EIGHT_PERIODS':{'execution':'PASS','data_validation':'PARTIAL','cross_validation':'PASS'},
                'FINANCIAL_DAILY':{'execution':'PASS','data_validation':'PARTIAL','cross_validation':'UNVERIFIED','processed':177,'pending_total':77,'remaining_unvisited':4526},
                'SECTORS':{'execution':'PASS','data_validation':'PASS','cross_validation':'UNVERIFIED'},
                'ADJUSTMENTS_ROTATING':{'execution':'PASS','data_validation':'PARTIAL','cross_validation':'UNVERIFIED','processed':80,'next_batch_required':True}
            }}
        msg = m.format_message(self.d, {'last_result':1},'2026-11-26')
        self.assertIn('运行结果：PARTIAL',msg)
        self.assertIn('八周期：部分股票被隔离，仍需核查',msg)
        self.assertIn('EIGHT_PERIODS：退出0；数据PARTIAL；跨源PASS',msg)
        self.assertIn('待审77只',msg)
        self.assertIn('未遍历4526只',msg)
        self.assertIn('除权：后续仍需轮换',msg)
        self.assertIn('正常轮换：未确认',msg)
        self.assertLessEqual(len(msg.encode('utf-8')),2048)

    def test_incomplete_stages_report_failure_honestly(self):
        self.d['status'] = 'FAILED'; self.d['stage_records']={}; self.d['steps_completed']=[]
        self.d['errors']=['SECRET_NOT_TO_SEND']
        m.check_contract(self.d,'2026-11-26',self.now)
        msg=m.format_message(self.d, {'last_result':1},'2026-11-26')
        self.assertIn('FAILED',msg)
        self.assertNotIn('SECRET_NOT_TO_SEND',msg)
        self.assertIn('未执行',msg)

    def test_quality_partial_remains(self):
        msg=m.format_message(self.d, {'last_result':0},'2026-11-26')
        self.assertIn('PARTIAL',msg)
        self.assertIn('UNVERIFIED',msg)
        self.assertIn('全部认证',msg)

    def test_receipt_changed_detection_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'r.json'; p.write_text(json.dumps(self.d),encoding='utf-8')
            doc,digest=m.read_receipt(p)
            self.assertEqual(doc['status'],'SUCCESS')
            self.assertEqual(len(digest),64)

    def test_once_file_is_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            marker=m.reserve_once(d,'2026-11-26','a'*64)
            self.assertTrue(marker.is_file())
            with self.assertRaises(FileExistsError):
                m.reserve_once(d,'2026-11-26','b'*64)
            self.assertEqual(json.loads(marker.read_text())['status'],'RESERVED_UNKNOWN_NO_AUTORETRY')

    def test_bad_server_and_missing_key_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            key=Path(tmp)/'id'
            with self.assertRaises(m.UnsafeReport):
                m.dispatch('root@43.142.32.208',key,'message','2026-11-26','a'*64,m.DEFAULT_REMOTE)
            with self.assertRaises(m.UnsafeReport):
                m.dispatch('ubuntu@43.142.32.208',key,'message','2026-11-26','a'*64,m.DEFAULT_REMOTE)

    def test_ssh_timeout_never_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            key=Path(tmp)/'id'; key.write_text('mock')
            with mock.patch.object(m.subprocess,'run',side_effect=m.subprocess.TimeoutExpired('ssh',40)) as sub:
                with self.assertRaisesRegex(m.UnsafeReport,'DO_NOT_RETRY'):
                    m.dispatch('ubuntu@43.142.32.208',key,'msg','2026-11-26','a'*64,m.DEFAULT_REMOTE)
                sub.assert_called_once()

    def test_nov25_cutoff_prevents_resend(self):
        a=type('Args',(),{'date':'2026-11-25','mode':'once'})()
        with self.assertRaisesRegex(m.UnsafeReport,'NO_RESEND'):
            m.run(a)


if __name__ == '__main__':
    unittest.main()
