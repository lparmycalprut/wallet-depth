# LP Entry Check

Tool kecil untuk menilai apakah sebuah token **bagus untuk entri LP** di Meteora DLMM.
Cukup tempel contract address (CA), tool mengambil data pool dari Meteora dan memberi verdict.

```bash
python3 tools/lp_entry_check/lp_entry_check.py <CONTRACT_ADDRESS>
python3 tools/lp_entry_check/lp_entry_check.py            # tempel CA saat diminta
python3 tools/lp_entry_check/lp_entry_check.py <CA> --json
```

Hanya memakai pustaka standar Python 3.9+. Tidak butuh Streamlit atau paket lain.

## Verdict

| Verdict | Arti |
|---|---|
| BAGUS UNTUK ENTRI | Semua cek lolos. |
| TUNGGU | Harga belum tenang, fee belum stabil, atau likuiditas aktif kurang. |
| TIDAK COCOK | Fee/TVL 24H di bawah 5%. |
| HINDARI | Harga bergerak ekstrem (≥ 30%) dalam 1 jam terakhir. |
| BELUM CUKUP DATA | Ada cek yang tidak terukur (misalnya pool baru atau gagal fetch). |
| TIDAK ADA POOL | Tidak ada pool Meteora untuk CA itu. |

## Cek yang dilakukan

1. **Gerak ekstrem 1H**: `|Δ harga 1H| < 30%`.
2. **Harga tenang** per window: `|Δ| ≤ 10%` (1H), `≤ 20%` (4H), `≤ 30%` (12H).
3. **Fee/TVL 24H ≥ 5%**. Untuk pool yang belum genap 24 jam, nilainya adalah fee sejak dibuat.
4. **Fee stabil**: laju fee per jam pada 1H dibanding 4H berada di rentang 0,5–2,0.
5. **Likuiditas aktif**: `active_tvl ÷ tvl ≥ 50%`.

Info saja (tidak mengubah verdict): lonjakan volume 1H ≥ 200%.

## Catatan

- Perubahan harga 0% pada pool yang belum genap 24 jam dianggap **tidak terukur**, sama seperti aturan di Best Pool.
- Tool memilih pool dengan TVL terbesar untuk token itu. Kalau ada beberapa pool, peringatan akan ditampilkan.
- `min_price` dan `max_price` dari API berubah per timeframe, jadi tool **tidak** memakainya untuk menilai range. Tool juga tidak tahu range yang akan Anda pasang.
- Ambang adalah heuristik. Blok `KONSTANTA` di `lp_entry_check.py` adalah satu-satunya tempat untuk mengubahnya.
- Tool ini bukan saran investasi.

## Tes

```bash
python3 -m unittest tests.test_lp_entry_check
```

Tes tidak memanggil jaringan dan memakai data pool asli yang sudah diambil sebagai fixture.
