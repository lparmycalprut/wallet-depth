#!/usr/bin/env python3
"""SHIM sementara — workflow lama masih memanggil file ini.

Ganti workflow ke ``python scripts/scan_holders.py`` lalu hapus file ini.
"""
import sys

from scripts.scan_holders import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
