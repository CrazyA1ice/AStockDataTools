"""Offline real binary ZIP / Arrow Parquet test vectors; no network or stock data."""
from __future__ import annotations

from datetime import date,timedelta,timezone
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import live_sync as S
import tdx_source as T

def official_zip(day,*,missing=(),duplicate=False,corrupt=False,
                 suspended_market=None,bad_active_market=None,
                 missing_amount_market=None):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for m,equity in (("sh","600000"),("sz","000001"),("bj","920021")):
            cod=bytearray()
            md1=bytearray()
            symbols=[equity,"510050" if m=="sh" else
                     ("159915" if m=="sz" else "880000")]
            if duplicate:
                symbols[1]=symbols[0]
            for i,code in enumerate(symbols):
                row=bytearray(150)
                row[:6]=code.encode("ascii")
                row[32:34]=struct.pack("<H",i)
                row[40:45]=b"TestA"
                cod.extend(row)
                blk=bytearray(512)
                struct.pack_into("<d",blk,4,9.99)
                o,h,l,c=(10.,11.,9.,10.5)
                vol=10000+i
                amount=float("nan") if corrupt else 105000.
                if i==0 and m==suspended_market:
                    o,h,l=0.,0.,0.
                    vol=0
                    amount=0.
                if i==0 and m==bad_active_market:
                    h=9.5
                if i==0 and m==missing_amount_market:
                    amount=0.
                struct.pack_into("<4d",blk,12,o,h,l,c)
                struct.pack_into("<Q",blk,56,vol)
                struct.pack_into("<d",blk,72,amount)
                md1.extend(blk)
            key=day.strftime("%Y%m%d")[2:]
            for ext,payload in (("cod",cod),("md1",md1)):
                path=m+key+"."+ext
                if path not in missing:
                    z.writestr(path,payload)
    return raw.getvalue()

def good_units():
    return {"tdx_shares_to_local_volume":100,
            "tdx_yuan_to_local_amount":1,
            "volume_fit":1,"amount_fit":1}

