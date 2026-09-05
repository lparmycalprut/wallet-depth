"""Konfigurasi paket tes.

Suite ini tidak boleh menyentuh jaringan: backup durable store (pull/push
``holder_history.json.gz`` ke ref ``holder-live``) dimatikan paksa lewat
kill-switch ``HOLDER_STORE_BACKUP``. Tes yang memang menguji transport
backup mengaktifkannya kembali dengan ``mock.patch.dict`` sendiri
(lihat ``tests/test_store_backup.py``) dan tetap mem-mock fungsi transportnya.

Watchlist Robinhood juga di-stub kosong di sini supaya runner ``unittest``
(``python -m unittest discover -s tests -t .``) sama offline-nya dengan
pytest ``conftest.py``; tes khusus Robinhood mem-mock lapisan network-nya
sendiri.
"""
import os

import robinhood_watchlist as _rw

os.environ["HOLDER_STORE_BACKUP"] = "0"

_rw.load_watchlist = lambda *args, **kwargs: {}
_rw.load_status = lambda *args, **kwargs: {"updated_at": None, "tokens": {}}
_rw.load_history = lambda *args, **kwargs: {"updated_at": None, "tokens": {}}
