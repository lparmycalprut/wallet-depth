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

import alert_settings as _as
import robinhood_watchlist as _rw

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

_rw.load_watchlist = lambda *args, **kwargs: {}
_rw.load_status = lambda *args, **kwargs: {"updated_at": None, "tokens": {}}
_rw.load_history = lambda *args, **kwargs: {"updated_at": None, "tokens": {}}
