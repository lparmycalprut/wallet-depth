# 🚀 Cara Deploy ke GitHub + Streamlit Cloud (Gratis)

Hasil akhir: app kamu online di URL seperti
`https://namamu-wallet-depth.streamlit.app` — bisa diakses dari HP/laptop
mana saja, dan **auto-update setiap kali kamu `git push`**.

---

## Langkah 1 — Upload ke GitHub

Repo git lokal sudah disiapkan (sudah `git init` + commit pertama).
`config.json` yang berisi API key **sudah otomatis dikecualikan** lewat
`.gitignore`, jadi aman.

1. Buat repo baru di [github.com/new](https://github.com/new)
   — nama bebas, misal `wallet-depth`. **Jangan** centang "Add README".
2. Dari folder `wallet-depth/`, jalankan:

```bash
git remote add origin https://github.com/lparmycalprut/wallet-depth.git
git branch -M main
git push -u origin main
```

> Saat diminta password, pakai **Personal Access Token** (buat di
> GitHub → Settings → Developer settings → Tokens), bukan password akun.

## Langkah 2 — Deploy di Streamlit Community Cloud

1. Buka [share.streamlit.io](https://share.streamlit.io) → login pakai akun GitHub.
2. Klik **Create app** → **Deploy a public app from GitHub**.
3. Pilih repo `wallet-depth`, branch `main`, main file: **`app.py`**.
4. Sebelum klik Deploy, buka **Advanced settings → Secrets**, lalu paste:

```toml
helius_api_key = "PASTE-HELIUS-API-KEY-DI-SINI"
helius_extra_keys = "KEY-KEDUA,KEY-KETIGA"  # optional
```

5. Klik **Deploy**. Tunggu ±2 menit → app online! 🎉

> API key TIDAK ditaruh di repo. Di cloud, app membaca key dari **Secrets**
> (app.py sudah mendukung ini otomatis). Di lokal tetap pakai `config.json`.

## Langkah 3 — Update app kapan saja

Edit file di komputermu, lalu:

```bash
git add -A
git commit -m "update fitur X"
git push
```

Streamlit Cloud mendeteksi push dan **otomatis redeploy** dalam ~1 menit.
Bisa juga edit langsung dari github.com (tombol ✏️ di file) → commit →
auto-deploy juga.

## Menjalankan di komputer lain

```bash
git clone https://github.com/lparmycalprut/wallet-depth.git
cd wallet-depth
cp config.example.json config.json   # lalu isi API key
pip install -r requirements.txt
streamlit run app.py
```

## Catatan

- **Repo publik vs privat**: Streamlit Cloud free bisa deploy dari repo
  **privat** juga — disarankan privat kalau mau lebih tenang.
- **Sleep**: app gratisan "tidur" setelah beberapa hari tidak diakses;
  pengunjung berikutnya cukup klik tombol wake up (~30 detik).
- Tombol "💾 Simpan ke config.json" hanya efektif saat jalan lokal
  (filesystem di cloud bersifat sementara) — di cloud gunakan Secrets.
