# worktree_patch.md — Perbesar real/dust + auto-compare saat scan

## Context
User: "perbesar tulisan detail real holder vs dust 💎 Real ≥$5: **1,470** ·
🪙 Dust: **1,634** · ratio **90% di semua cards**" + "tampilkan juga notes
di scan trending dan degen · jadi, ketika scan dilakukan, otomatis juga
akan scan perbandingan ini".

## Decisions (from ask_user)
- **card_detail_scope = all_cards**: perbesar di LP Radar + Degen Radar cards
  + Analyze page holder verdict (sudah besar via st.metric)
- **auto_scan_compare = gmgn_only**: tidak tambah API key requirement,
  pakai GMGN token_stat (top-10 holders list + total holder count) sebagai
  proxy untuk real/dust split. Tambah disclaimer bahwa data approximate.

## Approach

### 1. Perbesar tulisan real/dust di cards (LP + Degen Radar)
- Current: `font-size:0.72rem` pada `<div>` block
- Target: `font-size:0.92rem` (lebih besar, weight 700), dengan border
  halus + background subtle untuk "pop"
- Tambah emoji per row (💎 Real / 🪙 Dust) lebih prominent
- Ratio jadi colored badge (🟢 ≥50% / 🟡 30-50% / 🔴 <30%)

### 2. Auto-compare saat scan trending/HRHR
- Tambah `enrich_rows_with_holder_split(rows)` di `trending_ui.py`
- Fetch GMGN token_stat (top-10 holders + total holder count) per CA
- Compute:
  - `n_top10_real` = top-10 wallets dengan USD value ≥ $5 (price × ui_amount)
  - `n_top10_dust` = top-10 wallets dengan USD value < $5
  - `n_other_holders` = `total_holders - 10` (mostly dust for memecoins)
  - `n_real_est` = `n_top10_real` (best case — top-10 covers most real)
  - `n_dust_est` = `n_top10_dust + n_other_holders` (worst case)
  - `ratio_est` = `n_real_est / max(1, n_dust_est)`
- Add new row field `holder_split_est` and `holder_split_src`
- Display in `render_trending()` table as 2 extra inline notes:
  `💎 Real: {n_real_est:,} 🪙 Dust: {n_dust_est:,} ratio {ratio_est}% (GMGN approx)`
- Add disclaimer: "(GMGN top-10 approximation; full Helius snapshot per cron)"

### 3. Failure modes & safety
- GMGN fetch fails → row gets `holder_split_est = None`, no note added
- Top-10 holders < 10 → use whatever we have, mark `top_n_used: N`
- Price = 0 → can't compute USD value → skip
- Token is LP-only / no holders → gracefully skip

## Files to edit
- `core.py`: add `gmgn_token_stat(ca) -> dict` (extract from
  `scripts/update_cvd.py:_gmgn_top_holders`, return both `holders_list`
  and `total_holders` count)
- `scripts/update_cvd.py`: delegate to `core.gmgn_token_stat` so we have
  one source of truth
- `trending_ui.py`:
  - new function `enrich_rows_with_holder_split(rows, dust_limit_usd=5.0)`
  - call it in `run_screen` and `run_screen_hrhr` (after `gmgn_screen()`
    succeeds, before the rows hit session state) — that way the table
    auto-shows the comparison on every scan
  - new helper `_format_holder_split_note(row)` for the inline note
  - update `render_trending` to include the note in the `Notes` column
    OR as a new column — decision: append to Notes (no layout change)
- `app.py`:
  - LP Radar card `_rd_html`: increase font + colors
  - Degen Radar card `_rd_html_deg`: same
  - Refactor both to use a shared helper `_format_real_dust_html(_rd)`
- `tests/test_holder_split.py` (new): 6-8 tests for the new
  `gmgn_token_stat` / `enrich_rows_with_holder_split` / rendering
  format. Mock GMGN HTTP so tests run offline.

## Backward compatibility
- New field on row: `holder_split_est` — additive, ignored by old code
- New GMGN call only fires during `enrich_rows_with_holder_split`; can be
  turned off via `gmgn_only=False` in the function call (default ON for
  our case)
- `fetch_real_dust_ratio` in app.py unchanged (still Helius-based for
  Analyze + Radar; the new GMGN-based path is only for the screener)
- `core.gmgn_token_stat` returns the SAME shape as the old
  `_gmgn_top_holders` (holder pairs + supply), so `update_cvd.py`
  refactor is a pure delegation — no behavior change

## Verification
- `python -c "import ast; ast.parse(...)"` after each file change
- Run all 10 existing test files (must stay green)
- New test file: 6+ tests
- Manual smoke: scan trending → table shows 💎/🪙/ratio notes inline
- LP/Degen Radar cards: real/dust font visibly bigger

## Commit
- Single commit: `feat(holder-split): bigger cards + auto-compare on scan`
