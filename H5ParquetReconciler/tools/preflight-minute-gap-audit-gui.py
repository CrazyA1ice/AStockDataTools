#!/usr/bin/env python3
"""PowerShell-5.1-safe GUI startup check; no Python -c quote escaping.

This script parses the GUI as UTF-8, imports its module and verifies that
the expected App class exists. It never opens Tk or market files and never
starts old purchased-Parquet materialization tasks.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXPECTED_GUI = HERE / "minute-gap-audit-gui.py"


def preflight(path: Path) -> None:
    path = Path(path)
    if path.is_symlink() or path.resolve() != EXPECTED_GUI.resolve():
        raise ValueError("GUI path must match the safe source-key audit GUI")
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))
    import tkinter  # noqa: F401 - verify Tkinter is installed

    spec = importlib.util.spec_from_file_location(
        "safe_minute_gap_gui_startup_preflight", path
    )
    if spec is None or spec.loader is None:
        raise ValueError("Unable to load safe GUI module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "App"):
        raise ValueError("Safe minute-gap audit GUI App not found")
    print("GUI_PREFLIGHT_OK: UTF-8 syntax, tkinter and safe GUI imports")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", type=Path, required=True)
    args = parser.parse_args(argv)
    preflight(args.gui)


if __name__ == "__main__":
    main()
