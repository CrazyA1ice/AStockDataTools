#!/usr/bin/env python3
"""Read TDX official DAILY packages, based on a-stock-data v3.10.4 §1.3.

Source: https://github.com/simonlin1212/a-stock-data (Apache-2.0).
This implementation retains that project's documented .cod/.md1 layout,
bounds, and fail-closed checks. It never updates any vendor Parquet/H5 file.
The upstream repository provides API recipes, not downloadable Parquet data.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import hashlib
import io
import math
import re
import struct
import time
import urllib.error
import urllib.request
import zipfile

TDX_URL="https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
MIN_ROWS={"sh":10000,"sz":3000,"bj":50}
FIRST_BJ=date(2022,5,6)
ZIP_MAX=50_000_000
MEMBER_MAX=35_000_000

class MissingPackage(Exception):
    """404: not published, non-trading day or outside source retention; retryable."""

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def is_equity(market,code,year):
    """Conservative candidate filter; no guessed historical-code remappings."""
    if not re.fullmatch(r"\d{6}",code):
        return False
    if market=="sh":
        return code.startswith(("600","601","603","605")) or (
            year>=2019 and code.startswith(("688","689")))
    if market=="sz":
        return code.startswith(("000","001","002","003","300","301"))
    if market=="bj":
        return year>=2022 and code.startswith(("920","430","830","870"))
    return False

def parse_daily_zip(raw,day,minimums=None):
    if not isinstance(day,date) or not isinstance(raw,bytes) or not 10<len(raw)<=ZIP_MAX:
        raise ValueError("Invalid or oversized official daily ZIP")
    if raw[:2]!=b"PK":
        raise ValueError("Official daily package did not start with ZIP header")
    limits=MIN_ROWS if minimums is None else minimums
    key=day.strftime("%Y%m%d")
    equities=[]
    all_counts={}
    valid_counts={}
    skipped_nontrading={}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members={entry.filename:entry for entry in archive.infolist()}
        if len(members)!=len(archive.infolist()):
            raise ValueError("Duplicate official ZIP members")
        for market in ("sh","sz","bj"):
            code_name=f"{market}{key[2:]}.cod"
            quote_name=f"{market}{key[2:]}.md1"
            if (market=="bj" and day<FIRST_BJ
                    and code_name not in members and quote_name not in members):
                continue
            if code_name not in members or quote_name not in members:
                raise ValueError("Missing original cod/md1 market pair: "+market)
            if (members[code_name].file_size>MEMBER_MAX
                    or members[quote_name].file_size>MEMBER_MAX):
                raise ValueError("Oversized official daily package member")
            cod=archive.read(code_name)
            md1=archive.read(quote_name)
            if len(cod)%150 or len(md1)%512 or len(cod)//150!=len(md1)//512:
                raise ValueError("Original official cod/md1 block alignment differs")
            total=0
            kept=0
            zero_trading=0
            equity_candidates=0
            symbols=set()
            indexes=set()
            for offset in range(0,len(cod),150):
                item=cod[offset:offset+150]
                try:
                    code=item[:6].rstrip(b"\x00 ").decode("ascii")
                except UnicodeDecodeError as exc:
                    raise ValueError("Invalid ASCII stock code") from exc
                seq=struct.unpack_from("<H",item,32)[0]
                if (re.fullmatch(r"\d{6}",code) is None
                        or code in symbols or seq in indexes):
                    raise ValueError("Duplicated or invalid official stock code/index")
                symbols.add(code)
                indexes.add(seq)
                bar=md1[seq*512:(seq+1)*512]
                if len(bar)!=512:
                    raise ValueError("Market quote index exceeds official block")
                old_close=struct.unpack_from("<d",bar,4)[0]
                o,h,l,c=struct.unpack_from("<4d",bar,12)
                amount=struct.unpack_from("<d",bar,72)[0]
                symbol=market.upper()+code
                if not all(math.isfinite(n) for n in (old_close,o,h,l,c,amount)):
                    raise ValueError(
                        f"TDX_SOURCE_NONFINITE date={day} symbol={symbol} seq={seq}"
                        f" prev_close={old_close!r} open={o!r} high={h!r}"
                        f" low={l!r} close={c!r} amount={amount!r}")
                volume=struct.unpack_from("<Q",bar,56)[0]
                if c<=0:
                    # No price is common for indexes/baskets in TDX
                    # packages. It must not be mistaken for a traded A
                    # share with real turnover.
                    if is_equity(market,code,day.year) and (volume>0 or amount>0):
                        raise ValueError(
                            f"TDX_SOURCE_NONPOSITIVE_CLOSE_WITH_TRADE date={day}"
                            f" symbol={symbol} seq={seq} close={c!r}"
                            f" volume_shares={volume} amount_yuan={amount!r}")
                    continue
                total+=1
                if not is_equity(market,code,day.year):
                    continue
                equity_candidates+=1
                name_bytes=item[40:72].split(b"\x00")[0]
                try:
                    official_name=name_bytes.decode("gbk").strip()
                except UnicodeDecodeError as exc:
                    raise ValueError("Invalid GBK source market security name") from exc
                if not official_name:
                    raise ValueError("Missing named source security with a valid closing price")
                if volume==0 and amount==0:
                    # TDX often publishes a previous close for suspended/
                    # non-trading A-shares, but the O/H/L values may be
                    # zero or otherwise not a genuine traded bar. Keep
                    # these codes in source metadata; do NOT synthesize a
                    # zero-volume OHLCVA market bar or silently distort it.
                    zero_trading+=1
                    continue
                if (volume==0 or amount<=0
                        or min(o,h,l,c)<=0
                        or l>min(o,c)+0.0001
                        or h+0.0001<max(o,c)
                        or l>h+0.0001):
                    raise ValueError(
                        f"TDX_INVALID_TRADED_A_SHARE_OHLCVA date={day}"
                        f" symbol={symbol} seq={seq} name={official_name!r}"
                        f" prev_close={old_close:.8g} open={o:.8g}"
                        f" high={h:.8g} low={l:.8g} close={c:.8g}"
                        f" volume_shares={volume} amount_yuan={amount:.12g}"
                        f" reason={'zero_volume_with_amount' if volume==0 else 'nonpositive_amount_or_invalid_price_grid'}"
                        f" raw_zip_sha256={sha256(raw)[:16]}")
                equities.append({"symbol":symbol,"date":day.isoformat(),
                                 "open":float(o),"high":float(h),
                                 "low":float(l),"close":float(c),
                                 "volume_shares":int(volume),
                                 "amount_yuan":float(amount)})
                kept+=1
            if total<int(limits.get(market,0)):
                raise ValueError("Incomplete official full-market priced rows in "+market)
            # A very large number of zero-trade A-share records is more
            # likely a malformed package than a normal suspension count.
            # Block the whole day instead of undercounting a market.
            if equity_candidates and zero_trading>max(300, int(equity_candidates*.20)):
                raise ValueError(
                    f"TDX_EXCESSIVE_ZERO_TRADE_A_SHARES date={day}"
                    f" market={market} zero_trade={zero_trading}"
                    f" candidate_equities={equity_candidates}")
            all_counts[market]=total
            valid_counts[market]=kept
            skipped_nontrading[market]=zero_trading
    if not equities or len({row["symbol"] for row in equities})!=len(equities):
        raise ValueError("No unique A-share equity in full-market daily package")
    return equities,{"all_priced_by_market":all_counts,
                     "a_share_by_market":valid_counts,
                     "zero_turnover_nontrading_a_shares_by_market":skipped_nontrading,
                     "date":day.isoformat(),"origin_url":TDX_URL.format(ymd=key),
                     "raw_zip_sha256":sha256(raw),
                     "return_values_unadjusted":True,
                     "volume_source_units":"shares",
                     "amount_source_units":"CNY_yuan"}

def download_daily(day,cache_dir,*,retries=3,pause=2.0,logger=None):
    """Download once, keep an immutable raw ZIP for reproducible verification."""
    cache_dir=Path(cache_dir)
    cache_dir.mkdir(parents=True,exist_ok=True)
    target=cache_dir/(day.strftime("%Y%m%d")+".zip")
    if target.is_symlink():
        raise ValueError("Unsafe ZIP cache symlink")
    if target.is_file():
        raw=target.read_bytes()
        if len(raw)>ZIP_MAX:
            raise ValueError("Cached upstream daily ZIP exceeds size limit")
        parse_daily_zip(raw,day)
        return raw,"cached"
    url=TDX_URL.format(ymd=day.strftime("%Y%m%d"))
    for attempt in range(1,retries+1):
        try:
            request=urllib.request.Request(
                url,headers={"User-Agent":"AStockDataTools-ParquetLiveSync/0.1",
                             "Accept":"application/zip"})
            with urllib.request.urlopen(request,timeout=35) as response:
                if response.status!=200:
                    raise ValueError("Unexpected upstream daily HTTP status")
                raw=response.read(ZIP_MAX+1)
            if len(raw)>ZIP_MAX:
                raise ValueError("Official daily ZIP too large")
            parse_daily_zip(raw,day)
            temp=target.with_suffix(".zip.part")
            if temp.exists():
                temp.unlink()
            with temp.open("xb") as stream:
                stream.write(raw)
                stream.flush()
            temp.replace(target)
            return raw,"downloaded"
        except urllib.error.HTTPError as exc:
            if exc.code==404:
                raise MissingPackage(str(day)+" official daily ZIP not published (404)") from exc
            if exc.code not in (408,429,500,502,503,504):
                raise
            error=exc
        except (urllib.error.URLError,TimeoutError,ConnectionError) as exc:
            error=exc
        if logger is not None:
            logger(f"RETRY_SOURCE {day} {attempt}/{retries} {type(error).__name__}")
        if attempt<retries:
            time.sleep(pause*attempt)
    raise RuntimeError(f"Official TDX daily ZIP could not be downloaded: {day}") from error