class OfficialSourceParsing(unittest.TestCase):
    def setUp(self):
        self.day=date(2026,11,11)

    def test_true_binary_tdx_market_pairs_and_stock_only(self):
        bars,meta=T.parse_daily_zip(official_zip(self.day),self.day,
                                    minimums={"sh":1,"sz":1,"bj":1})
        self.assertEqual(len(bars),3)
        self.assertEqual(sorted(x["symbol"] for x in bars),
                         ["BJ920021","SH600000","SZ000001"])
        self.assertEqual(bars[0]["volume_shares"],10000)
        self.assertEqual(bars[0]["amount_yuan"],105000.0)
        self.assertEqual(meta["all_priced_by_market"],{"sh":2,"sz":2,"bj":2})

    def test_real_zero_turnover_suspended_a_share_not_fake_trading_bar(self):
        # Full source still contains genuine close carried forward while
        # O/H/L are zero. This is NOT a traded A-share OHLCVA record and
        # should be counted, excluded and explainable, not abort the day.
        bars,meta=T.parse_daily_zip(
            official_zip(self.day,suspended_market="sh"),self.day,
            minimums={"sh":1,"sz":1,"bj":1})
        self.assertEqual(len(bars),2)
        self.assertNotIn("SH600000",[bar["symbol"] for bar in bars])
        self.assertEqual(meta["zero_turnover_nontrading_a_shares_by_market"]["sh"],1)
        self.assertEqual(meta["zero_turnover_nontrading_a_shares_by_market"]["sz"],0)

    def test_genuine_traded_a_share_bad_ohlc_fails_with_exact_symbol_and_date(self):
        with self.assertRaisesRegex(
            ValueError,r"TDX_INVALID_TRADED_A_SHARE_OHLCVA date=2026-11-11 symbol=SZ000001"):
            T.parse_daily_zip(official_zip(self.day,bad_active_market="sz"),
                              self.day,minimums={"sh":1,"sz":1,"bj":1})

    def test_genuine_traded_a_share_missing_amount_not_silently_zero_filled(self):
        with self.assertRaisesRegex(
            ValueError,r"TDX_INVALID_TRADED_A_SHARE_OHLCVA date=2026-11-11 symbol=BJ920021"):
            T.parse_daily_zip(official_zip(self.day,missing_amount_market="bj"),
                              self.day,minimums={"sh":1,"sz":1,"bj":1})

    def test_invalid_traded_quote_is_quarantined_with_source_sha_not_published(self):
        day=self.day
        source=official_zip(day,bad_active_market="sh")
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"downloads"
            cache.mkdir()
            # Exercise the real public ZIP quarantine but no network:
            # an already downloaded byte sequence that fails strict OHLCVA.
            with self.assertRaisesRegex(ValueError,"TDX_INVALID_TRADED_A_SHARE_OHLCVA"):
                T.parse_daily_zip(source,day,minimums={"sh":1,"sz":1,"bj":1})
            quarantine=T.preserve_rejected_zip(source,day,cache,"bad OHLC")
            self.assertEqual(quarantine.read_bytes(),source)
            self.assertEqual(quarantine.parent.name,"rejected_official_tdx")
            self.assertEqual(quarantine,T.preserve_rejected_zip(
                source,day,cache,"repeat, must not overwrite"))
            self.assertFalse((cache/(day.strftime("%Y%m%d")+".zip")).exists())

    def test_live_download_bad_traded_quote_has_diagnostic_and_private_rejected_zip(self):
        day=self.day
        raw=official_zip(day,bad_active_market="sz")
        with tempfile.TemporaryDirectory() as td:
            class FakeHttp(io.BytesIO):
                status=200
            with patch.object(T.urllib.request,"urlopen",
                              return_value=FakeHttp(raw)):
                with self.assertRaisesRegex(
                    ValueError,r"TDX_INVALID_TRADED_A_SHARE_OHLCVA"
                               r" date=2026-11-11 symbol=SZ000001.*private_raw_zip="):
                    T.download_daily(day,Path(td)/"downloads",retries=1,pause=0)
            target=Path(td)/"rejected_official_tdx"/(
                "20261111-"+T.sha256(raw)[:16]+".zip")
            self.assertTrue(target.is_file())
            self.assertEqual(T.sha256(target.read_bytes()),T.sha256(raw))
            self.assertFalse((Path(td)/"downloads"/"20261111.zip").exists())

    def test_bad_bj_pair_fails_closed_not_partial(self):
        key=self.day.strftime("%Y%m%d")[2:]
        with self.assertRaisesRegex(ValueError,"Missing original"):
            T.parse_daily_zip(
                official_zip(self.day,missing={"bj"+key+".cod"}),
                self.day,minimums={"sh":1,"sz":1,"bj":1})

    def test_duplicate_code_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"Duplicated"):
            T.parse_daily_zip(official_zip(self.day,duplicate=True),
                              self.day,minimums={"sh":1,"sz":1,"bj":1})

    def test_nan_market_value_fails_closed(self):
        with self.assertRaisesRegex(ValueError,r"TDX_SOURCE_NONFINITE date=2026-11-11 symbol=SH600000"):
            T.parse_daily_zip(official_zip(self.day,corrupt=True),
                              self.day,minimums={"sh":1,"sz":1,"bj":1})

    def test_market_minimums_required_on_live_production(self):
        with self.assertRaisesRegex(ValueError,"Incomplete official"):
            T.parse_daily_zip(official_zip(self.day),self.day)

    def test_stock_type_exclusions_for_bj_and_non_equity(self):
        self.assertFalse(T.is_equity("sh","510050",2026))
        self.assertFalse(T.is_equity("sh","000001",2026))
        self.assertFalse(T.is_equity("bj","920021",2021))
        self.assertTrue(T.is_equity("bj","920021",2026))
        self.assertTrue(T.is_equity("sh","688981",2026))

