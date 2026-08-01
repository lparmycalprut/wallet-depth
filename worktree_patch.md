# worktree_patch.md — FOCUS_MODE bug audit + fix

## Context
User minta: "ok, default focus mode true ya — lalu cek sekali lagi apakah
ada kemungkinan yang menyebabkan bug dll". FOCUS_MODE sudah ON by default
(sudah di-commit di `1da409a`). Tugas sekarang: audit bug/risk dari
implementasi FOCUS_MODE + fix yang ditemukan.

## Audit findings (severity-ranked)

### 🔴 Bug #1 — `NameError: ldivs` (HIGH)
**File**: `app.py` line 3225
```python
if FOCUS_MODE and ldivs:
    st.caption("🎯 FOCUS_MODE: divergence tetap direkam ke ...")
```
- `ldivs` di-set di dalam `if all(p is not None for p in pser) and len(pser) >= 7:`
  (line 3167) — nested di dalam `if pmap:` (line 3155) → `if cvd_bucket >= 60:`
  → `if not FOCUS_MODE:` chain.
- Jika `pmap` kosong (GMGN tidak return price series), atau
  `cvd_bucket < 60` (cvd_bucket=30), atau `pser` tidak lengkap, atau
  `len(pser) < 7`, maka `ldivs` **tidak pernah diinisialisasi**.
- Saat `FOCUS_MODE=True` (default), line 3225 dieksekusi → `NameError: ldivs`.
- **Severity**: HIGH — crash di CVD section pada common paths.

**Fix**: Initialize `ldivs = []` di awal try block (atau di scope yang
mencakup line 3225). Aman: `if FOCUS_MODE and ldivs:` — empty list
adalah falsy, jadi caption tidak muncul jika tidak ada divergence.

### 🟡 Bug #2 — Degen Radar tidak punya FOCUS_MODE caption (MEDIUM)
**File**: `app.py` line 1602+ (Degen Radar caption)
- LP Radar punya FOCUS_MODE callout (line 1381-1384) tapi Degen Radar
  tidak. Konsistensi UX: user FOCUS_MODE=True akan lihat callout di LP
  tapi tidak di Degen → confusing.
- **Severity**: MEDIUM (UX inconsistency)

**Fix**: Tambah FOCUS_MODE callout di Degen Radar caption (mirip LP).

### 🟡 Bug #3 — `conviction_summary` dead import (LOW)
**File**: `app.py` line 126
- `conviction_summary` di-import tapi tidak pernah dipakai (hanya
  ada fallback def). Dead code → linter warning, tapi tidak crash.
- **Severity**: LOW

**Fix**: Hapus import yang tidak terpakai, atau gunakan `conviction_summary`
di section yang menampilkan conviction_pct di LP/Degen Radar cards.
Untuk sekarang: hapus import (simpler, less risk).

### 🟢 Bug #4 — `import json as _json` shadow built-in (LOW)
**File**: `scripts/update_cvd.py` line 224
- `import json as _json` di dalam `main()`. Best practice: import di
  top of file. Tapi `json` tidak dipakai lagi setelah block ini, jadi
  tidak masalah.
- **Severity**: LOW (style only)

**Decision**: skip — not a real bug.

## Implementation plan

1. **Fix Bug #1**: Add `ldivs = []` initialization di line 3154 (start
   of try block). Cek semua code path di bawahnya apakah `ldivs` terdefinisi
   sebelum line 3225. **Cek dengan test case: GMGN return 0 swaps**.

2. **Fix Bug #2**: Tambah FOCUS_MODE callout di Degen Radar caption.

3. **Fix Bug #3**: Hapus `conviction_summary` dari import di app.py line 126
   dan dari fallback def. (tidak akan di-break karena sudah ada di focus.py
   dan bisa di-reimport kapan saja.)

4. **Verification**:
   - Run `python -c "import ast; ast.parse(open('app.py').read())"`
   - Run all 9 test files
   - Add new test: `tests/test_focus_mode.py` dengan minimal:
     - `is_focus_mode({})` → True
     - `is_focus_mode({"focus_mode": False})` → False
     - `is_focus_mode({"focus_mode": True})` → True
     - `health_badge("missing-ca")` → dict with level/label/reason
     - `conviction_summary({...})` → reduced dict
   - Manual test: simulate CVD path yang tidak ada price series

5. **Commit**: `fix(focus): init ldivs + FOCUS_MODE callout in Degen + clean dead import`

## Backward compatibility
- Fix Bug #1: purely defensive init, tidak mengubah behavior
- Fix Bug #2: additive caption (hanya muncul saat FOCUS_MODE=True)
- Fix Bug #3: remove unused import — no consumer
- Test: baru, additive only

## Files to edit
- `app.py`: 3 changes (Bug #1, #2, #3)
- `tests/test_focus_mode.py`: new test file
- `worktree_patch.md`: this file
