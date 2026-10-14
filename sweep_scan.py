# -*- coding: utf-8 -*-
"""Orkestrator scan page **🌊 Sweep** — dipakai bersama UI dan cron.

Satu putaran :func:`run_scan`:

1. ambil metrik tiap mint (DexScreener + RugCheck + GMGN) — paralel;
2. simpan snapshot per jam ke state;
3. jalankan 5 kriteria skor + gate authority (:mod:`sweep_screen`);
4. deteksi sweep dari candle GeckoTerminal (1 jam untuk kriteria 6, 5 menit
   untuk deteksi sweep);
5. perbarui hasil sinyal lama (``max_up_pct`` / ``max_down_pct``);
6. kirim alert Telegram **hanya saat transisi status** (kelayakan / sweep).

Network **tidak** disentuh saat modul di-import, jadi aman diuji di CI dan aman
dipanggil dalam thread Streamlit.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import sweep_alert as alert
import sweep_data as data
import sweep_screen as screen
import sweep_store as store

DEFAULT_WORKERS = 4
#: Candle 1 jam untuk kriteria 5/6 dan candle 5 menit untuk deteksi sweep.
HOUR_LIMIT = 96
MIN5_LIMIT = 120


def _fetch_bundle(mint: str, *, use_cache: bool = True) -> dict:
    """Metrik + candle terbaru + jendela kelahiran pool utama untuk satu mint."""
    metrics = data.collect_metrics(mint, use_cache=use_cache)
    pool = metrics.get("pair_address") or ""
    candles_hour = (data.ohlcv(pool, "hour", limit=HOUR_LIMIT,
                               use_cache=use_cache) if pool else [])
    candles_min5 = (data.ohlcv(pool, "min5", limit=MIN5_LIMIT,
                               use_cache=use_cache) if pool else [])
    cohort = data.cohort_ohlcv_detail(
        pool, metrics.get("pair_created_at"), use_cache=use_cache)
    return {"mint": mint, "metrics": metrics,
            "candles_hour": candles_hour, "candles_min5": candles_min5,
            "cohort_candles": cohort["rows"],
            "cohort_error": cohort["error"]}


def analyze(bundle: dict, snapshots=None, *, state=None, now=None) -> dict:
    """Skrining + deteksi sweep untuk satu mint (tanpa jaringan)."""
    bundle = bundle or {}
    metrics = bundle.get("metrics") or {}
    snapshots = snapshots if snapshots is not None else []
    mint = bundle.get("mint") or metrics.get("mint") or ""
    result = screen.evaluate(
        metrics, snapshots=snapshots, candles=bundle.get("candles_hour") or [],
        cohort_candles=bundle.get("cohort_candles") or [],
        cohort_error=bundle.get("cohort_error"),
        state=state, mint=mint, now=now)
    event = screen.detect_sweep(bundle.get("candles_min5") or [])
    context = screen.sweep_context(
        event, result.get("liq_mc"), metrics.get("fdv_usd"),
        market_cap_usd=metrics.get("market_cap_usd")) if event else None
    return {"mint": mint, "metrics": metrics, "result": result,
            "sweep": event, "sweep_context": context}


def _scan_one(mint: str, *, use_cache: bool = True) -> dict:
    try:
        bundle = _fetch_bundle(mint, use_cache=use_cache)
        item = analyze(bundle)
        # Candle mentah tetap di memori untuk memperbarui kriteria dan profil
        # kohort setelah snapshot putaran ini tersimpan.
        for field in ("candles_hour", "candles_min5", "cohort_candles"):
            item[field] = bundle.get(field) or []
        item["cohort_error"] = bundle.get("cohort_error") or ""
        return item
    except Exception as exc:  # noqa: BLE001 - satu mint gagal ≠ scan gagal
        return {"mint": mint, "metrics": {"mint": mint, "ok": False,
                                          "error": str(exc)[:160]},
                "result": screen.evaluate({}, snapshots=[], candles=[]),
                "sweep": None, "sweep_context": None,
                "candles_hour": [], "candles_min5": [],
                "cohort_candles": [], "cohort_error": ""}


def run_scan(mints, *, state: dict | None = None,
             use_cache: bool = True, send_alerts: bool = True,
             workers: int = DEFAULT_WORKERS, now: int | None = None,
             persist: bool = False) -> dict:
    """Jalankan satu putaran scan untuk semua ``mints``.

    Mengembalikan ``{"rows": [...], "state": {...}, "alerts": [...],
    "elapsed": float}``. ``rows`` urut menurut kedekatan ke kelayakan supaya
    tabel UI langsung terbaca (lihat :func:`sweep_screen.display_sort_key`).
    Ambang kriteria ditetapkan di :mod:`sweep_screen`.
    """
    started = time.time()
    seen = store.parse_mints(mints)
    state = store.load_state() if state is None else state
    latches = state.setdefault("shakeout_latched_at", {})
    if not isinstance(latches, dict):
        latches = state["shakeout_latched_at"] = {}
    cohort_latches = state.setdefault("cohort_latched", {})
    if not isinstance(cohort_latches, dict):
        cohort_latches = state["cohort_latched"] = {}
    alerts_sent = []
    results = []

    if seen:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(seen)))) as pool:
            for item in pool.map(lambda m: _scan_one(m, use_cache=use_cache), seen):
                results.append(item)

    for item in results:
        mint = item["mint"]
        metrics = item["metrics"] or {}
        item["_snapshot_row"] = None
        # Status scan terakhir (sukses/gagal) selalu dicatat: scan gagal tidak
        # boleh tampil seolah data lama masih segar atau tersembunyi oleh filter.
        store.record_scan_status(
            state, mint, ok=bool(metrics.get("ok")),
            error=metrics.get("error") or "",
            ts=int(now if now is not None else time.time()))
        if metrics.get("ok"):
            item["_snapshot_row"] = store.add_snapshot(state, mint, metrics, ts=now)

        # First successful shakeout + higher-low detection is latched forever.
        # Later candles (including a sweep under the former low) never clear it.
        if latches.get(mint) is None:
            detected = screen.criterion_shakeout(item.get("candles_hour") or [])
            if detected.get("passed") is True:
                detected_at = screen._num(detected.get("detection_ts"))
                latches[mint] = int(detected_at if detected_at is not None
                                    else (now if now is not None else time.time()))

        history = store.mint_history(state, mint)
        # Latch kohort: sekali kohort ≤ −50% (VWAP dan GMGN) tercatat, baik live
        # maupun di riwayat harga snapshot, kelayakan kohort tidak gugur lagi.
        if cohort_latches.get(mint) is None:
            pre = item.get("result") or {}
            if pre.get("cohort_gate_passed"):
                cohort_latches[mint] = {
                    "ts": int(now if now is not None else time.time()),
                    "source": "live"}
            else:
                cohort = pre.get("cohort") or {}
                found = screen.cohort_latch_from_history(
                    store.mint_history(state, mint, limit=10_000),
                    cohort.get("vwap_48h"),
                    metrics.get("holder_cost_basis"),
                    metrics.get("holder_cost_balance"))
                if found:
                    cohort_latches[mint] = found
        # Score with complete hourly history and the stored per-mint latches.
        enriched = screen.evaluate(
            metrics, snapshots=history,
            candles=item.get("candles_hour") or [],
            cohort_candles=item.get("cohort_candles") or [],
            cohort_error=item.get("cohort_error"),
            state=state, mint=mint, now=now,
            cohort_latch=cohort_latches.get(mint))
        item["result"] = enriched
        if item.get("sweep"):
            # Inflow nyata = Δ likuiditas antar snapshot. Kalau snapshot
            # pembanding belum ada, sweep_context memakai estimasi berlabel.
            inflow = store.net_inflow(state, mint, metrics.get("liq_usd"), now=now)
            item["net_inflow_usd"] = inflow
            item["sweep_context"] = screen.sweep_context(
                item["sweep"], enriched.get("liq_mc"), metrics.get("fdv_usd"),
                market_cap_usd=metrics.get("market_cap_usd"),
                price_usd=metrics.get("price_usd"),
                liq_usd=metrics.get("liq_usd"),
                net_inflow_usd=inflow)
        # Tampilan halaman disimpan di snapshot terbaru: saat halaman dibuka,
        # data terakhir bisa ditampilkan tanpa scan ulang.
        if item.get("_snapshot_row") is not None:
            store.set_view(state, mint, item["_snapshot_row"], store.make_view(
                mint, metrics, enriched, item.get("sweep_context"),
                ts=item["_snapshot_row"]["ts"]))

    prices = {item["mint"]: (item["metrics"] or {}).get("price_usd")
              for item in results if (item["metrics"] or {}).get("price_usd")}
    store.update_outcomes(state, prices, now=now)

    # Sinyal SELALU dicatat (cron/tanpa alert pun); hanya pengiriman Telegram
    # yang dijaga send_alerts. Sebelumnya seluruh blok ini di balik send_alerts,
    # sehingga putaran tanpa alert tidak menyimpan sinyal sama sekali.
    cfg = alert.telegram_config()  # dibaca selalu; pengiriman dijaga send_alerts
    muted = alert.muted_mints()
    for item in results:
        mint = item["mint"]
        metrics = item["metrics"] or {}
        result = item["result"] or {}
        if not metrics.get("ok") or mint in muted:
            continue
        if result.get("eligible"):
            if store.alert_gate(state, mint, "eligibility", now=now):
                store.record_signal(state, {
                    "ts": int(now if now is not None else time.time()),
                    "mint": mint, "kind": "eligibility",
                    "symbol": metrics.get("symbol") or "",
                    "price_usd": metrics.get("price_usd"),
                    "base_price": metrics.get("price_usd"),
                    "entry_price": metrics.get("price_usd"),
                    "liq_mc": result.get("liq_mc"),
                    "verdict": result.get("verdict"),
                    "passed_count": result.get("passed_count"),
                    "scored_count": result.get("scored_count"),
                })
                if send_alerts and cfg.get("ok"):
                    sent, error = alert.send_message(
                        alert.format_eligibility(mint, metrics, result),
                        config=cfg)
                    alerts_sent.append({"mint": mint, "kind": "eligibility",
                                        "sent": sent, "error": error})
        else:
            store.clear_eligibility(state, mint)

        context = item.get("sweep_context")
        candle_ts = (context or {}).get("sweep_ts")
        existing = (store.find_sweep_signal(state, mint, context)
                    if context and candle_ts is not None else None)
        if existing is not None:
            # Candle sudah tercatat: hanya isi inflow nyata bila baru tersedia.
            store.backfill_sweep_inflow(
                existing, context,
                measured_at=int(now if now is not None else time.time()))
        elif context and candle_ts is not None:
            # Waktu sinyal = waktu candle sweep (bukan waktu scan), supaya
            # riwayat & outcome sejajar dengan pasar. Waktu deteksi disimpan
            # terpisah. Satu candle hanya dicatat sekali (lihat find_sweep_signal).
            scan_ts = int(now if now is not None else time.time())
            fresh = (scan_ts - (int(candle_ts) + store.SWEEP_CANDLE_SEC)
                     <= store.SWEEP_ALERT_MAX_AGE)
            signal = store.record_signal(state, {
                "ts": int(candle_ts),
                "detected_ts": scan_ts,
                "sweep_ts": int(candle_ts),
                "mint": mint, "kind": "sweep",
                "symbol": metrics.get("symbol") or "",
                "price_usd": metrics.get("price_usd"),
                "base_price": context.get("base_price"),
                "entry_price": context.get("close"),
                "peak_price": context.get("peak"),
                "liq_mc": context.get("liq_mc"),
                "vol_x": context.get("vol_x"),
                "price_mult": context.get("price_mult"),
                "peak_mult": context.get("peak_mult"),
                "est_cost_usd": context.get("est_cost_usd"),
                "est_cost_close_usd": context.get("est_cost_close_usd"),
                "churn_x": context.get("churn_x"),
                # Angka nyata (kalau ada) disimpan berdampingan dengan
                # angka teoretis — tabel statistik tidak boleh
                # menampilkan tebakan sebagai pengukuran.
                "net_inflow_usd": context.get("net_inflow_usd"),
                "churn_net_x": context.get("churn_net_x"),
                "paper_mcap_usd": context.get("paper_mcap_usd"),
                "paper_gain_usd": context.get("paper_gain_usd"),
                "leverage": context.get("leverage"),
                "leverage_net": context.get("leverage_net"),
            })
            if not send_alerts:
                signal["alert_skipped"] = "alert_nonaktif"
            elif fresh:
                sent, error = alert.send_message(
                    alert.format_sweep(mint, metrics, context), config=cfg)
                alerts_sent.append({"mint": mint, "kind": "sweep",
                                    "sent": sent, "error": error})
            else:
                signal["alert_skipped"] = "candle_terlalu_tua"

    store.prune(state)
    if persist:
        store.save_state(state, persist=True, reason="scan")
    rows = sorted(
        [{"mint": item["mint"], "metrics": item["metrics"],
          "result": item["result"], "sweep": item["sweep"],
          "sweep_context": item["sweep_context"],
          "turnover_x": (item.get("result") or {}).get("turnover_x"),
          "cohort": (item.get("result") or {}).get("cohort"),
          "cohort_gate_status": (item.get("result") or {}).get("cohort_gate_status"),
          # Hourly candles stay in memory for display/debug; they are not state.
          "candles_hour": item.get("candles_hour") or []} for item in results],
        key=lambda row: screen.display_sort_key(row["result"]),
    )
    return {"rows": rows, "state": state, "alerts": alerts_sent,
            "elapsed": time.time() - started}
