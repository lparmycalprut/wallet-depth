#!/usr/bin/env python3
"""Rantai run cron berikutnya — pengganti langkah "Chain run berikutnya".

Dulu logika ini berupa bash inline di ``.github/workflows/daily-effort.yml``.
Pindah ke skrip karena dua alasan:

1. **Bot tidak bisa menulis folder workflow** (403 ``refusing to allow a
   GitHub App to create or update workflow … without 'workflows' permission``),
   jadi setiap perbaikan ritme harus disalin user dengan tangan. Dengan
   skrip ini, YAML cukup memanggil ``python scripts/chain_next_run.py`` —
   perubahan kadens/guard berikutnya cukup lewat commit biasa;
2. bash + ``bash -e`` **fail-closed**: satu kesalahan sesaat pada
   ``ACTIVE=$(curl -sSf … | python3 -c …)`` menghentikan langkah, dispatch
   tidak terkirim, dan seluruh pipeline mati sampai ``schedule`` berikutnya
   (yang bisa berjam-jam — lihat di bawah).

Kenapa chain dispatch ada: ``schedule: cron "*/5 * * * *"`` GitHub bersifat
best-effort dan bisa di-throttle parah. Data nyata 2026-09-09 (workflow
``Holder Dust Scanner``, repo publik, tanpa masalah billing): schedule hanya
menyala 4× sehari (01:35, 06:41, 11:56, 16:30 UTC — jarak 4,5–5,2 JAM), tiap
kejadian hanya menghasilkan SATU run dispatch lalu hening ±4,5 jam. Korban
terakhir: run #1182 selesai 16:40:24 UTC, tidak ada scan lagi sampai
17:29 UTC. Jadi ritme 5 menit dipegang chain ini, schedule hanya cadangan.

Aturan dispatch (satu GET daftar run dipakai untuk keduanya):

* **Guard 1 — antrean**: lewati dispatch bila masih ada run workflow ini
  (cabang sama) yang ``queued``/``in_progress``/``waiting``. GitHub hanya
  menahan SATU run mengantre per group ``holder-scanner``; request ketiga
  membatalkan yang mengantre ("Canceling since a higher priority waiting
  request for holder-scanner exists");
* **Guard 2 — run kembar**: lewati dispatch HANYA bila ada run lain yang
  baru selesai dalam ``CHAIN_QUIET_SEC`` (default 240 s — WAJIB < kadens,
  kalau tidak rantai mematikan dirinya sendiri). Run serumit itu pasti
  sudah men-dispatch penerusnya sendiri, dan langkah ini selalu tidur
  sampai batas 5 menit berikutnya sehingga satu run minimal berumur
  ±320 detik — run yang baru selesai selalu lebih tua dari jendela, jadi
  rantai tidak bisa macet.
  Guard lama membandingkan umur run ``event=schedule`` dengan 900 detik dan
  menyimpulkan "schedule sehat" — itulah penyebab stall 2026-09-09: sekali
  schedule (yang telat berjam-jam itu) selesai, dispatch berikutnya
  dilewati, dan tidak ada lagi yang membangunkan pipeline.

Bila API GitHub error: **fail-open** (tetap dispatch). Run ganda tidak
berbahaya — :data:`scripts.scan_holders.MIN_RUN_GAP_SEC` sudah menyaring run
kedua dalam slot yang sama supaya keluar tanpa kerja; run yang terlewat
berarti lane LP buta selama berjam-jam.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
CADENCE_SEC = 5 * 60          # kadens target cron/chain
LEAD_SEC = 20                 # bangun sedikit setelah batas 5 menit
QUIET_SEC = 240               # jendela "run lain baru saja selesai"
ACTIVE_STATES = ("queued", "in_progress", "waiting")
TIMEOUT_SEC = 20
_NO_RETRY_STATUS = (400, 401, 404, 422)   # kesalahan permanen, bukan throttle


def _parse_ts(value):
    """``2026-09-09T16:40:24Z`` → epoch detik (0 bila tidak terbaca)."""
    if not value:
        return 0
    try:
        return int(dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=dt.timezone.utc).timestamp())
    except (TypeError, ValueError):
        return 0


def next_boundary_wait(now_ts: int, cadence: int = CADENCE_SEC,
                       lead: int = LEAD_SEC) -> int:
    """Detik sampai ``cadence`` berikutnya + ``lead`` (selalu ≥ 1).

    Bangun ±20 detik setelah batas 5 menit supaya run berikutnya mulai di
    fase yang sama tiap siklus; ``cadence``/``lead`` boleh diubah lewat CLI
    tanpa menyentuh YAML.
    """
    cadence = max(60, int(cadence))
    lead = max(0, int(lead))
    return max(1, cadence - (int(now_ts) % cadence) + lead)


def split_runs(runs, me_id, branch: str = "", now_ts: int = 0,
               quiet_sec: int = QUIET_SEC):
    """Pisahkan daftar run GitHub jadi (aktif, umur run selesai terbaru).

    ``runs`` = item ``workflow_runs`` dari API. Run dengan id ``me_id`` dan
    cabang lain ``branch`` diabaikan. Mengembalikan jumlah run yang masih
    hidup dan umur (detik) run ``completed`` terbaru — ``None`` bila tidak
    ada, supaya pemanggil bisa membedakan "tidak ada" dari "0 detik".
    """
    me = str(me_id or "")
    active = 0
    last_done = 0
    for run in runs or []:
        if str(run.get("id") or "") == me:
            continue
        if branch and str(run.get("head_branch") or "") != branch:
            continue
        if run.get("status") in ACTIVE_STATES:
            active += 1
        elif run.get("status") == "completed":
            last_done = max(last_done, _parse_ts(run.get("updated_at")))
    age = (int(now_ts) - last_done) if last_done else None
    return active, age


def should_dispatch(active: int, last_age, quiet_sec: int = QUIET_SEC):
    """Keputusan rantai: ``(bool dispatch, alasan)``.

    Dipisah dari I/O supaya tabel kasusnya bisa diuji offline — termasuk
    kasus 2026-09-09 (``active=0``, run schedule terakhir berumur 299 s)
    yang pada guard lama berarti "lewati" dan pipeline mati 4,5 jam.
    """
    if int(active) > 0:
        return False, f"{int(active)} run masih antre/berjalan"
    if last_age is not None and int(last_age) < int(quiet_sec):
        return False, (f"run lain selesai {int(last_age)}s lalu "
                       f"(< {int(quiet_sec)}s) — run itu yang merantai")
    detail = "tidak ada run lain" if last_age is None else \
        f"run terakhir selesai {int(last_age)}s lalu"
    return True, detail


def _request(url: str, token: str, *, method: str = "GET", body=None,
             attempts: int = 3, sleep=time.sleep):
    """Panggilan GitHub API dengan retry + backoff.

    Mengembalikan ``(status_code, payload)``; ``payload`` ``None`` bila
    semua percobaan gagal (dipanggil menanganinya sebagai fail-open).
    """
    data = None
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "wallet-depth-chain"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last = (0, None)
    for attempt in range(max(1, int(attempts))):
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method=method)
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                raw = resp.read()
                payload = json.loads(raw) if raw else {}
                return resp.status, payload
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:180]
            except Exception:  # noqa: BLE001
                pass
            last = (exc.code, detail)
            # 400/404/422 = permintaan salah (ref hilang, nama workflow
            # salah) — retry hanya memperlambat run. 403/429/5xx sering
            # berupa secondary rate limit yang hilang sendiri.
            if exc.code in _NO_RETRY_STATUS:
                return last
        except Exception as exc:  # noqa: BLE001  URLError, timeout, dll
            last = (0, f"{type(exc).__name__}: {exc}")
        if attempt + 1 < max(1, int(attempts)):
            backoff = 5 * (attempt + 1)
            print(f"WARN: {method} {url.split('/repos/')[-1]} gagal "
                  f"({last[0]} {str(last[1])[:120]}) — coba lagi "
                  f"{backoff}s lagi", file=sys.stderr)
            sleep(backoff)
    return last


def list_runs(repo: str, workflow: str, token: str, *, per_page: int = 50):
    """Daftar run terbaru workflow; ``None`` bila API tidak bisa dibaca."""
    url = (f"{API}/repos/{repo}/actions/workflows/{workflow}/runs"
           f"?per_page={int(per_page)}")
    status, payload = _request(url, token)
    if status != 200 or not isinstance(payload, dict):
        print(f"WARN: daftar run gagal (HTTP {status}: "
              f"{str(payload)[:150]}) — guard dilewati, dispatch tetap "
              "dicoba", file=sys.stderr)
        return None
    return payload.get("workflow_runs") or []


def dispatch_run(repo: str, workflow: str, ref: str, token: str, *,
                 attempts: int = 4, sleep=time.sleep) -> bool:
    """POST workflow_dispatch; ``True`` bila diterima (201/202/204)."""
    url = f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    status, _payload = _request(url, token, method="POST",
                               body={"ref": ref}, attempts=attempts,
                               sleep=sleep)
    if status in (201, 202, 204):
        return True
    print(f"WARN: dispatch ditolak (HTTP {status}: "
          f"{str(_payload)[:200]})", file=sys.stderr)
    return False


def chain_once(*, repo: str, workflow: str, ref: str, run_id: str,
               token: str, cadence: int, quiet_sec: int, lead: int,
               do_sleep=time.sleep, now=time.time, sleeper_ok=True) -> int:
    """Satu siklus rantai: tidur → evaluasi guard → dispatch.

    Return kode exit: 0 = dispatch terkirim atau dilewati dengan alasan
    guard; 1 = dispatch dicoba tapi gagal total (biar run ditandai merah,
    kegagalan rantai tidak boleh terbaca seperti "cron sehat").
    """
    wait = next_boundary_wait(int(now()), cadence, lead)
    print(f"Tidur {wait}s sampai batas {cadence // 60} menit berikutnya."
          + ("" if sleeper_ok else "  (--no-sleep: tidur dilewati)"))
    if sleeper_ok:
        do_sleep(wait)

    runs = list_runs(repo, workflow, token)
    active, age = (0, None)
    if runs is not None:
        active, age = split_runs(runs, run_id, branch=ref,
                                 now_ts=int(now()), quiet_sec=quiet_sec)
    go, reason = should_dispatch(active, age, quiet_sec)
    if not go:
        print(f"Dispatch dilewati — {reason}.")
        return 0
    if dispatch_run(repo, workflow, ref, token):
        print(f"Run berikutnya di-dispatch ({reason}).")
        return 0
    print("ERROR: rantai TERPUTUS — dispatch run berikutnya gagal setelah "
          "retry. Cron hanya akan bangkit lagi saat schedule GitHub "
          "menyala (bisa berjam-jam). Jalankan 'Run workflow' manual untuk "
          "menyambungkan kembali.", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch run cron berikutnya (rantai anti-throttle).")
    parser.add_argument("--workflow",
                        default=os.environ.get("CHAIN_WORKFLOW",
                                               "daily-effort.yml"),
                        help="nama berkas workflow di folder .github/workflows")
    parser.add_argument("--cadence", type=int,
                        default=int(os.environ.get("CHAIN_CADENCE_SEC")
                                    or CADENCE_SEC),
                        help=f"detik antar-run (default {CADENCE_SEC})")
    parser.add_argument("--quiet-sec", type=int,
                        default=int(os.environ.get("CHAIN_QUIET_SEC")
                                    or QUIET_SEC),
                        help=f"jendela run baru selesai (default {QUIET_SEC}, "
                             "WAJIB < --cadence)")
    parser.add_argument("--lead", type=int,
                        default=int(os.environ.get("CHAIN_LEAD_SEC")
                                    or LEAD_SEC),
                        help=f"detik setelah batas (default {LEAD_SEC})")
    parser.add_argument("--no-sleep", action="store_true",
                        help="langsung evaluasi (uji coba / trigger manual)")
    args = parser.parse_args(argv)

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    ref = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if not repo or not token:
        # Tidak di Actions / tanpa token: jangan gagal merah, tidak ada yang
        # bisa di-rantai. Perilaku sama seperti langkah ini di-lewati.
        print("Dispatch dilewati — GITHUB_REPOSITORY/GITHUB_TOKEN tidak "
              "tersedia (chain hanya jalan di GitHub Actions).")
        return 0
    if args.quiet_sec >= args.cadence:
        print(f"WARN: --quiet-sec {args.quiet_sec} ≥ --cadence {args.cadence} "
              "— rantai bisa mematikan dirinya sendiri; dipangkas ke "
              f"{max(0, args.cadence - 60)}s.", file=sys.stderr)
        args.quiet_sec = max(0, args.cadence - 60)

    return chain_once(repo=repo, workflow=args.workflow, ref=ref,
                      run_id=run_id, token=token, cadence=args.cadence,
                      quiet_sec=args.quiet_sec, lead=args.lead,
                      sleeper_ok=not args.no_sleep)


if __name__ == "__main__":
    raise SystemExit(main())
