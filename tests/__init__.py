"""Offline defaults shared by the test suite."""
import os

os.environ["HELIUS_USAGE_PROBE"] = "0"
os.environ.setdefault("SCAN_CACHE", "0")
os.environ["TOKEN_TAX_FETCH"] = "0"
