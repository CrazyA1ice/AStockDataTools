"""Synthetic PyArrow tests for explicit SHA-only private joined logical day read."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


Q=load("private_joined_sha_reader_test",
       HERE.parent/"tools"/"query-private-joined-day-by-version-sha-readonly.py")
F=load("private_joined_sha_fixture",
       HERE/"test_register_private_joined_day_logical_version.py")


@contextmanager
def ready():
    with F.ready() as (base,parent,folder,delta,versions,active,lock,batch):
        with patch.object(Q,"REG",F.R), \
             patch.object(Q,"JOIN",F.R.J), \
             patch.object(Q,"READER",F.R.READER):
            registered=F.R.prepare(parent,delta)
            sha=registered["version_sha256"]
            output=base.reports/"verified-logical-version-query.json"
            yield base,sha,parent,folder,delta,versions,active,lock,output


def query(sha,out,symbols=("SH600000","SZ000001","SH600519"),
          first="2026-09-30",last="2026-10-08"):
    return Q.query_version(sha,list(symbols),first,last,out)


class ExplicitPrivateJoinedVersionReadTests(unittest.TestCase):
    def test_complete_immutable_version_query_returns_full_private_rows(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            original={p:Q.READER.sha256_file(p) for p in (
                b.pqfile,b.manifest_file,b.safe_file,
                folder/"day.parquet",folder/"manifest.json",delta,
                versions/(sha+".json"))}
            result=query(sha,out)
            s=result["safe_summary"]
            self.assertEqual(s["full_joined_rows_verified"],5)
            self.assertEqual(s["full_joined_stocks_verified"],3)
            self.assertEqual(s["selected_rows"],5)
            self.assertEqual(s["selected_purchased_rows"],2)
            self.assertEqual(s["selected_h5_gap_candidate_rows"],3)
            self.assertEqual(s["logical_version_sha256"],sha)
            self.assertTrue(s[
                "logical_version_parent_delta_parquet_manifest_and_safe_sha_verified"])
            self.assertFalse(s["private_active_pointers_read_or_modified"])
            self.assertFalse(s["original_market_sources_opened_or_modified"])
            self.assertFalse(s["raw_ohlcva_or_stock_symbols_in_safe"])
            self.assertTrue(s["no_live_market_source_freshness_recheck"])
            self.assertEqual(len(result["bars_by_symbol"]["SH600519"]),2)
            self.assertEqual({p:Q.READER.sha256_file(p) for p in original},original)
            self.assertFalse(active.exists())
            for secret in ("SH600519","SH600000","SZ000001","150000.25",
                           "HikyuuData","AllCycleAStockData"):
                self.assertNotIn(secret,out.read_text())
            self.assertEqual(len(list(b.reports.glob("*.json"))),3)

    def test_query_new_stock_subset_without_other_rows(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            result=query(sha,out,("SH600519",),"2026-10-08","2026-10-08")
            s=result["safe_summary"]
            self.assertEqual(s["selected_rows"],1)
            self.assertEqual(s["selected_purchased_rows"],0)
            self.assertEqual(s["selected_h5_gap_candidate_rows"],1)
            self.assertEqual(s["full_joined_rows_verified"],5)
            self.assertEqual(list(result["bars_by_symbol"]),["SH600519"])

    def test_unknown_or_invalid_sha_refused_without_output(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            for bad in ("notsha","f"*64,"",None):
                with self.subTest(sha=bad):
                    with self.assertRaises(ValueError):
                        query(bad,out)
                    self.assertFalse(out.exists())

    def test_malformed_and_duplicate_requested_symbols_refused(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            for symbols in ([],["sh600519"],["SH600519","SH600519"],
                            ["BAD"],["BJ899999"],["SH600000 "],
                            ["SH600519"]*11):
                with self.subTest(symbols=symbols):
                    with self.assertRaises(ValueError):
                        query(sha,out,symbols)
                    self.assertFalse(out.exists())

    def test_requested_dates_must_be_within_registered_window(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            for first,last in (("2026-09-29","2026-10-08"),
                               ("2026-09-30","2026-10-09"),
                               ("2026-10-09","2026-10-08"),
                               ("2026-10-8","2026-10-08")):
                with self.subTest(first=first,last=last):
                    with self.assertRaises(ValueError):
                        query(sha,out,first=first,last=last)
                    self.assertFalse(out.exists())

    def test_registered_version_json_tampering_refused(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            p=versions/(sha+".json")
            v=json.loads(p.read_text())
            v["joined_rows"]+=1
            p.write_text(json.dumps(v),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"content SHA differs"):
                query(sha,out)
            self.assertFalse(out.exists())

    def test_original_base_parquet_tampering_refused_before_query(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            with b.pqfile.open("ab") as stream:
                stream.write(b"changed-original-base")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                query(sha,out)
            self.assertFalse(out.exists())

    def test_delta_parquet_tampering_refused_before_query(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            with (folder/"day.parquet").open("ab") as stream:
                stream.write(b"changed-delta")
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                query(sha,out)
            self.assertFalse(out.exists())

    def test_source_safe_changed_after_registration_blocks_read(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            delta.write_text(delta.read_text()+"\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"no longer matches"):
                query(sha,out)
            self.assertFalse(out.exists())

    def test_explicit_version_never_consults_any_private_active_pointer(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            with patch.object(Q.REG,"read_pointer",
                              side_effect=AssertionError("must not read pointer")), \
                 patch.object(Q.JOIN.ADD.VERSION,"read_pointer",
                              side_effect=AssertionError("must not read parent pointer")):
                result=query(sha,out)
            self.assertEqual(result["safe_summary"]["selected_rows"],5)
            self.assertFalse(active.exists())

    def test_version_lock_blocks_read_before_private_decode(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            lock.write_text("locked",encoding="utf-8")
            with patch.object(Q.JOIN,"read_joined",
                              side_effect=AssertionError("must not read")):
                with self.assertRaisesRegex(ValueError,"update in progress"):
                    query(sha,out)
            self.assertFalse(out.exists())

    def test_version_changes_during_join_aborts_without_safe(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            original=Q.JOIN.read_joined
            def replace_version(*args,**kwargs):
                result=original(*args,**kwargs)
                p=versions/(sha+".json")
                p.write_text(p.read_text()+"\n",encoding="utf-8")
                return result
            with patch.object(Q.JOIN,"read_joined",side_effect=replace_version):
                with self.assertRaisesRegex(ValueError,"version SHA changed"):
                    query(sha,out)
            self.assertFalse(out.exists())

    def test_unsafe_joined_summary_not_published_even_when_returned(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            original=Q.JOIN.read_joined
            def forged(*args,**kwargs):
                result=original(*args,**kwargs)
                result["safe_summary"]["selected_purchased_rows"]=99
                return result
            with patch.object(Q.JOIN,"read_joined",side_effect=forged):
                with self.assertRaisesRegex(ValueError,"does not match registered"):
                    query(sha,out)
            self.assertFalse(out.exists())

    def test_output_outside_module_reports_rejected(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            with self.assertRaises(ValueError):
                query(sha,b.module/"unsafe.json")
            self.assertFalse(out.exists())

    def test_existing_safe_is_never_overwritten(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            out.write_text("protected",encoding="utf-8")
            with self.assertRaises(ValueError):
                query(sha,out)
            self.assertEqual(out.read_text(),"protected")

    def test_in_memory_mode_does_not_publish_intermediate_join_safe(self):
        with ready() as (b,sha,parent,folder,delta,versions,active,lock,out):
            original=Q.JOIN.read_joined
            def verify_suppress(*args,**kwargs):
                self.assertIsNone(args[5])
                self.assertIs(kwargs.get("emit_safe"),False)
                return original(*args,**kwargs)
            with patch.object(Q.JOIN,"read_joined",side_effect=verify_suppress):
                result=query(sha,out)
            self.assertEqual(result["safe_summary"]["selected_rows"],5)
            self.assertEqual(
                list(p.name for p in b.reports.glob("*verified-logical*")),
                [out.name])


if __name__=="__main__":
    unittest.main(verbosity=2)
