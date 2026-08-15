# Fitur yang sudah dihapus

Wallet Depth hanya menggunakan Efisiensi Anomali harian. Seluruh detector,
scoring, digest, snapshot, dan format alert generasi sebelumnya telah dihapus,
bukan dinonaktifkan.

Yang tetap aktif:

- watchlist add/remove dan sinkronisasi GitHub;
- fetch trade GMGN dengan fallback Helius;
- candle GeckoTerminal;
- listing Trending/Degen tanpa ranking;
- penyimpanan `daily_effort.json`;
- chart tujuh hari dan alert Telegram S1–S4.

Jangan menghidupkan kembali modul lama. Perubahan klasifikasi hanya boleh
mengikuti formula dan threshold di `AGENTS.md`.
