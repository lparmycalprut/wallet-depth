# Halaman yang disembunyikan dari main app

Halaman-halaman ini **tidak tampil** di main app karena permintaan user (2026-11-10):

- `8_🌊_Sweep.py`
- `9_🔍_Cek_CA_Sweep.py`
- `10_⚡_Early_Watcher.py`
- `11_🧭_Cek_Entri_LP.py`
- `12_🚪_Cek_LP_Keluar.py`

Kodenya tetap ada di repository (tidak dihapus). Streamlit hanya membaca folder
`pages/`, jadi halaman di sini tidak terdaftar. Untuk mengaktifkan kembali,
pindahkan berkas ke `pages/` (`git mv`) lalu jalankan ulang tes.

Alert Telegram untuk Sweep dan Early Watcher juga dimatikan (cron dihapus dari
workflow dan secret Telegram tidak diteruskan). Modul pendukung (`sweep_*.py`,
`early_*.py`, `lp_*_ui.py`) tidak diubah.
