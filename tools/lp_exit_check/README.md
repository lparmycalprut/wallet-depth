# 🚪 Cek LP Keluar (Meteora)

Tool kecil untuk satu pertanyaan: **apakah likuiditas pool sedang ditarik?**
Tempel CA, tool mengambil data pool Meteora per window (1H, 4H, 12H, 24H) dan
melaporkan deposit, withdraw, dan net deposit.

## Sinyal
- `net deposit = total_deposits − total_withdraws` (sama dengan field `net_deposits` dari Meteora).
- **Net negatif** berarti withdraw lebih besar dari deposit, yaitu LP sedang keluar.
- Net negatif di 1H atau 4H → **LP KELUAR TERBARU**.
- Net negatif hanya di 12H atau 24H → **LP KELUAR SEBELUMNYA**.
- Tidak ada net negatif dan semua window terukur → **TIDAK ADA SINYAL**.

Catatan: "net negatif" dan "withdraw lebih besar dari deposit" adalah kondisi yang sama,
karena `net = deposit − withdraw`. Tool hanya memakai satu cek.

## Pemakaian
```
python3 tools/lp_exit_check/lp_exit_check.py <CONTRACT_ADDRESS>
python3 tools/lp_exit_check/lp_exit_check.py <CA> --json
```

Halaman Streamlit: **🚪 Cek LP Keluar** (`pages/12_🚪_Cek_LP_Keluar.py`, UI di `lp_exit_ui.py`).
Hasil di-cache 60 detik. Halaman ini tidak menyimpan apa pun dan tidak mengubah watchlist.

## Batasan
- Hanya heuristik dari angka per window. Tidak menilai harga, fee, IL, atau risiko token.
- Field deposit/withdraw bergantung pada cara Meteora menghitung window. Nilai antar window bisa tidak konsisten, terutama pada pool dengan data sedikit.
- Bila pool punya beberapa pool, yang dinilai adalah pool dengan TVL terbesar.
- Hanya memakai pustaka standar Python 3.9+.
