"""Offline tests for full-length WeCom completion push; no network or UI."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import market_update_push as P


def fixture_report(detail="验证完成"):
    stages = tuple(P.STAGES)
    return {
        "format": "qmt_daily_single_trigger_v3",
        "status": "SUCCESS",
        "china_start": "2026-11-23T20:05:00+08:00",
        "started_local": "2026-11-23T20:05:00+08:00",
        "finished_local": "2026-11-23T21:10:00+08:00",
        "steps_completed": list(stages),
        "stage_records": {name: {"exit_code": 0, "log_path": "local"}
                          for name in stages},
        "validation": {
            "data_validation": "PARTIAL",
            "cross_validation": "UNVERIFIED",
            "sections": {stage: {"execution": "PASS",
                                 "data_validation": "PASS",
                                 "cross_validation": "UNVERIFIED",
                                 "detail": detail}
                         for stage in stages},
        },
        "errors": [],
    }


class CompletionPushTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.receipt = self.root / "receipt.json"
        self.config = self.root / "private.json"
        self.outbox = self.root / "outbox"
        self.write_receipt(fixture_report())

    def write_receipt(self, report):
        self.receipt.write_text(json.dumps(report, ensure_ascii=False),
                                encoding="utf-8")

    def write_app_config(self):
        self.config.write_text(json.dumps({
            "provider": "wecom_app", "corp_id": "corp-fake",
            "corp_secret": "secret-fake", "agent_id": 10001,
            "to_user": "fake-user",
        }), encoding="utf-8")

    def test_dry_run_does_not_write_or_send(self):
        self.write_app_config()
        def never(*_args):
            raise AssertionError("No outbound notification on preview")
        result = P.dispatch(
            self.receipt, self.config, self.outbox,
            dry_run=True, transport=never)
        self.assertEqual(result["status"], "DRY_RUN_NO_EXTERNAL_SEND")
        self.assertFalse(self.outbox.exists())
        self.assertIn("QMT财务", result["text"])

    def test_no_config_retains_full_local_receipt_not_false_success(self):
        res = P.dispatch(self.receipt, self.config, self.outbox)
        self.assertEqual(res["status"],
                         "NOT_CONFIGURED_LOCAL_RECEIPT_RETAINED")
        self.assertEqual(len(list(self.outbox.glob("*.json"))), 1)
        text_files = list(self.outbox.glob("*.txt"))
        self.assertEqual(len(text_files), 1)
        self.assertEqual(text_files[0].read_text(encoding="utf-8"),
                         P._report_text(fixture_report()))
        with self.assertRaises(P.PushBlocked):
            # Prevent duplicate sends if status becomes ambiguous
            P._checked_config(self.config)

    def test_unicode_full_text_is_numbered_and_not_truncated(self):
        big_detail = "完整财务摘要" * 270
        doc = fixture_report(big_detail)
        self.write_receipt(doc)
        self.write_app_config()
        messages = []
        def simulated(_cfg, part):
            messages.append(part)
        out = P.dispatch(
            self.receipt, self.config, self.outbox, transport=simulated)
        self.assertEqual(out["status"], "ALL_PARTS_API_ACK")
        self.assertGreater(len(messages), 1)
        self.assertEqual(len(messages), out["parts"])
        self.assertTrue(all(len(m.encode("utf-8")) <= 1700 for m in messages))
        for i, part in enumerate(messages, 1):
            self.assertTrue(part.startswith(f"【A股更新 {i}/{len(messages)}】"))
        raw = "".join(part.split("\n", 1)[1] for part in messages)
        self.assertEqual(raw, P._report_text(doc))
        self.assertIn(big_detail, raw)

    def test_existing_provider_ack_is_idempotent(self):
        self.write_app_config()
        observed = []
        first = P.dispatch(
            self.receipt, self.config, self.outbox,
            transport=lambda _cfg, msg: observed.append(msg))
        second = P.dispatch(
            self.receipt, self.config, self.outbox,
            transport=lambda _cfg, msg: (_ for _ in ()).throw(
                AssertionError("Must not send same run twice")))
        self.assertEqual(first["status"], "ALL_PARTS_API_ACK")
        self.assertEqual(second["status"], "ALREADY_ACKED")
        self.assertEqual(len(observed), 1)

    def test_uncertain_send_never_automatically_replays(self):
        self.write_app_config()
        def ambiguous(*_args):
            raise TimeoutError("mock request delivered but response lost")
        with self.assertRaisesRegex(P.PushBlocked, "NOT_CONFIRMED"):
            P.dispatch(self.receipt, self.config, self.outbox,
                       transport=ambiguous)
        with self.assertRaisesRegex(P.PushBlocked, "UNCERTAIN"):
            P.dispatch(self.receipt, self.config, self.outbox,
                       transport=lambda *_: None)
        state = json.loads(next(self.outbox.glob("*.json")).read_text())
        self.assertIn("UNKNOWN", state["parts"])

    def test_stale_completion_receipt_refused_before_send(self):
        self.write_app_config()
        with self.assertRaisesRegex(P.PushBlocked, "STALE"):
            P.dispatch(self.receipt, self.config, self.outbox,
                       expected_start="wrong")
        self.assertFalse(self.outbox.exists())

    def test_deferred_finance_is_not_mislabeled_completed(self):
        doc = fixture_report()
        doc["status"] = "PARTIAL"
        doc["steps_completed"].remove("FINANCIAL_DAILY")
        doc["stage_records"]["FINANCIAL_DAILY"] = {
            "status": "DEFERRED_CUTOFF", "exit_code": 87,
            "log_path": "local"}
        doc["finance_deferred_by_cutoff"] = True
        text = P._report_text(doc)
        self.assertIn("顺延下次", text)
        self.assertIn("财务顺延", text)
        self.assertNotIn("QMT财务：运行完成", text)

    def test_real_canary_is_explicit_and_has_no_market_data_actions(self):
        self.write_app_config()
        sent = []
        with patch.object(P, "_send_one",
                          side_effect=lambda cfg, text:
                              sent.append((cfg["provider"], text))):
            result = P.main(["--config", str(self.config), "--canary-send"])
        self.assertEqual(result, 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "wecom_app")
        self.assertIn("手动发送的测试消息", sent[0][1])
        self.assertIn("没有执行K线或财务更新", sent[0][1])
        self.assertFalse(self.outbox.exists())

    def _canary_with_fake_provider(self, responses):
        self.write_app_config()
        output = io.StringIO()
        with patch.object(P, "_http_json", side_effect=responses) as provider:
            with redirect_stdout(output):
                status = P.main(["--config", str(self.config), "--canary-send"])
        self.assertEqual(status, 2)
        self.assertNotIn("MARKET_PUSH_CANARY_PROVIDER_ACK=TRUE", output.getvalue())
        self.assertEqual(provider.call_count, len(responses))
        marker = "MARKET_PUSH_CANARY_DIAGNOSTIC="
        self.assertIn(marker, output.getvalue())
        diagnostic = json.loads(output.getvalue().split(marker, 1)[1].strip())
        self.assertEqual(diagnostic["status"], "NOT_CONFIRMED")
        return diagnostic, output.getvalue()

    def test_canary_token_error_code_printed_without_credentials(self):
        diagnostic, output = self._canary_with_fake_provider([
            {"errcode": 40013, "errmsg": "LEAK_SECRET_userid"},
        ])
        self.assertEqual(diagnostic["stage"], "TOKEN")
        self.assertEqual(diagnostic["reason"], "WECOM_ACCESS_TOKEN_REJECTED")
        self.assertEqual(diagnostic["provider_errcode"], 40013)
        self.assertNotIn("LEAK_SECRET_userid", output)
        self.assertNotIn("secret-fake", output)
        self.assertNotIn("corp-fake", output)

    def test_canary_send_error_code_printed_without_token_or_raw_errmsg(self):
        diagnostic, output = self._canary_with_fake_provider([
            {"errcode": 0, "access_token": "EXAMPLE_TOKEN_PRIVATE"},
            {"errcode": 60020, "errmsg": "LEAK_USER_ID"},
        ])
        self.assertEqual(diagnostic["stage"], "MESSAGE_SEND")
        self.assertEqual(diagnostic["provider_errcode"], 60020)
        self.assertEqual(diagnostic["reason"], "WECOM_PROVIDER_MESSAGE_REJECTED")
        self.assertNotIn("EXAMPLE_TOKEN_PRIVATE", output)
        self.assertNotIn("LEAK_USER_ID", output)
        self.assertNotIn("fake-user", output)

    def test_canary_invalid_recipient_never_prints_user_identifier(self):
        diagnostic, output = self._canary_with_fake_provider([
            {"errcode": 0, "access_token": "TESTTOKEN"},
            {"errcode": 0, "invaliduser": "USER_ID_SHOULD_NOT_PRINT"},
        ])
        self.assertEqual(diagnostic["stage"], "MESSAGE_SEND")
        self.assertEqual(diagnostic["reason"], "WECOM_APP_RECIPIENT_NOT_ACCEPTED")
        self.assertNotIn("USER_ID_SHOULD_NOT_PRINT", output)

    def test_canary_http_error_prints_safe_status_never_secret_url(self):
        self.write_app_config()
        error = HTTPError(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpsecret=PRIVATE",
            403, "SECRET_REASON", {}, None)
        output = io.StringIO()
        with patch.object(P, "_http_json", side_effect=error) as provider:
            with redirect_stdout(output):
                status = P.main(["--config", str(self.config), "--canary-send"])
        self.assertEqual(status, 2)
        self.assertEqual(provider.call_count, 1)
        detail = json.loads(output.getvalue().split(
            "MARKET_PUSH_CANARY_DIAGNOSTIC=", 1)[1].strip())
        self.assertEqual(detail["stage"], "TOKEN")
        self.assertEqual(detail["http_status"], 403)
        self.assertEqual(detail["reason"], "WECOM_HTTP_ERROR")
        self.assertNotIn("corpsecret=PRIVATE", output)
        self.assertNotIn("SECRET_REASON", output)

    def test_canary_network_error_prints_stage_without_raw_exception(self):
        self.write_app_config()
        output = io.StringIO()
        with patch.object(P, "_http_json",
                          side_effect=URLError("SECRET_PROXY_ADDRESS")) as provider:
            with redirect_stdout(output):
                status = P.main(["--config", str(self.config), "--canary-send"])
        self.assertEqual(status, 2)
        self.assertEqual(provider.call_count, 1)
        detail = json.loads(output.getvalue().split(
            "MARKET_PUSH_CANARY_DIAGNOSTIC=", 1)[1].strip())
        self.assertEqual(detail["stage"], "TOKEN")
        self.assertEqual(detail["reason"], "WECOM_TRANSPORT_ERROR")
        self.assertNotIn("SECRET_PROXY_ADDRESS", output)

    def test_malformed_provider_response_does_not_leak_response_text(self):
        self.write_app_config()
        output = io.StringIO()
        with patch.object(P, "_http_json",
                          side_effect=ValueError("SECRET_FULL_RESPONSE")):
            with redirect_stdout(output):
                status = P.main(["--config", str(self.config), "--canary-send"])
        self.assertEqual(status, 2)
        self.assertIn('"reason": "WECOM_RESPONSE_PARSE_ERROR"', output.getvalue())
        self.assertNotIn("SECRET_FULL_RESPONSE", output.getvalue())

    def test_provider_numeric_error_can_be_negative_and_no_message_sent(self):
        diagnostic, output = self._canary_with_fake_provider([
            {"errcode": -1, "errmsg": "SECRET_STATUS"},
        ])
        self.assertEqual(diagnostic["stage"], "TOKEN")
        self.assertEqual(diagnostic["provider_errcode"], -1)
        self.assertNotIn("SECRET_STATUS", output)

    def test_safe_diagnostic_never_echoes_arbitrary_exception_text(self):
        report = P._safe_diagnostic(RuntimeError("PRIVATE_APP_SECRET"))
        self.assertEqual(report["reason"], "UNEXPECTED_ERROR")
        self.assertEqual(report["stage"], "UNKNOWN")
        self.assertNotIn("PRIVATE_APP_SECRET", json.dumps(report))

    def test_config_validation_still_performs_no_provider_request(self):
        self.write_app_config()
        with patch.object(P, "_http_json",
                          side_effect=AssertionError("VALIDATE_MUST_BE_OFFLINE")):
            with redirect_stdout(io.StringIO()) as output:
                result = P.main(["--config", str(self.config),
                                 "--validate-config"])
        self.assertEqual(result, 0)
        self.assertIn("MARKET_PUSH_CONFIG_VALID=wecom_app", output.getvalue())

    def test_wecom_app_uses_correct_routes_and_acks(self):
        self.write_app_config()
        cfg = P._checked_config(self.config)
        seen = []
        def fake_http(url, *, payload=None):
            seen.append((url, payload))
            if payload is None:
                return {"errcode": 0, "access_token": "temporary-fake"}
            return {"errcode": 0}
        with patch.object(P, "_http_json", side_effect=fake_http):
            P._send_one(cfg, "测试消息")
        self.assertIn("/cgi-bin/gettoken", seen[0][0])
        self.assertIn("/cgi-bin/message/send", seen[1][0])
        self.assertEqual(seen[1][1]["text"]["content"], "测试消息")
        self.assertEqual(seen[1][1]["touser"], "fake-user")

    def test_wecom_webhook_restricts_domain_and_accepts_provider_ack(self):
        self.config.write_text(json.dumps({
            "provider": "wecom_webhook",
            "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fake"
        }), encoding="utf-8")
        cfg = P._checked_config(self.config)
        with patch.object(P, "_http_json", return_value={"errcode": 0}) as http:
            P._send_one(cfg, "测试消息")
        self.assertEqual(http.call_args.kwargs["payload"]["msgtype"], "text")
        self.config.write_text(json.dumps({
            "provider": "wecom_webhook",
            "webhook_url": "https://evil.invalid/cgi-bin/webhook/send?key=x",
        }), encoding="utf-8")
        with self.assertRaises(P.PushBlocked):
            P._checked_config(self.config)

    def test_wecom_provider_error_is_not_claimed_as_delivered(self):
        self.write_app_config()
        cfg = P._checked_config(self.config)
        with patch.object(P, "_http_json", side_effect=[
                {"errcode": 0, "access_token": "temporary-fake"},
                {"errcode": 40003}]):
            with self.assertRaisesRegex(P.PushBlocked, "REJECTED"):
                P._send_one(cfg, "test")


if __name__ == "__main__":
    unittest.main()
