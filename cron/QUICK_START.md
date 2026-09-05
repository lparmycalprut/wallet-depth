# ⚡ QUICK START: Dust % Market Cap Chart

**Waktu: 5 menit** | **Tingkat: Mudah**

---

## 🎯 Tujuan

Ganti dropdown dengan **grafik perubahan % Market Cap dust wallets ($0-$10)**.

---

## 🚀 3 LANGKAH CEPAT

### Step 1: Setup Cron (1 menit)

```bash
# Buka crontab
crontab -e

# Tambahkan baris ini (ganti TOKEN_CA dengan address $MORTY)
0 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py TOKEN_CA

# Simpan (Ctrl+X, Y, Enter)
```

**Contoh TOKEN_CA untuk $MORTY:** `7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`

---

### Step 2: Test Cron (1 menit)

```bash
# Jalankan manual
python3 /home/user/wallet-depth/cron/historical_dust_tracker.py TOKEN_CA

# Cek data
cat /home/user/wallet-depth/cron/dust_history.json
```

**Expected Output:**
```json
{"entries": [{"timestamp": "...", "dust_percentage": 0.59, ...}]}
```

---

### Step 3: Tampilkan Grafik (3 menit)

#### Opsi A: Streamlit (Jika pakai app.py)

**Tambahkan di file Streamlit:**

```python
import json
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

# Load data
@st.cache_data(ttl=300)
def load_dust():
    p = Path("cron/dust_history.json")
    return json.loads(p.read_text()) if p.exists() else {"entries": []}

# Tampilkan
data = load_dust()
if data["entries"]:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[e["date"] for e in data["entries"]],
        y=[e["dust_percentage"] for e in data["entries"]],
        mode='lines+markers',
        line=dict(color='#e94560', width=3),
        fill='tozeroy',
        fillcolor='rgba(233,69,96,0.2)'
    ))
    fig.update_layout(
        title='Dust % Market Cap ($0-$10)',
        template='plotly_dark',
        height=400
    )
    st.plotly_chart(fig, use_container_width=True)
```

#### Opsi B: HTML Standalone

```bash
# Jalankan server
cd /home/user/wallet-depth/cron
npm install && node server.js

# Buka di browser: http://localhost:3000/dust-chart
```

#### Opsi C: Embed di HTML

```html
<iframe 
    src="http://localhost:3000/dust-chart" 
    width="100%" 
    height="500px" 
    frameborder="0"
></iframe>
```

---

## ✅ SELESAI!

Anda sekarang punya:
- ✅ **Cron job** yang catat dust % MCAP setiap jam
- ✅ **Grafik interaktif** yang menampilkan perubahan
- ✅ **Data historis** 30 hari terakhir

---

## 🔧 Troubleshooting Cepat

| Problem | Solusi |
|---------|--------|
| Cron tidak jalan | `tail -f /var/log/syslog \| grep CRON` |
| No data | Jalankan manual dulu |
| Module not found | `pip install -r requirements.txt` |
| Chart tidak muncul | `node server.js` di folder cron |

---

## 📚 File Penting

| File | Deskripsi |
|------|-----------|
| `historical_dust_tracker.py` | Cron job untuk catat data |
| `dust_chart.html` | Grafik HTML |
| `server.js` | Server untuk serve grafik |
| `dust_history.json` | Database historis |

---

**Need help?** Lihat `README.md` untuk detail lengkap.
