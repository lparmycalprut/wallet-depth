# -*- coding: utf-8 -*-
"""Markup-risk and AI-prompt tests (no pytest, files, or network).

Run with:  python tests/test_markup_ai_prompt.py
"""
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ai_prompt  # noqa: E402
import cvd  # noqa: E402
import trending_ui  # noqa: E402

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def close(actual, expected, tolerance=1e-9):
    return math.isclose(actual, expected, rel_tol=tolerance,
                        abs_tol=tolerance)


def candle(low, high, close_price, ts=0):
    return {"ts": ts, "o": close_price, "h": high, "l": low,
            "c": close_price, "v": 1.0}


class TempPaths:
    """Keep every cvd path pointed away from committed production data."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (cvd.CVD_PATH, cvd.CONV_PATH)
        cvd.CVD_PATH = os.path.join(self.tmp.name, "cvd.json")
        cvd.CONV_PATH = os.path.join(self.tmp.name, "conviction.json")
        return self

    def __exit__(self, *args):
        cvd.CVD_PATH, cvd.CONV_PATH = self.saved
        self.tmp.cleanup()


def test_markup_contract():
    print("\n[markup] 48h window base (first candle close), thresholds, peak, and invalid input")
    with TempPaths():
        check(cvd.markup_from_candles([candle(1, 2, 1)] * 2) is None,
              "fewer than 3 candles returns None")
        sample = [candle(10, 20, 15)] * 3
        check(cvd.markup_from_candles(sample, price_now=0) is None,
              "non-positive current price returns None")
        check(cvd.markup_from_candles(sample, price_now="bad") is None,
              "invalid current price returns None")

        # Base is the FIRST candle's close, not the lowest low
        # So a token that had a very old low=1 but recent candles at 10-50
        # will only see the 48h move, not the ancient low.
        bars = [candle(10, 20, 10)] + [candle(15, 50, 40, i)
                                        for i in range(4)]
        result = cvd.markup_from_candles(bars, price_now=40)
        check(close(result["markup_pct"], 300.0),
              "base is the first candle close (10), so +300%")
        check(close(result["peak_markup_pct"], 400.0),
              "peak markup is measured from the same base")
        check(close(result["off_peak_pct"], -20.0),
              "off-peak is the signed drawdown from the peak")
        check(result["past_peak"] is True,
              "past_peak is true below the historical peak")
        check(result["level"] == "danger",
              "exactly +300% reaches danger")

        default_price = cvd.markup_from_candles(bars)
        check(close(default_price["markup_pct"], 300.0),
              "price_now=None uses the latest close (40)")
        check(default_price["level"] == "danger",
              "+300% is still danger")
        below = cvd.markup_from_candles(bars, price_now=14.9)
        check(below["level"] == "ok", "below +50% remains ok")


def test_analysis_windows():
    print("\n[windows] every CVD row fits inside the selected fetch")
    expected = {
        4: [4], 6: [4, 6], 8: [4, 8], 12: [4, 6, 12],
        24: [6, 12, 24], 36: [9, 18, 36], 48: [12, 24, 48],
    }
    for requested, windows in expected.items():
        got = cvd.analysis_windows(requested)
        check(got == windows,
              f"{requested}h selection produces supported rows {got}")
        check(all(window <= requested for window in got),
              f"{requested}h selection never claims a longer window")
    check(cvd.analysis_windows("bad") == [],
          "invalid selected window degrades to an empty list")


def test_markup_copy():
    print("\n[markup] UI labels and warnings")
    danger = {"level": "danger", "markup_pct": 320,
              "off_peak_pct": -25, "past_peak": True}
    warn = {"level": "warn", "markup_pct": 175,
            "off_peak_pct": 0, "past_peak": False}
    check("DANGER" in cvd.markup_label(danger),
          "danger label is explicit")
    check("WARNING" in cvd.markup_label(warn),
          "warning label is explicit")
    check("+320%" in cvd.markup_warning(danger) and
          "25% di bawah puncak" in cvd.markup_warning(danger),
          "danger copy includes markup and peak drawdown")
    check("exit liquidity" in cvd.markup_warning(danger),
          "danger copy explains the actionable risk")
    check(cvd.markup_warning({"level": "ok"}) == "",
          "ok markup emits no warning")


def prompt_fixture(available_hours=8):
    now = 1_800_000_000.0
    swaps = [
        ("buy", 4.0, now - 23 * 3600, "WhaleOldBuy111111111"),
        ("sell", 5.0, now - 17 * 3600, "WhaleSeller2222222"),
        ("buy", 1.0, now - 11 * 3600, "RetailBuyer3333333"),
        ("buy", 6.0, now - 5 * 3600, "WhaleNewBuy444444"),
    ]
    windows = {
        6: {"swaps": 1, "net": 6, "whale_net": 6, "retail_net": 0,
            "pure_buy": 6, "pure_sell": 0, "net_pure": 6,
            "conviction": 100, "verdict": "accum"},
        24: {"swaps": 4, "net": 6, "whale_net": 5, "retail_net": 1,
             "pure_buy": 10, "pure_sell": 5, "net_pure": 5,
             "conviction": 66.7, "verdict": "mixed"},
        # The existing page may calculate a 48h row from a shorter fetch.
        # The prompt must not present that unsupported label.
        48: {"swaps": 4, "net": 6, "whale_net": 5, "retail_net": 1,
             "pure_buy": 10, "pure_sell": 5, "net_pure": 5,
             "conviction": 66.7, "verdict": "partial"},
    }
    wallets = [
        {"wallet": "WhaleNewBuy444444", "role": "pure accumulator",
         "buy": 6, "sell": 0, "swaps": 1, "age": "🐣 12h",
         "flags": ""},
        {"wallet": "WhaleSeller2222222", "role": "pure distributor",
         "buy": 0, "sell": 5, "swaps": 1, "age": "🌱 8d",
         "flags": "DCA"},
        {"wallet": "WhaleOldBuy111111111", "role": "pure accumulator",
         "buy": 4, "sell": 0, "swaps": 1, "age": "🌳 40d",
         "flags": ""},
    ]
    return ai_prompt.build_ai_prompt(
        symbol="TEST", ca="TestCA", requested_hours=24,
        available_hours=available_hours, swaps=swaps,
        window_stats=windows, wallet_rows=wallets,
        price_now=0.001, market_cap=500_000, now_ts=now,
        period_count=4)


def test_prompt_order_and_honesty():
    print("\n[prompt] glossary first and incomplete-data honesty")
    prompt = prompt_fixture(available_hours=8)
    glossary_at = prompt.index("GLOSARIUM WAJIB")
    honesty_at = prompt.index("KEJUJURAN DAN CAKUPAN DATA")
    identity_at = prompt.index("IDENTITAS SNAPSHOT")
    check(glossary_at < honesty_at < identity_at,
          "glossary renders before all snapshot metrics")
    check("Whale** = satu swap **≥3 SOL" in prompt,
          "glossary fixes the whale threshold at 3 SOL")
    check("toleransi\n  lawan arah maksimal **5%**" in prompt,
          "glossary defines pure-wallet tolerance")
    check("persentase volume beli ukuran-whale" in prompt,
          "glossary defines conviction before reporting it")
    check("DATA TIDAK PENUH" in prompt and
          "diminta 24 jam" in prompt and "hanya 8 jam" in prompt,
          "short coverage is stated explicitly")
    check("DILARANG menyimpulkan tren" in prompt,
          "incomplete data forbids a trend conclusion")
    check("| 48h |" not in prompt,
          "summary omits windows longer than the selected 24h fetch")
    check("| 24h | tidak penuh |" in prompt and
          "| 6h | lengkap |" in prompt,
          "each summary row states whether its own window is covered")
    check("TIDAK TERCAKUP" in prompt and "SEBAGIAN" in prompt,
          "timeline does not disguise missing periods as zero flow")


def test_prompt_tables_and_tasks():
    print("\n[prompt] chronological periods, wallet ages, and task contract")
    prompt = prompt_fixture()
    labels = ["T-24h → T-18h", "T-18h → T-12h",
              "T-12h → T-6h", "T-6h → sekarang"]
    positions = [prompt.index(label) for label in labels]
    check(positions == sorted(positions),
          "timeline is rendered oldest to newest in 4 periods")
    check("Umur 🐣/🌱/🌳" in prompt and all(
        icon in prompt for icon in ("🐣 12h", "🌱 8d", "🌳 40d")),
        "wallet table carries all three age classes")
    for scenario in ("take profit", "distribusi ke retail",
                     "rotasi antar-whale", "akumulasi", "shakeout",
                     "churn"):
        check(scenario in prompt, f"task includes {scenario} scenario")
    check("perlu panik atau tidak" in prompt,
          "AI must make a firm panic-or-not assessment")
    check("membatalkan pembacaan" in prompt,
          "AI must state invalidation conditions")
    check("bahasa Indonesia" in prompt and
          "Jangan memberi target harga" in prompt,
          "language and no-price-target rules are explicit")
    complete = prompt_fixture(available_hours=24)
    check("DATA MENCUKUPI" in complete and
          "DATA TIDAK PENUH" not in complete,
          "complete coverage receives the complete-data status")


def test_screener_note_styles():
    print("\n[screener UI] T10 danger and ATH retrace use semantic glow")
    t10 = trending_ui._format_note_part("T10 29% too concentrated")
    check("color:#ef4444" in t10 and "text-shadow" in t10,
          "T10 concentration warning is bright glowing red")

    ath = trending_ui._format_note_part("Down 90.0% dari ATH")
    check("color:#22c55e" in ath and "text-shadow" in ath,
          "90% ATH retrace note is bright glowing green")

    shallow = trending_ui._format_note_part("Down 89.9% dari ATH")
    check("text-shadow" not in shallow,
          "ATH green glow starts at 90%, not below it")
    check("tidak menambah Fit" in trending_ui.CAPTION,
          "caption states that ATH retrace is display-only")
    labels = [label for label, _ in trending_ui.COLUMNS]
    check("🧠 Smart" not in labels,
          "smart-money column is removed from the screener")


def test_ui_integration_guards():
    print("\n[integration] safety sweep and Prompt to AI wiring")
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as handle:
        app_source = handle.read()
    with open(os.path.join(ROOT, "pages", "4_📊_CVD.py"),
              encoding="utf-8") as handle:
        page_source = handle.read()
    with open(os.path.join(ROOT, "pages", "5_🔔_Signals.py"),
              encoding="utf-8") as handle:
        signals_source = handle.read()
    with open(os.path.join(ROOT, "DEPLOY.md"), encoding="utf-8") as handle:
        deploy_source = handle.read()

    sweep_at = app_source.index("WATCHLIST MARKUP SAFETY")
    radar_at = app_source.index("if _conv_hist:")
    check(sweep_at < radar_at,
          "watchlist markup sweep runs before the LP Radar block")
    check("🟢 KOKOH" not in app_source,
          "LP Radar stability badges (KOKOH/GOYAH/MELEMAH) are disabled")
    check("💪 STRONG" not in app_source,
          "LP Radar volume-quality indicators are disabled")
    check("for offset in range(0, len(cas), 30)" in app_source and
          "cas[:30]" not in app_source,
          "DexScreener batching covers the entire watchlist")
    check("ThreadPoolExecutor" in app_source and
          "executor.map(fetch_one, pairs)" in app_source,
          "daily-candle sweep fetches watchlist pools concurrently")
    check(app_source.count("href='{_cvd_link}'") >= 2 and
          'f"<a href=\'/CVD?ca={_ca}\'' not in app_source,
          "LP Radar / Degen Radar cards avoid invalid nested anchor markup")
    check("_markup[\"level\"] == \"danger\"" in app_source,
          "the independent red banner is limited to +300% danger")
    check("dexscreener.com" in app_source and "gmgn.ai" in app_source,
          "existing DexScreener and GMGN shortcuts are preserved")
    check(page_source.count('selectbox("Time window"') == 1,
          "CVD page still has exactly one time-window dropdown")
    check("WINDOWS = analysis_windows(hours)" in page_source,
          "CVD page never adds an unsupported 48h row")
    check("now_ts = fetched_at" in page_source,
          "cached reruns stay anchored to the original data snapshot")
    check('st.button("🤖 Prompt to AI"' in page_source and
          "build_ai_prompt(" in page_source,
          "CVD page exposes and wires the Prompt to AI button")
    guard_types = ("guard_breakout", "guard_failed_breakout",
                   "guard_breakdown", "guard_spring", "guard_reclaim")
    check(all(kind in signals_source for kind in guard_types),
          "Signals page renders every Breakout Guard event type")
    check('helius_api_key = "PASTE-HELIUS-API-KEY-DI-SINI"' in deploy_source,
          "deployment docs contain a placeholder, not a live API key")


if __name__ == "__main__":
    test_markup_contract()
    test_analysis_windows()
    test_markup_copy()
    test_prompt_order_and_honesty()
    test_prompt_tables_and_tasks()
    test_screener_note_styles()
    test_ui_integration_guards()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
