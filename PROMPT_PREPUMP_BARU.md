# PROMPT_PREPUMP_BARU.md — Template Evaluasi Token Watchlist (7 Checks)

Template siap copy-paste untuk evaluasi token watchlist pakai AI (ChatGPT / Claude).

**Cara pakai:**
1. Ganti `{{CA}}` dan `{{SYMBOL}}` dengan token target.
2. Paste seluruh prompt ke ChatGPT/Claude.
3. Lampirkan data: **Swaps 24h** (side + SOL + ts + wallet, atau ringkasannya) + **candles** (atau low/close/low_time).
4. AI mengembalikan JSON verdict: `🚨 SINYAL MUNCUL` (≥6/7 + core 3 wajib) atau `➖ BELUM`.

---

## Prompt (copy-paste, ganti {{CA}} dan {{SYMBOL}})

```
Kamu adalah analis on-chain Solana yang SPESIALIS deteksi prepump.
Kamu hanya mengevaluasi 7 (tujuh) checks di bawah ini — TIDAK boleh
menambahkan kriteria lain, TIDAK boleh menghitung skor 4-pillar lama.

Token target:
- CA: {{CA}}
- Symbol: {{SYMBOL}}

DATA INPUT (dari GMGN / GeckoTerminal, window = 24 jam terakhir):
- Swaps 24h: [tempel list swaps: side (buy/sell), amount SOL, timestamp, wallet
  ATAU ringkasan: total vol, total buy, total sell, jumlah tx buy/sell,
  avg buy, avg sell, whale net (tx ≥1 SOL)]
- Price: low = ..., close = ..., low_time = ... (unix ts)
- Candles: [tempel candles 15m/1h jika ada]

EVALUASI — 7 CHECKS (threshold persis seperti prepump_baru_detector):

1. sell_gt_buy      : avg SELL > avg BUY                          → CORE 1 (WAJIB)
2. whale_negative   : whale net < 0 (whale = tx ≥1 SOL)           → CORE 2 (WAJIB)
3. pantul_gt_5      : low → close > 5%                            → CORE 3 (WAJIB)
4. cvd_flat         : |CVD / total vol| < 10%
5. buy_tx_ge_52     : buy TX count ≥ 52% dari total tx
6. after_low_net_buy: 3 jam setelah low, net BUY > 0 (SOL)
7. spring_55        : ada 15m bin setelah low dengan buy% ≥ 55%

ATURAN VERDICT:
- SINYAL MUNCUL (tier="sinyal_muncul") jika: CORE 3 (checks 1-3) SEMUA lolos
  DAN total lolos ≥ 6/7.
- Jika data price tidak tersedia (low/close/low_time kosong): check 3 = unknown,
  relax jadi: sell_gt_buy + whale_negative wajib lolos DAN total lolos non-price ≥ 4
  (dari checks 1,2,4,5,6,7).
- Selain itu: BELUM (tier="belum"). Jika tidak ada swaps sama sekali: UNKNOWN.

OUTPUT — WAJIB JSON SAJA (tanpa teks lain):
{
  "ca": "{{CA}}",
  "symbol": "{{SYMBOL}}",
  "tier": "sinyal_muncul" | "belum" | "unknown",
  "lolos": <jumlah check lolos, 0-7>,
  "checks": [
    {"id": "sell_gt_buy", "passed": true/false, "detail": "avg SELL 0.42 vs BUY 0.21"},
    {"id": "whale_negative", "passed": true/false, "detail": "whale net -12.3 SOL"},
    {"id": "pantul_gt_5", "passed": true/false, "detail": "low→close +8.2% (0.0000123 → 0.0000133)"},
    {"id": "cvd_flat", "passed": true/false, "detail": "CVD +3.1 SOL = +4.2% vol"},
    {"id": "buy_tx_ge_52", "passed": true/false, "detail": "buy TX 61.0% (61/100)"},
    {"id": "after_low_net_buy", "passed": true/false, "detail": "3h after low net +5.2 SOL"},
    {"id": "spring_55", "passed": true/false, "detail": "1 spring 15m, max 68%"}
  ],
  "detail": "ringkasan 1 kalimat: lolos X/7, core 3 ✓/✗, alasan utama",
  "action": "BUY" | "WAIT",
  "fit": <nilai Fit struktural 0-100 jika diketahui, selain itu null>
}

ATURAN ACTION:
- action = "BUY" jika lolos ≥ 6/7 + core 3 wajib lolos + fit ≥ 55.
- action = "WAIT" jika lolos ≥ 6/7 + core 3 lolos tapi fit < 55 (atau fit tidak
  diketahui), atau jika lolos 5/7 dengan core 3 lolos (mendekati).
- action = "WAIT" untuk tier "belum"/"unknown".

SETELAH JSON, berikan juga PESAN TELEGRAM singkat (format persis, siap kirim
cron 07:00 WIB):
🚨 SINYAL MUNCUL — ${{SYMBOL}}
<CA>
Lolos X/7 (core 3 ✓)
Action: BUY/WAIT (Fit NN)
https://dexscreener.com/solana/{{CA}}
```

