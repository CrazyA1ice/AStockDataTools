"""Synthetic-only normalised postclose overlay tests; never read real TDX/H5/PQ."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "postclose_private_overlay_under_test",
    HERE/"tdx-postclose-private-overlay.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def sample(period="5min",symbol="SH600000",day="2026-10-27"):
    return {
        "format":M.DOC_FORMAT,
        "source":"tdx_postclose_local",
        "symbol":symbol,"date":day,"period":period,
        "time_label_policy":M.PERIOD_POLICY[period],
        "bars":[{
            "time":label,"open":10.0,"high":11.0,
            "low":9.0,"close":10.5,
            "volume":100.0,"amount":1025.0,
        } for label in M.expected_times(period)],
    }


class TdxPrivateOverlayTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)/"module"
        self.home.mkdir()
        self.work=self.home/"work"/"tdx_postclose_overlay"
        self.reports=self.home/"reports"
        self.reports.mkdir()
        self.patches=[
            mock.patch.object(M,"MODULE",self.home),
            mock.patch.object(M,"WORK",self.work.resolve()),
            mock.patch.object(M,"REPORTS",self.reports.resolve()),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def input_file(self,record=None):
        target=self.home/"incoming.json"
        target.write_text(json.dumps(record or sample(),allow_nan=False),
                          encoding="utf-8")
        return target

    def test_normalized_three_period_grids_are_complete(self):
        for period,count in (("day",1),("5min",48),("1min",241)):
            with self.subTest(period=period):
                record=sample(period)
                safe=M.validate(record)
                self.assertEqual(safe["matching_bar_count"],count)
                self.assertFalse(safe["eligible_for_automatic_primary_source_union"])
                self.assertFalse(safe["exchange_calendar_independently_verified"])
        self.assertEqual(M.expected_times("5min")[0],"09:30")
        self.assertEqual(M.expected_times("5min")[-1],"14:55")
        self.assertEqual(M.expected_times("1min")[0],"09:30")
        self.assertEqual(M.expected_times("1min")[-1],"15:00")

    def test_incomplete_duplicate_unordered_or_bad_ohlc_is_rejected(self):
        base=sample()
        def shortened(x): x["bars"].pop()
        def repeated(x): x["bars"][1]["time"]="09:30"
        def swapped(x): x["bars"][0]["time"]="11:30"
        def negative(x): x["bars"][0]["volume"]=-2
        def range_bad(x): x["bars"][0]["high"]=7
        def nonfinite(x): x["bars"][0]["amount"]=float("nan")
        def zero_price(x): x["bars"][0]["close"]=0
        def wrong_source(x): x["source"]="unknown_binary"
        def wrong_policy(x): x["time_label_policy"]="five_minute_end_label"
        def b_share(x): x["symbol"]="SZ200001"
        def extra(x): x["bars"][0]["unapproved_field"]=1
        for transform in (shortened,repeated,swapped,negative,range_bad,
                          nonfinite,zero_price,wrong_source,wrong_policy,
                          b_share,extra):
            with self.subTest(transform=transform.__name__):
                rec=deepcopy(base)
                transform(rec)
                with self.assertRaises(ValueError):
                    M.validate(rec)

    def test_input_fingerprint_and_duplicate_json_key_handling(self):
        source=self.input_file()
        data,checksum=M.load_input(source)
        self.assertEqual(data["bars"][0]["time"],"09:30")
        self.assertRegex(checksum,r"^[0-9a-f]{64}$")
        source.write_text('{"a":1,"a":2}',encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Duplicate JSON object key"):
            M.load_input(source)
        source.write_text('{"a": NaN}',encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NaN/Infinity"):
            M.load_input(source)
        source.write_bytes(b" "* (M.MAX_INPUT_BYTES+1))
        with self.assertRaisesRegex(ValueError,"256 KiB"):
            M.load_input(source)

    def test_private_stage_version_change_rollback_and_reactivate(self):
        original=sample()
        first=M.stage(original,"a"*64)
        self.assertEqual(first["outcome"],"new_private_overlay_version")
        sha1=first["local_private_version_sha256"]
        private=M.private_dir("SH600000","5min","2026-10-27")
        self.assertTrue((private/"active.json").is_file())
        self.assertEqual(M.read_pointer(private),sha1)
        self.assertEqual(M.stage(original,"a"*64)["outcome"],"already_active")
        edited=deepcopy(original)
        edited["bars"][0]["amount"]+=1
        second=M.stage(edited,"b"*64)
        sha2=second["local_private_version_sha256"]
        self.assertNotEqual(sha1,sha2)
        self.assertEqual(M.read_pointer(private),sha2)
        self.assertEqual(M.rollback("SH600000","5min","2026-10-27")[
            "outcome"],"previous_version_restored")
        self.assertEqual(M.read_pointer(private),sha1)
        self.assertEqual(M.rollback("SH600000","5min","2026-10-27")[
            "outcome"],"active_overlay_disabled")
        self.assertIsNone(M.read_pointer(private))
        self.assertTrue((private/"versions"/(sha1+".json")).exists())
        self.assertTrue((private/"versions"/(sha2+".json")).exists())
        reactivated=M.stage(original,"a"*64)
        self.assertEqual(reactivated["outcome"],
                         "verified_private_version_reactivated")
        self.assertEqual(M.read_pointer(private),sha1)
        self.assertFalse((private/".operation.lock").exists())

    def test_reject_corrupted_version_and_pointer_without_source_edit(self):
        original=sample()
        out=M.stage(original,"a"*64)
        directory=M.private_dir("SH600000","5min","2026-10-27")
        digest=out["local_private_version_sha256"]
        version=directory/"versions"/(digest+".json")
        with version.open("r",encoding="utf-8") as fd:
            corrupted=json.load(fd)
        corrupted["record"]["bars"][0]["close"]=0.0
        version.write_text(json.dumps(corrupted),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"checksum mismatch"):
            M.rollback("SH600000","5min","2026-10-27")
        self.assertEqual(M.read_pointer(directory),digest)
        self.assertFalse((directory/".operation.lock").exists())

    def test_exclusive_lock_prevents_concurrent_mutations(self):
        record=sample()
        directory=M.private_dir("SH600000","5min","2026-10-27")
        with M.exclusive_lock(directory):
            with self.assertRaisesRegex(ValueError,"lock exists"):
                M.stage(record,"a"*64)
        self.assertFalse((directory/".operation.lock").exists())
        with self.assertRaisesRegex(ValueError,"No private overlay"):
            M.rollback("SH600000","5min","2026-10-27")

    def test_cli_validate_stage_rollback_are_safe_and_explicit(self):
        source=self.input_file()
        def invoke(args):
            with redirect_stdout(StringIO()):
                M.main(args)
        validate=[
            "--action","validate","--input",str(source),
            "--out","reports/tdx-validate.json"]
        invoke(validate)
        doc=json.loads((self.reports/"tdx-validate.json").read_text())
        self.assertFalse(doc["raw_ohlcva_in_report"])
        self.assertEqual(doc["outcome"],"validated_only")
        self.assertFalse(self.work.exists())
        stage=[
            "--action","stage","--input",str(source),"--allow-private-copy",
            "--out","reports/tdx-stage.json"]
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(["--action","stage","--input",str(source),
                    "--out","reports/no-copy.json"])
        invoke(stage)
        output=json.loads((self.reports/"tdx-stage.json").read_text())
        self.assertTrue(output["private_data_only_under_gitignored_work"])
        self.assertNotIn('"open"',json.dumps(output))
        self.assertNotIn('"amount"',json.dumps(output))
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(stage)
        invoke(["--action","rollback","--symbol","SH600000",
                "--period","5min","--date","2026-10-27",
                "--out","reports/tdx-rollback.json"])
        self.assertFalse((M.private_dir("SH600000","5min","2026-10-27")/
                         "active.json").exists())
        with self.assertRaisesRegex(ValueError,"NEW JSON"):
            M.out_path(self.home/"outside.json")

    def test_invalid_state_does_not_touch_market_source(self):
        source=self.input_file()
        snapshot=source.read_bytes()
        bad=sample()
        bad["bars"][0]["high"]=1
        with self.assertRaises(ValueError):
            M.stage(bad,"a"*64)
        self.assertEqual(source.read_bytes(),snapshot)
        self.assertFalse(self.work.exists())


if __name__=="__main__":
    unittest.main()
