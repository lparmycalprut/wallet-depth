# Bug Fix Summary - wallet-depth

Tanggal: 2026-08-04
Status: ✅ Semua 185 tests PASS

## Bug 1: Rate-limit delay di cto_deep_scan.py

**File:** `cto_deep_scan.py`  
**Lokasi:** function `main()`, loop `for i, ca in enumerate(cas_to_scan, 1):`

**Masalah:**  
Tidak ada rate-limit delay antar panggilan API per token (DexScreener/GMGN/Helius/RugCheck/GeckoTerminal dipanggil beruntun tanpa jeda), padahal `import time` sudah ada tapi tidak dipakai. File scanner lain (gmgn_screener.py, incubation_radar.py, lp_safe_radar.py) semuanya pakai `time.sleep(0.8)`.

**Fix:**
- Menambahkan parameter `--delay` (default 0.8 detik) di argparse
- Menambahkan `time.sleep(args.delay)` di akhir setiap iterasi loop (kecuali iterasi terakhir)
- Konsisten dengan scanner lain dan mengurangi risiko Cloudflare/429 block

**Diff:**
```python
# Tambah parameter
parser.add_argument("--delay", type=float, default=0.8,
                    help="seconds to sleep between API call windows per token (default 0.8)")

# Tambah sleep di akhir loop
for i, ca in enumerate(cas_to_scan, 1):
    # ... existing code ...
    print(f"  Pass: {res.get('pass')} Reasons: {' | '.join(res.get('reasons',[])[:6])}")
    if i < len(cas_to_scan):
        time.sleep(args.delay)
```

---

## Bug 2: Silent exception di scripts/update_cvd.py

**File:** `scripts/update_cvd.py`  
**Lokasi:** baris 162, blok `except Exception as e:`

**Masalah:**  
Exception ditangkap tapi tidak pernah di-log, sehingga kegagalan jalur Helius holder snapshot pada cron per-jam sama sekali tidak terlihat oleh operator.

**Fix:**
- Menambahkan log eksplisit sebelum fallback ke GMGN
- Tetap lanjut fallback seperti biasa (tidak mengubah logika fallback)

**Diff:**
```python
except Exception as e:
    # fall through to GMGN; don't crash the cron
    print(f"WARN: helius holder snapshot failed for {ca}: {e}")
```

---

## Bug 3: LP score error masking di pages/8_💧_LP_Safe_Radar.py

**File:** `pages/8_💧_LP_Safe_Radar.py`  
**Lokasi:** baris 191, blok `except Exception as e:`

**Masalah:**  
Kegagalan perhitungan lp_score disamarkan jadi skor 0 asli, sehingga tidak bisa dibedakan dari token yang memang mendapat skor 0.

**Fix:**
- Set `r["lp_score"] = 0` DAN tambahkan field baru `r["_lp_score_error"] = str(e)`
- Di tampilan tabel: tambahkan kolom "Reason" yang menunjukkan "⚠️ calc error" jika field error ada
- Di tampilan detail: tambahkan "⚠️ calc error" di markdown jika ada error

**Diff:**
```python
# Di except block
except Exception as e:
    r["lp_score"] = 0
    r["_lp_score_error"] = str(e)

# Di tabel display
df = pd.DataFrame([{
    "Symbol": r.get("symbol"),
    "LP Score": r.get("lp_score",0),
    # ... other columns ...
    "Reason": ("⚠️ calc error" if r.get("_lp_score_error") else ""),
    "CA": r.get("ca")[:12]+"...",
} for r in cands])

# Di detail view
_err_note = " ⚠️ calc error" if r.get("_lp_score_error") else ""
st.markdown(f"**{r.get('symbol')}** LP Score **{lp_s}/100**{_err_note} — `{ca[:12]}...` — {r.get('_lp_reason','')}")
```

---

## Bug 4: Bare except di cto_deep_scan.py dan pages/8_💧_LP_Safe_Radar.py

**File:** `cto_deep_scan.py` baris ~601, `pages/8_💧_LP_Safe_Radar.py` baris ~108

**Masalah:**  
Bare `except:` ikut menangkap KeyboardInterrupt/SystemExit, yang seharusnya tidak ditangkap.

**Fix:**
- Ganti `except:` menjadi `except Exception:` di kedua lokasi

**Diff:**
```python
# cto_deep_scan.py line 601
- except:
+ except Exception:
    pass

# pages/8_💧_LP_Safe_Radar.py line 108
- except:
+ except Exception:
    r["lp_score"] = 85
```

---

## Bug 5: F-string tanpa placeholder

**Files:** 
- `app.py` baris 952 & 1593
- `cto_deep_scan.py` baris 127 & 897 (sekarang 901)
- `lp_safe_radar.py` baris 492
- `pages/4_📊_CVD.py` baris 342
- `pages/8_💧_LP_Safe_Radar.py` baris 155 (bonus)

**Masalah:**  
F-string digunakan tanpa placeholder `{}`, yang tidak perlu dan membingungkan.

**Keputusan untuk tiap lokasi:**
Semua kasus di atas adalah string statis tanpa interpolasi. Prefix `f` dihapus karena tidak ada variabel yang perlu diinterpolasi.

**Diff:**
```python
# app.py:952
- svg = (f"<div style='font-size:0.68rem;color:#64748b;"
-        f"margin-top:4px;'>1 titik tercatat — grafik muncul "
-        f"setelah cron jam berikutnya.</div>")
+ svg = ("<div style='font-size:0.68rem;color:#64748b;"
+        "margin-top:4px;'>1 titik tercatat — grafik muncul "
+        "setelah cron jam berikutnya.</div>")

# app.py:1593
- _conv_html = (
-     f"<span style='color:#94a3b8;font-size:1.15rem;"
-     f"font-weight:800;'>⏰ stale</span>")
+ _conv_html = (
+     "<span style='color:#94a3b8;font-size:1.15rem;"
+     "font-weight:800;'>⏰ stale</span>")

# cto_deep_scan.py:127
- r = rq.get(f"https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
+ r = rq.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)

# cto_deep_scan.py:901
- print(f"\n=== SUMMARY ===")
+ print("\n=== SUMMARY ===")

# lp_safe_radar.py:492
- print(f"\n=== CATJAK LP SAFE RADAR ===")
+ print("\n=== CATJAK LP SAFE RADAR ===")

# pages/4_📊_CVD.py:342
- st.info(f"Fetching focus range from GMGN Trades API…")
+ st.info("Fetching focus range from GMGN Trades API…")

# pages/8_💧_LP_Safe_Radar.py:155
- st.info(f"No LP Safe passed, showing top 20 closest rejects for tuning:")
+ st.info("No LP Safe passed, showing top 20 closest rejects for tuning:")
```

---

## Verifikasi

### Pyflakes check
```bash
$ python -m pyflakes app.py cto_deep_scan.py lp_safe_radar.py pages/*.py scripts/*.py
# No f-string warnings
```

### Test suite
```bash
$ python -m pytest tests/ -q
185 passed in 4.78s
```

Semua 185 tests tetap PASS tanpa modifikasi test suite.

---

## Files Modified

1. `cto_deep_scan.py` - 3 changes (rate-limit, bare except, f-string)
2. `scripts/update_cvd.py` - 1 change (exception logging)
3. `pages/8_💧_LP_Safe_Radar.py` - 3 changes (error field, bare except, f-string)
4. `app.py` - 2 changes (f-strings)
5. `lp_safe_radar.py` - 1 change (f-string)
6. `pages/4_📊_CVD.py` - 1 change (f-string)

Total: 6 files changed, 20 insertions(+), 13 deletions(-)
