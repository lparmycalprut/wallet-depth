# 📊 MORTY Dust % Market Cap Tracker

Grafik **perubahan % Market Cap yang dipegang oleh dust wallets ($0-$10)** untuk token $MORTY.

## 🎯 Tujuan

Mengganti **dropdown** dengan **line chart interaktif** yang menampilkan:
- Perubahan % Market Cap dust wallets dari waktu ke waktu
- Statistik: Current, 30d Average, 30d Max, 24h Change
- Data historis 30 hari terakhir
- Dark theme yang cocok dengan dashboard crypto

---

## 📁 Struktur File

```
cron/
├── dust_history.json          # Database historis (auto-generated)
├── historical_dust_tracker.py # Cron job untuk catat data (Python)
├── historical_dust_tracker.js # Alternatif Node.js (jika diperlukan)
├── dust_chart.html            # Grafik HTML (Chart.js)
├── server.js                  # Express server untuk serve chart
├── package.json               # Dependencies Node.js
└── README.md
```

---

## ⚙️ Setup (Python-based)

### 1. Pastikan Python Environment Siap

Proyek ini sudah menggunakan Python. Pastikan dependencies terinstall:

```bash
cd /home/user/wallet-depth
pip install -r requirements.txt
```

### 2. Setup Cron Job

#### Opsi A: Linux Cron (Recommended)

Edit crontab:
```bash
crontab -e
```

Tambahkan (simpan setiap jam untuk $MORTY):
```
0 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
```

> **Note**: Ganti `7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU` dengan token address $MORTY yang benar.

#### Opsi B: Jalankan Manual untuk Test

```bash
# Test langsung
python3 cron/historical_dust_tracker.py 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU

# Lihat hasil
cat cron/dust_history.json
```

---

## 🔧 Cara Kerja

### `historical_dust_tracker.py`

Script ini:
1. Menggunakan **`fetch_holders()`** dari `holder_analysis.py` untuk ambil data holder
2. Menggunakan **`classify_holders()`** untuk klasifikasi real vs dust
3. Extract **`dust_pct_mc`** (persentase Market Cap yang dipegang dust)
4. Simpan ke `dust_history.json` dengan timestamp
5. Auto-delete data > 30 hari

### Integrasi dengan Codebase yang Sudah Ada

Script sudah **terintegrasi penuh** dengan:
- ✅ `holder_analysis.py` - Fetch & classify holders
- ✅ `core.py` - Get market data (marketcap, price)
- ✅ Helius DAS API - Sumber data utama
- ✅ GMGN - Fallback jika Helius gagal

---

## 🚀 Jalankan Server untuk Chart

### Opsi 1: Node.js Server (Recommended)

```bash
# Install dependencies
cd /home/user/wallet-depth/cron
npm install

# Jalankan server
node server.js
```

