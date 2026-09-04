"""Konfigurasi paket tes.

Suite ini tidak boleh menyentuh jaringan: backup durable store (pull/push
``holder_history.json.gz`` ke ref ``holder-live``) dimatikan paksa lewat
kill-switch ``HOLDER_STORE_BACKUP``. Tes yang memang menguji transport
backup mengaktifkannya kembali dengan ``mock.patch.dict`` sendiri
(lihat ``tests/test_store_backup.py``) dan tetap mem-mock fungsi transportnya.
"""
import os

os.environ["HOLDER_STORE_BACKUP"] = "0"