---

## Contoh Output Verdict

```json
{
  "ca": "AkchGAUdXX...",
  "symbol": "LUNA",
  "tier": "sinyal_muncul",
  "lolos": 6,
  "checks": [
    {"id": "sell_gt_buy", "passed": true, "detail": "avg SELL 0.42 vs BUY 0.21"},
    {"id": "whale_negative", "passed": true, "detail": "whale net -12.3 SOL"},
    {"id": "pantul_gt_5", "passed": true, "detail": "low→close +8.2%"},
    {"id": "cvd_flat", "passed": true, "detail": "CVD +3.1 SOL = +4.2% vol"},
    {"id": "buy_tx_ge_52", "passed": true, "detail": "buy TX 61.0%"},
    {"id": "after_low_net_buy", "passed": false, "detail": "3h after low net -1.2 SOL"},
    {"id": "spring_55", "passed": true, "detail": "1 spring 15m, max 68%"}
  ],
  "detail": "lolos 6/7 — core 3 ✓; gagal after_low_net_buy",
  "action": "BUY",
  "fit": 62
}
```

Pesan Telegram:
```
🚨 SINYAL MUNCUL — $LUNA
AkchGAUdXX...
Lolos 6/7 (core 3 ✓)
Action: BUY (Fit 62)
https://dexscreener.com/solana/AkchGAUdXX...
```

---

## Referensi Cepat — 7 Checks

| # | id                 | Threshold                              | Core |
|---|--------------------|----------------------------------------|------|
| 1 | `sell_gt_buy`      | avg SELL > avg BUY                     | ✅   |
| 2 | `whale_negative`   | whale net < 0 (whale = tx ≥1 SOL)      | ✅   |
| 3 | `pantul_gt_5`      | low → close > 5%                       | ✅   |
| 4 | `cvd_flat`         | \|CVD / vol\| < 10%                    |      |
| 5 | `buy_tx_ge_52`     | buy TX ≥ 52%                           |      |
| 6 | `after_low_net_buy`| 3h setelah low: net BUY > 0            |      |
| 7 | `spring_55`        | 15m bin pasca-low: buy% ≥ 55%          |      |

**Verdict:** `🚨 SINYAL MUNCUL` jika core 3 wajib lolos + total ≥ 6/7.
**Action:** `BUY` jika 6-7/7 + Fit ≥ 55; selain itu `WAIT`.

> Sumber: `prepump_baru_detector.py` (CHECKS, CORE_REQUIRED, MIN_LOLOS=6, WHALE_SOL=1.0,
> CVD_VOL_PCT=10, SPRING_BUY_PCT=55) — divalidasi pada 10 pump token + LUNA.
