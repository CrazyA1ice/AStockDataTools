"""Offline provider simulation and durable at-most-once safety."""
import importlib.util
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / 'astock_market_wecom_server_once.py'
spec = importlib.util.spec_from_file_location('astock_market_wecom_server_once', MODULE)
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

FIXTURE_NOW = datetime.fromisoformat('2026-11-26T22:00:00+08:00')
REQUEST={'date':'2026-11-26','receipt_sha256':'a'*64,
         'text':'【A股每日更新详情｜2026-11-26】\n状态：PARTIAL'}
CONFIG={'corp_id':'ww-test','secret':'private','agent_id':100,'member_userid':'self',
        'member_is_active_in_app':True,'wechat_plugin_opted_in':True}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.clock = mock.patch.object(s, 'now_china', return_value=FIXTURE_NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_validate_rejects_mismatch(self):
        d=dict(REQUEST,text='other message content')
        with self.assertRaises(s.Refused):
            s.validate_request(d)

    def test_validate_rejects_over_limit(self):
        d=dict(REQUEST,text=REQUEST['text']+'abc'*1000)
        with self.assertRaises(s.Refused):
            s.validate_request(d)

    def test_never_send_future_or_stale_dates(self):
        with mock.patch.object(s,'now_china',return_value=datetime.fromisoformat('2026-11-28T22:00:00+08:00')):
            with self.assertRaisesRegex(s.Refused,'OUTSIDE_RUN_DATE_WINDOW'):
                s.validate_request(REQUEST)

    def test_early_day_disallowed(self):
        with mock.patch.object(s,'now_china',return_value=datetime.fromisoformat('2026-11-26T10:00:00+08:00')):
            with self.assertRaises(s.Refused):
                s.validate_request(REQUEST)

    def test_validate_accepts(self):
        self.assertEqual(s.validate_request(REQUEST)[0],'2026-11-26')

    def test_acks_once_only(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s,'OUTBOX',Path(tmp)/'out'), \
                mock.patch.object(s,'load_config',return_value=CONFIG), \
                mock.patch.object(s,'preflight',return_value='token'), \
                mock.patch.object(s,'api',return_value={'errcode':0}) as api:
            self.assertEqual(s.send_once(REQUEST),0)
            self.assertEqual(api.call_count,1)
            receipt=json.loads((s.OUTBOX/'2026-11-26.json').read_text())
            self.assertEqual(receipt['status'],'API_ACK_NOT_DEVICE_PROOF')
            with self.assertRaises(FileExistsError):
                s.send_once(REQUEST)
            self.assertEqual(api.call_count,1)

    def test_partial_user_not_ack(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s,'OUTBOX',Path(tmp)/'out'), \
                mock.patch.object(s,'load_config',return_value=CONFIG), \
                mock.patch.object(s,'preflight',return_value='token'), \
                mock.patch.object(s,'api',return_value={'errcode':0,'invaliduser':'self'}):
            self.assertEqual(s.send_once(REQUEST),4)
            self.assertEqual(json.loads((s.OUTBOX/'2026-11-26.json').read_text())['status'],'PROVIDER_REJECTED_OR_PARTIAL')

    def test_unknown_response_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s,'OUTBOX',Path(tmp)/'out'), \
                mock.patch.object(s,'load_config',return_value=CONFIG), \
                mock.patch.object(s,'preflight',return_value='token'), \
                mock.patch.object(s,'api',side_effect=TimeoutError('timeout')) as api:
            self.assertEqual(s.send_once(REQUEST),4)
            self.assertEqual(json.loads((s.OUTBOX/'2026-11-26.json').read_text())['status'],'UNKNOWN_NO_RETRY')
            with self.assertRaises(FileExistsError):
                s.send_once(REQUEST)
            api.assert_called_once()

    def test_preflight_fail_reserves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s,'OUTBOX',Path(tmp)/'out'), \
                mock.patch.object(s,'load_config',return_value=CONFIG), \
                mock.patch.object(s,'preflight',side_effect=s.Refused('SCOPE_INVALID')):
            with self.assertRaises(s.Refused):
                s.send_once(REQUEST)
            self.assertFalse(s.OUTBOX.exists())

    def test_no_redirect_and_fixed_api_paths(self):
        with self.assertRaises(s.Refused):
            s.api('anything-else')


if __name__ == '__main__':
    unittest.main()