class UnitMatchingAndPhysicalDay(unittest.TestCase):
    def test_auto_unit_scale_from_2026_original_day(self):
        old={}
        current=[]
        for i in range(200):
            sym="SH"+str(600000+i)
            base=50+i*.01
            old[sym]={"close":base,"volume":float((10000+i)*100),
                      "amount":float((100000+i)*1),
                      "ts":S.source_day_ts(date(2026,9,30))+34200000}
            current.append({"symbol":sym,"close":base,"date":"2026-09-30",
                            "volume_shares":10000+i,"amount_yuan":100000+i})
        result=S.compare_units(old,current)
        self.assertEqual(result["tdx_shares_to_local_volume"],100)
        self.assertEqual(result["tdx_yuan_to_local_amount"],1)
        self.assertEqual(result["matched_prices"],200)
        self.assertEqual(result["local_day_ts_offset_ms"],34200000)

    def test_changed_adjusted_close_rejects_calibration(self):
        old={}
        current=[]
        for i in range(200):
            sym="SH"+str(600000+i)
            old[sym]={"close":5.0,"volume":1000000.,"amount":100000.}
            current.append({"symbol":sym,"close":20.0,
                            "volume_shares":10000,"amount_yuan":100000})
        with self.assertRaisesRegex(ValueError,"Close prices disagree"):
            S.compare_units(old,current)

    def test_ambiguous_zero_amount_cannot_calibrate(self):
        with self.assertRaisesRegex(ValueError,"Insufficient"):
            S.infer_factor([(0,0)]*200,[1,10,100],absolute=1000)

    def test_arrow_day_schema_and_cn_midnight_ms(self):
        import pyarrow as pa
        expected=date(2026,11,11)
        table=S.prepare_day([
            {"symbol":"SH600000","date":str(expected),
             "open":10.,"high":11.,"low":9.,"close":10.5,
             "volume_shares":1000,"amount_yuan":2000.}
        ],expected,good_units())
        self.assertEqual(table.schema,S.parquet_schema())
        self.assertEqual(table.num_rows,1)
        self.assertEqual(table["volume"].to_pylist(),[100000.0])
        self.assertEqual(table["amount"].to_pylist(),[2000.0])
        self.assertEqual(table["ts"].to_pylist(),[S.source_day_ts(expected)])

    def test_future_and_legacy_collision_refused(self):
        with self.assertRaisesRegex(ValueError,"after 2026-10-13"):
            S.safe_window(date(2026,10,13),date(2026,10,14))
        with self.assertRaises(ValueError):
            S.safe_window(date(2026,10,14),date(2027,1,1))

