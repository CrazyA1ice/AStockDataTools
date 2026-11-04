#!/usr/bin/env python3
"""Safely reuse a pre-existing bounded purchased minute-key index or build ONCE.

This is an analysis-only key-index organizer, not a Parquet/H5 market writer.
Identical source-window index files are never silently duplicated; multiple
existing candidates or stale source metadata fail closed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


I=load("minute_reuse_existing_purchased_index",
       "build-minute-purchased-key-index.py")


def ensure(root,first,last,*,run_id=None):
    days=I.make_days(first,last)
    root=Path(root)
    I.N.validate(root,days[0],"000000000000")
    if I.STORE.is_symlink():
        raise ValueError("Private index store cannot be a symlink")
    pattern="purchased-minute-keys-"+days[0].isoformat()+"-"+days[-1].isoformat()+"-*.sqlite"
    prior=sorted(I.STORE.glob(pattern)) if I.STORE.is_dir() else []
    for file in prior:
        if file.is_symlink() or not file.is_file():
            raise ValueError("Unsafe pre-existing index path")
    if len(prior)>1:
        raise ValueError("Multiple purchased source-key indexes for one window: choose manually")
    if prior:
        path=prior[0]
        # A valid index must match unchanged vendor/H5 source metadata,
        # exact window, both periods and original root. Even when source
        # has changed, do not auto-create a replacement under a new ID.
        for period in I.N.PERIODS:
            I.query_index(path,root,period,days[0])
            I.query_index(path,root,period,days[-1])
        return {
            "status":"reused_existing_source_key_index_no_new_file",
            "index_path":str(path),
            "from_day":days[0].isoformat(),
            "through_day":days[-1].isoformat(),
            "already_indexed":True,
            "new_private_index_created":False,
            "purchased_ohlcva_rows_copied":0,
            "market_parquet_or_h5_files_written":False,
            "source_content_sha_certified":False,
        }
    rid=run_id or secrets.token_hex(6)
    result=I.build(root,days[0],days[-1],rid)
    return {
        "status":"new_private_source_key_index_built_once",
        "index_path":result["index_path"],
        "from_day":days[0].isoformat(),
        "through_day":days[-1].isoformat(),
        "already_indexed":False,
        "new_private_index_created":True,
        "purchased_index_rows_by_period":{
            period:result["periods"][period]["a_share_unique_keys"]
            for period in I.N.PERIODS},
        "purchased_ohlcva_rows_copied":0,
        "market_parquet_or_h5_files_written":False,
        "source_content_sha_certified":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    args=p.parse_args(argv)
    print(json.dumps(ensure(args.root,args.from_day,args.through_day),
                     indent=2,sort_keys=True,ensure_ascii=False))


if __name__=="__main__":
    main()
