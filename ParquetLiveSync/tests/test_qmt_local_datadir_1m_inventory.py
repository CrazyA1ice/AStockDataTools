"""Offline QMT native folder metadata inventory safety tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/"qmt_local_datadir_1m_inventory.py"
spec=importlib.util.spec_from_file_location("qmt_local_datadir_1m_inventory",SCRIPT)
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


class TestQmtDatadirInventory(unittest.TestCase):
    def test_only_minutes_and_daily_no_tick_recursive_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"SH"/"0"/"688001").mkdir(parents=True)
            (root/"SH"/"0"/"688001"/"20261113.DAT").write_bytes(b"tick")
            (root/"SH"/"60").mkdir()
            (root/"SH"/"60"/"688001.DAT").write_bytes(b"1min-original")
            (root/"SH"/"300").mkdir()
            (root/"SH"/"300"/"688001.SH.DAT").write_bytes(b"5min")
            (root/"SZ"/"60").mkdir(parents=True)
            (root/"SZ"/"60"/"000001.DAT").write_bytes(b"sz")
            logs=[]
            report=T.run(root,logger=logs.append)
            self.assertEqual(report["one_min_file_count"],2)
            self.assertEqual(report["one_min_selected_anchor_files"],2)
            self.assertTrue(report["tick_directory_0_never_read"])
            self.assertTrue(report["dat_file_contents_not_parsed"])
            self.assertTrue(report["historical_241_bar_coverage_not_yet_verified"])
            self.assertTrue(report["no_network"])
            self.assertTrue(report["no_files_written"])
            data=[json.loads(x.split("=",1)[1]) for x in logs
                  if x.startswith("QMT_LOCAL_DATADIR_PERIOD")]
            self.assertEqual(len(data),9)
            sh_1m=next(x for x in data if x["market"]=="SH"
                       and x["period"]=="1m")
            self.assertEqual(sh_1m["selected_anchor_files"][0]["stock"],
                             "688001.SH")
            self.assertEqual(sh_1m["selected_anchor_files"][0]["hash_status"],
                             "SHA256_VERIFIED_READONLY")
            self.assertFalse(any("20261113.DAT" in x for x in logs))
            self.assertEqual((root/"SH"/"0"/"688001"/"20261113.DAT").read_bytes(),b"tick")
            self.assertEqual((root/"SH"/"60"/"688001.DAT").read_bytes(),b"1min-original")

    def test_symlink_root_and_parent_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/"a";a.mkdir()
            target=Path(temp)/"b"
            try:
                target.symlink_to(a,target_is_directory=True)
            except (OSError,NotImplementedError):
                return
            with self.assertRaisesRegex(ValueError,"symlink"):
                T.run(target,logger=lambda _:None)
            c=a/"SH"
            c.mkdir()
            sub=c/"60"
            sub.symlink_to(a,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,"Redirected"):
                T.one_directory(a,"SH","60")

    def test_large_anchor_not_hashed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/"SH"/"60";path.mkdir(parents=True)
            f=path/"688001.dat";f.write_bytes(b"large")
            with patch.object(T,"MAX_HASH_BYTES",2):
                report=T.one_directory(root,"SH","60")
            self.assertEqual(report["selected_anchor_files"][0]["hash_status"],
                             "SIZE_GT_64_MIB_NO_HASH")
            self.assertIsNone(report["selected_anchor_files"][0]["sha256"])

    def test_bad_root_and_no_reading_0(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):
                T.run(root/"none",logger=lambda _:None)
            with self.assertRaises(ValueError):
                T.safe_dir(root,"SH","0")


if __name__=="__main__":
    unittest.main()