Buka browser: [http://localhost:3000/dust-chart](http://localhost:3000/dust-chart)

### Opsi 2: Python Simple Server (Alternatif)

Jika tidak mau pakai Node.js:

```bash
cd /home/user/wallet-depth/cron
python3 -m http.server 8000
```

Buka: [http://localhost:8000/dust_chart.html](http://localhost:8000/dust_chart.html)

> **Note**: Data akan di-load dari `/cron/dust_history.json` (relative path)

---

## 📊 Output Grafik

### Preview

![Dust Chart](https://img.shields.io/badge/Chart.js-Line%20Chart-%23e94560?style=for-the-badge)

- **Line Chart** dengan area fill (gradient merah #e94560)
- **4 Stats Card**:
  - Current % MCAP
  - 30d Average
  - 30d Max
  - 24h Change (warna hijau/merah)
- **Responsive**: Otomatis adjust ukuran
- **Interaktif**: Tooltip saat hover
- **Dark Theme**: Background #1a1a2e

### Contoh Data Output (`dust_history.json`)

```json
{
  "entries": [
    {
      "timestamp": "2026-09-05T12:00:00.000000",
      "date": "2026-09-05",
      "time": "12:00:00",
      "token_ca": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
      "dust_percentage": 0.59,
      "dust_percentage_display": "0.5900%"
    },
    {
      "timestamp": "2026-09-05T13:00:00.000000",
      "date": "2026-09-05",
      "time": "13:00:00",
      "token_ca": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
      "dust_percentage": 0.61,
      "dust_percentage_display": "0.6100%"
    }
  ]
}
```

---

## 🔄 Integrasi dengan Frontend Yang Sudah Ada

### Opsi 1: Embed sebagai Iframe

```html
<iframe 
    src="http://localhost:3000/dust-chart" 
    width="100%" 
    height="500px" 
    frameborder="0"
    style="border-radius: 12px; background: #1a1a2e;"
></iframe>
```

### Opsi 2: Gunakan Chart.js Langsung di Streamlit

Jika pakai Streamlit (lihat `app.py`):

```python
import streamlit as st
import json
import plotly.graph_objects as go
from pathlib import Path

# Load data
@st.cache_data(ttl=300)
def load_dust_history():
    db_path = Path("cron/dust_history.json")
    if db_path.exists():
        with open(db_path) as f:
            return json.load(f)
    return {"entries": []}

data = load_dust_history()

if data["entries"]:
    # Prepare data for Plotly
    dates = [e["date"] for e in data["entries"]]
    times = [e["time"] for e in data["entries"]]
    values = [e["dust_percentage"] for e in data["entries"]]
    
    # Create figure
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=values,
        mode='lines+markers',
        name='Dust % MCAP',
        line=dict(color='#e94560', width=3),
        fill='tozeroy',
        fillcolor='rgba(233, 69, 96, 0.2)'
    ))
    
    fig.update_layout(
        title='MORTY Dust Wallet % Market Cap',
        xaxis_title='Date',
        yaxis_title='% Market Cap',
        template='plotly_dark',
        height=500
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Stats
    latest = data["entries"][-1]
    st.metric("Current Dust % MCAP", f"{latest['dust_percentage']:.2f}%")
```

### Opsi 3: React/Vue Component

Jika frontend pakai React:

```jsx
import React, { useEffect, useRef } from 'react';
import Chart from 'chart.js/auto';

export default function DustChart() {
    const chartRef = useRef(null);
    
    useEffect(() => {
        fetch('/cron/dust_history.json')
            .then(res => res.json())
            .then(data => {
                const ctx = chartRef.current.getContext('2d');
                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.entries.map(e => e.date),
                        datasets: [{
                            label: '% Market Cap (Dust: $0-$10)',
                            data: data.entries.map(e => e.dust_percentage),
                            borderColor: '#e94560',
                            backgroundColor: 'rgba(233, 69, 96, 0.1)',
                            tension: 0.4,
                            fill: true
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: { 
                            legend: { labels: { color: '#fff' } } 
                        },
                        scales: { 
                            x: { ticks: { color: '#8b8b8b' } },
                            y: { ticks: { color: '#8b8b8b' } }
                        }
                    }
                });
            });
    }, []);
    
    return <canvas ref={chartRef} />;
}
```

---

## 📈 Data yang Tersimpan

| Field | Type | Deskripsi |
|-------|------|-----------|
| `timestamp` | string | ISO format timestamp |
| `date` | string | Format: YYYY-MM-DD |
| `time` | string | Format: HH:MM:SS |
| `token_ca` | string | Token address (MORTY CA) |
| `dust_percentage` | float | Nilai % Market Cap (contoh: 0.59) |
| `dust_percentage_display` | string | Format display (contoh: "0.5900%") |

**Retensi**: 30 hari terakhir (auto-delete data lama)

---

## 🎨 Customization

### Ganti Warna Chart

Edit di `dust_chart.html`:
```javascript
borderColor: '#e94560',  // Warna line (default: merah)
backgroundColor: gradient, // Warna area fill
```

### Ganti Rentang Waktu

Edit di `historical_dust_tracker.py`:
```python
# Ubah 30 hari ke 7 hari, 90 hari, dll.
thirty_days_ago = now - timedelta(days=7)  # Simpan 7 hari terakhir
```

### Ganti Frekuensi Cron

```
# Setiap 30 menit
*/30 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py TOKEN_CA

# Setiap 6 jam
0 */6 * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py TOKEN_CA

# Setiap hari jam 12:00
0 12 * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py TOKEN_CA
```

### Ganti Token

```bash
# Untuk token lain, ganti TOKEN_CA di cron
0 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py NEW_TOKEN_ADDRESS
```

---

## 🛠️ Troubleshooting

### Error: "ModuleNotFoundError"

```bash
# Pastikan di directory yang benar
cd /home/user/wallet-depth

# Install dependencies
pip install -r requirements.txt
```

### Error: "No holders data"

1. Cek token address benar
2. Cek Helius API key tersedia di config
3. Cek koneksi internet
4. Jalankan manual untuk debug:
   ```bash
   python3 cron/historical_dust_tracker.py TOKEN_CA
   ```

### Chart tidak muncul

1. Cek server berjalan: `http://localhost:3000`
2. Cek file JSON ada: `cat cron/dust_history.json`
3. Cek console browser (F12) untuk error
4. Pastikan path benar di `dust_chart.html`

### Data tidak update

1. Cek log cron:
   ```bash
   tail -f /var/log/syslog | grep CRON
   ```
2. Jalankan cron manual:
   ```bash
   python3 cron/historical_dust_tracker.py TOKEN_CA
   ```
3. Cek file JSON:
   ```bash
   cat cron/dust_history.json
   ```

---

## 📊 Contoh Output Grafik

![Chart Preview](https://via.placeholder.com/800x500/1a1a2e/e94560?text=MORTY+Dust+%25+Market+Cap+Chart)

- **X-Axis**: Tanggal (30 hari terakhir)
- **Y-Axis**: % Market Cap (0% - 100%)
- **Line**: Merah (#e94560) dengan area fill
- **Points**: Setiap data point (per jam)
- **Stats**: 4 metric di bawah chart

---

## 🎯 Summary: Langkah-langkah

1. ✅ **Setup Cron Job**
   ```bash
   crontab -e
   # Tambahkan:
   0 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
   ```

2. ✅ **Test Cron Manual**
   ```bash
   python3 cron/historical_dust_tracker.py 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
   cat cron/dust_history.json
   ```

3. ✅ **Jalankan Server Chart**
   ```bash
   cd cron && npm install && node server.js
   ```

4. ✅ **Buka Chart**
   Browser: [http://localhost:3000/dust-chart](http://localhost:3000/dust-chart)

5. ✅ **Integrasi ke Frontend**
   - Embed iframe
   - Atau gunakan Chart.js langsung
   - Atau integrasi dengan Streamlit

---

## 📚 Referensi

- **holder_analysis.py**: `classify_holders()` - Klasifikasi real vs dust
- **core.py**: `get_market()` - Ambil marketcap & price
- **Helius DAS**: Sumber data holder utama
- **Chart.js**: Library grafik (CDN)

---

**Made with ❤️ for $MORTY Community**

*Last updated: 2026-09-05*
