"""Konfigurasi paket tes.

Suite ini tidak boleh menyentuh jaringan: backup durable store (pull/push
``holder_history.json.gz`` ke ref ``holder-live``) dimatikan paksa lewat
kill-switch ``HOLDER_STORE_BACKUP``. Tes yang memang menguji transport
backup mengaktifkannya kembali dengan ``mock.patch.dict`` sendiri
(lihat ``tests/test_store_backup.py``) dan tetap mem-mock fungsi transportnya.

"""
import os

import alert_settings as _as

os.environ["HOLDER_STORE_BACKUP"] = "0"

# Toggle alert (``alert_settings``) dibaca/ditulis dari UI → cron. Suite tidak
# boleh menyentuh GitHub sama sekali: baca remote = None (jatuh ke file lokal /
# default), tulis remote = sukses palsu (tanpa network). Tes yang memang
# menguji transport-nya mem-mock kedua fungsi ini sendiri.
_as._read_remote = lambda *args, **kwargs: None
_as._write_remote = lambda *args, **kwargs: True

# Panel 🧾 Log Aktivitas memeriksa sisa kredit key Helius (thread latar).
# Suite tidak boleh menyentuh jaringan sama sekali, jadi probe-nya dimatikan;
# tes transport kredit (tests/test_helius_usage.py) menyalakannya lagi sendiri.
os.environ["HELIUS_USAGE_PROBE"] = "0"

# Cache berkas hasil scan (``scan_result_cache``) membuat card Best Pool tahan
# refresh browser, tetapi runner ``unittest`` tidak punya fixture ``tmp_path``
# seperti pytest — dimatikan di sini supaya ``python -m unittest discover``
# tidak pernah menulis ke repo. pytest menghidupkannya kembali per-tes lewat
# fixture ``_iso_scan_cache`` di ``tests/conftest.py`` (direktori sementara).
os.environ.setdefault("SCAN_CACHE", "0")

# Pajak/dividend Best Pool (``token_tax``) memanggil StonkFun + pump.fun.
# Suite tidak boleh menyentuh jaringan: fetch dimatikan di sini (bukan hanya
# di conftest — runner ``unittest`` tidak memuat fixture pytest). Tes parser
# memakai payload lokal; tes fetch mem-mock HTTP sendiri.
os.environ["TOKEN_TAX_FETCH"] = "0"
