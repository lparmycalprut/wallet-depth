# Fitur yang sudah dihapus

Wallet Depth hanya menggunakan detektor **3 sinyal bottom** (CVD × volume USD
harian, batas hari 00:00 UTC). Seluruh detector, scoring, digest, snapshot,
dan format alert generasi sebelumnya telah dihapus, bukan dinonaktifkan —
termasuk framework **Efisiensi Anomali** (effort-to-result
R = |ΔCVD|/|ΔHarga%|, multiplier M, baseline sehat, S1–S5, ABSORBSI LANGSUNG,
PENYERAPAN) dan semua analisis **retention/retensi/diamond hands/holder
lock/smart buyer**.

Yang tetap aktif:

- watchlist add/remove dan sinkronisasi GitHub;
- fetch trade GMGN (diperkaya `amount_usd` + tag maker) dengan fallback Helius;
- candle GeckoTerminal;
- listing Trending/Degen tanpa ranking;
- penyimpanan `daily_effort.json` (window penyimpanan 30 hari per mint);
- chart harga/CVD + volume USD, scan seluruh window per hari;
- alert Telegram HANYA untuk 🟢 REVERSAL UP / 🔴 REVERSAL DOWN dari scanner
  realtime, dan hanya setelah struktur harga (SBR) mengonfirmasi. Alert
  harian "BOTTOM TERDETEKSI" untuk 3 sinyal bottom sudah dihentikan —
  detektor hariannya tetap dipakai dashboard saja.

Jangan menghidupkan kembali modul lama. Perubahan klasifikasi hanya boleh
mengikuti rumus dan threshold di `AGENTS.md`.
