#!/usr/bin/env python3
"""Inspect only Parquet FOOTERS and Arrow schema in original adjustment folder.

The Chinese-named 复权因子 folder is NOT an eighth/ninth OHLCVA K-line cycle.
Do not read factor values, guess adjustment semantics, rescale price or
infer historical date coverage from an unassigned file name.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MAX_FILES=32
MAX_ROWGROUPS=100000
MAX_COLS=512
LABEL="\u590d\u6743\u56e0\u5b50"


def inspect(root,*,max_files=MAX_FILES,max_rowgroups=MAX_ROWGROUPS):
    import pyarrow.parquet as pq
    if (type(max_files) is not int or not 1<=max_files<=MAX_FILES
            or type(max_rowgroups) is not int
            or not 1<=max_rowgroups<=MAX_ROWGROUPS):
        raise ValueError("Factor schema-only resource budgets invalid")
    root=Path(root)
    folder=root/"AllCycleAStockData"/LABEL
    if (root.is_symlink() or not root.is_dir() or folder.is_symlink()
            or not folder.is_dir()):
        raise ValueError("Original adjustment-factor folder missing/unsafe")
    sources=sorted(folder.rglob("*.parquet"))
    if not sources or len(sources)>max_files:
        raise ValueError("Require bounded nonempty original adjustment Parquet source list")
    before={}
    for source in sources:
        # Check ACTUAL folder-anchored parents, not Path-relative components.
        # Never traverse a nested source folder symlink.
        parents=[]
        parent=source.parent
        while parent!=folder:
            if not parent.is_relative_to(folder):
                raise ValueError("Factor Parquet source path escaped source folder")
            parents.append(parent)
            parent=parent.parent
        if (source.is_symlink() or not source.is_file()
                or any(p.is_symlink() for p in parents)):
            raise ValueError("Unsafe original factor parquet file or subfolder")
        stat=source.stat()
        before[str(source)]=(stat.st_size,stat.st_mtime_ns,stat.st_ino)
    infos=[]
    total_rows=total_groups=0
    for index,source in enumerate(sources):
        with pq.ParquetFile(source,memory_map=False,pre_buffer=False) as pqf:
            rg=pqf.metadata.num_row_groups
            if rg>max_rowgroups or total_groups+rg>max_rowgroups:
                raise ValueError("Original factor Parquet rowgroup budget exceeded")
            schema=pqf.schema_arrow
            if len(schema)>MAX_COLS:
                raise ValueError("Factor source schema column budget exceeded")
            rows=int(pqf.metadata.num_rows)
            if rows<0:
                raise ValueError("Negative factor footer row count")
            total_rows+=rows
            total_groups+=rg
            infos.append({
                "file_ordinal":index+1,
                "footer_rows":rows,
                "row_groups":rg,
                "arrow_fields":[{"name":field.name,"type":str(field.type)}
                                for field in schema],
                "filename_year_assignment_not_verified":True,
                "date_bounds_not_inferred_from_filename":True,
                "adjustment_direction_not_certified":True,
            })
    after={str(p):(p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ino)
           for p in sources}
    if before!=after:
        raise RuntimeError("Original adjustment Parquet source changed during footer inspection")
    return {
        "status":"purchased_adjustment_factor_parquet_footer_schema_only_not_certified",
        "source_folder":LABEL,
        "source_files":len(sources),
        "source_footer_rows":total_rows,
        "source_rowgroups":total_groups,
        "file_schemas":infos,
        "original_parquet_row_groups_read":False,
        "original_parquet_ohlcva_or_factor_values_read":False,
        "source_file_stat_unchanged":True,
        "original_market_files_modified":False,
        "new_market_files_written":False,
        "source_file_years_and_exact_trade_date_coverage_certified":False,
        "factor_value_semantics_and_adjustment_direction_certified":False,
        "corporate_action_adjusted_kline_materialized":False,
        "production_activated":False,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,required=True)
    args=ap.parse_args(argv)
    print(json.dumps(inspect(args.root),ensure_ascii=False,sort_keys=True,
                     separators=(",",":")))


if __name__=="__main__":
    main()