class AtomicLocalDayAndView(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root=Path(d.name)
        self.work=self.root/"work"
        self.work.mkdir()
        for field,value in (("WORK",self.work),("STATE",self.work/"state.json")):
            p=patch.object(S,field,value)
            p.start()
            self.addCleanup(p.stop)
        self.sourceDay=date(2026,11,11)
        self.sourcerows=[
            {"symbol":"SH600000","date":str(self.sourceDay),
             "open":10.,"high":11.,"low":9.,"close":10.5,
             "volume_shares":10000,"amount_yuan":150000.}]
        self.sourceMeta={"raw_zip_sha256":"a"*64,
                         "origin_url":"https://www.tdx.com.cn/test.zip",
                         "a_share_by_market":{"sh":1,"sz":0,"bj":0}}

    def test_windows_atomic_parquet_rename_closes_pyarrow_file_reader_first(self):
        # Reproduces WinError 32 without requiring actual Windows locks:
        # inspect the true ParquetFile close state at the exact os.replace.
        import pyarrow.parquet as pq
        original_reader=pq.ParquetFile
        original_rename=Path.replace
        readers=[]
        class SpyReader:
            def __init__(self,*args,**kwargs):
                self.inner=original_reader(*args,**kwargs)
                self.closed=False
                readers.append(self)
            def __getattr__(self,name):
                return getattr(self.inner,name)
            def close(self):
                self.inner.close()
                self.closed=True
        seen=[]
        def guarded_rename(file,target):
            if str(file).endswith(".parquet.part"):
                self.assertTrue(readers)
                self.assertTrue(all(reader.closed for reader in readers),
                                "Parquet reader must close before Windows rename")
                seen.append(str(file))
            return original_rename(file,target)
        state=S.initial_state()
        state["calibration"]=good_units()
        table=S.prepare_day(self.sourcerows,self.sourceDay,state["calibration"])
        with patch.object(pq,"ParquetFile",side_effect=SpyReader):
            with patch.object(Path,"replace",guarded_rename):
                proof=S.put_day(self.sourceDay,table,self.sourceMeta,state)
        self.assertEqual(len(seen),1)
        self.assertEqual(len(readers),1)
        self.assertTrue(readers[0].closed)
        self.assertTrue((self.work/proof["file"]).is_file())

    def test_windows_footer_rejection_releases_temp_parquet_reader(self):
        import pyarrow.parquet as pq
        original_reader=pq.ParquetFile
        readers=[]
        class BrokenFooter:
            def __init__(self,*args,**kwargs):
                self.inner=original_reader(*args,**kwargs)
                readers.append(self)
                self.closed=False
            @property
            def schema_arrow(self):
                return None
            @property
            def metadata(self):
                return self.inner.metadata
            def close(self):
                self.inner.close()
                self.closed=True
        state=S.initial_state()
        state["calibration"]=good_units()
        table=S.prepare_day(self.sourcerows,self.sourceDay,state["calibration"])
        with patch.object(pq,"ParquetFile",side_effect=BrokenFooter):
            with self.assertRaisesRegex(ValueError,"footer schema"):
                S.put_day(self.sourceDay,table,self.sourceMeta,state)
        self.assertEqual(len(readers),1)
        self.assertTrue(readers[0].closed)
        self.assertFalse((self.work/"incremental/day/year=2026/2026-11-11.parquet").exists())

    def test_atomic_day_parquet_receipt_and_manifest(self):
        base=S.initial_state()
        base["calibration"]=good_units()
        table=S.prepare_day(self.sourcerows,self.sourceDay,base["calibration"])
        proof=S.put_day(self.sourceDay,table,self.sourceMeta,base)
        self.assertEqual(proof["rows"],1)
        self.assertEqual(S.read_state()["days"][self.sourceDay.isoformat()]["rows"],1)
        from pyarrow.parquet import ParquetFile
        new=self.work/proof["file"]
        reader=ParquetFile(new)
        try:
            self.assertEqual(reader.metadata.num_rows,1)
        finally:
            reader.close()
        self.assertEqual(new.stat().st_size>0,True)
        # Simulate an interrupted publish: the physical file and receipt
        # are durable, but state.json was lost before the final manifest
        # update. The identical source must recover WITHOUT overwriting.
        base["days"].clear()
        S.save_state(base)
        digest=S.file_sha(new)
        restored=S.put_day(self.sourceDay,table,self.sourceMeta,base)
        self.assertEqual(restored,proof)
        self.assertEqual(S.file_sha(new),digest)
        self.assertEqual(len(S.read_state()["days"]),1)

    def test_receipt_mutation_refused_even_when_parquet_bytes_unchanged(self):
        doc=S.initial_state()
        doc["calibration"]=good_units()
        table=S.prepare_day(self.sourcerows,self.sourceDay,doc["calibration"])
        proof=S.put_day(self.sourceDay,table,self.sourceMeta,doc)
        receipt=(self.work/proof["file"]).with_suffix(".json")
        saved=json.loads(receipt.read_text(encoding="utf-8"))
        saved["raw_zip_sha256"]="f"*64
        receipt.write_text(json.dumps(saved),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"receipt checksum changed"):
            S.read_state()

    def test_missing_upstream_404_is_retryable_not_committed(self):
        from tdx_source import MissingPackage
        day=date(2026,10,14)
        with patch.object(S,"baseline",return_value={}):
            with patch.object(S,"get_calibration",return_value=good_units()):
                with patch.object(S,"download_daily",
                                  side_effect=MissingPackage("404")):
                    result=S.sync(self.root,day,day,logger=lambda _:None)
        self.assertEqual(result["new_days"],0)
        self.assertEqual(result["source_not_yet_available_404"],1)
        state=S.read_state()
        self.assertEqual(state["days"],{})
        self.assertIn(day.isoformat(),state["unavailable_404_last_attempt"])

    def test_real_physical_day_sync_then_idempotent_skip_without_network(self):
        day=date(2026,10,14)
        sample=[dict(self.sourcerows[0],date=str(day))]
        with patch.object(S,"baseline",return_value={}):
            with patch.object(S,"get_calibration",return_value=good_units()):
                with patch.object(S,"parse_daily_zip",
                                  return_value=(sample,self.sourceMeta)):
                    with patch.object(S,"download_daily",
                                      return_value=(b"official-zip","downloaded")) as downloader:
                        result=S.sync(self.root,day,day,logger=lambda _:None)
                    self.assertEqual(result["new_days"],1)
                    self.assertEqual(result["new_daily_rows"],1)
                    with patch.object(S,"download_daily",
                                      side_effect=AssertionError("No redownload")):
                        again=S.sync(self.root,day,day,logger=lambda _:None)
                        self.assertEqual(again["already_verified"],1)
        self.assertEqual(downloader.call_count,1)
        self.assertEqual(len(S.read_state()["days"]),1)

    def test_tampered_incremental_parquet_never_accepted(self):
        base=S.initial_state()
        base["calibration"]=good_units()
        table=S.prepare_day(self.sourcerows,self.sourceDay,base["calibration"])
        proof=S.put_day(self.sourceDay,table,self.sourceMeta,base)
        with (self.work/proof["file"]).open("ab") as f:
            f.write(b"CHANGED")
        with self.assertRaisesRegex(ValueError,"checksum changed"):
            S.read_state()

    def test_rejected_original_cutoff_in_private_state(self):
        doc=S.initial_state()
        doc["days"]["2026-10-13"]={"file":"incremental/day/x.parquet","sha256":"00"}
        S.save_state(doc)
        with self.assertRaisesRegex(ValueError,"colliding"):
            S.read_state()

    def test_downstream_eight_cycle_arrow_day_union_only_day_changes(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from pyarrow import dataset as ds
        # Artificial 1-stock base and 1-stock overlay; keep all other 7
        # exactly as their accepted original Parquet.
        olddir=self.root/"baseline"
        olddir.mkdir()
        oldpath=olddir/"legacy.parquet"
        baseline_day=date(2026,10,13)
        oldvalues={field:[] for field in S.FIELDS}
        oldvalues["ts"]=[S.source_day_ts(baseline_day)]
        oldvalues["symbol"]=["SH600000"]
        for k in S.FIELDS[2:]:
            oldvalues[k]=[10.]
        pq.write_table(pa.table(oldvalues,schema=S.parquet_schema()),oldpath)
        payload={"period_physical_files":{
            period:[{"root_kind":"private_module","relative_file":"legacy.parquet",
                     "source_class":"modern_16yr_purchased_first_day"}]
            for period in S.PERIODS}}
        with patch.object(S,"BASE_MODULE",olddir),patch.object(S,"baseline",return_value=payload):
            doc=S.initial_state()
            doc["calibration"]=good_units()
            table=S.prepare_day(self.sourcerows,self.sourceDay,doc["calibration"])
            S.put_day(self.sourceDay,table,self.sourceMeta,doc)
            day=S.open_live_dataset("day",self.root)
            minute=S.open_live_dataset("1min",self.root)
            self.assertEqual(day.count_rows(),2)
            self.assertEqual(minute.count_rows(),1)
            self.assertEqual(day.to_table()["symbol"].to_pylist(),
                             ["SH600000","SH600000"])

if __name__=="__main__":
    unittest.main()
