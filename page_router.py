# -*- coding: utf-8 -*-
"""Router deep-link ``?mint=…`` / ``?page=…`` untuk app multipage ``pages/``.

Streamlit melayani halaman lewat **slug** hasil pembersihan nama file
(``pages/5_🧮_Holder.py`` → ``/Holder``), bukan lewat path file. Tautan lama
di dashboard ini memakai ``pages/5_🧮_Holder.py?mint=…``; path itu tidak cocok
dengan slug mana pun, jadi Streamlit menjalankan halaman utama (``app.py``).
Modul ini adalah jaring pengamannya: selama **halaman utama** yang berjalan dan
URL membawa token, kita ``st.switch_page`` ke halaman yang dimaksud dengan
``mint`` tetap terbawa — tautan yang sudah tersebar (chat, bookmark) tetap
berfungsi, begitu pula URL yang salah kapitalisasi atau memakai path file.

Aturan:

* ``?mint=<ca>`` (atau ``ca`` / ``token`` / ``address``) → halaman Holder
  Analytic; ``?page=cvd`` memindahkannya ke CVD.
* ``?page=<slug|angka|nama file|path>`` tanpa token → pindah halaman saja.
* Nilai ``mint`` wajib lolos format address (base58 Solana atau ``0x``+40 hex
  Robinhood Chain). Sampah tidak pernah memicu navigasi, jadi parameter lain
  yang kebetulan bernama sama dari widget/URL pihak luar tidak membajak app.
* Sekali per (halaman, mint) per sesi — penanda di ``st.session_state``
  mencegah loop ketika user sengaja kembali ke dashboard membawa ``?mint=``.

Murni kalkulasi: :func:`resolve` bisa diuji tanpa Streamlit; :func:`apply`
adalah satu-satunya bagian yang menyentuh ``st``.
"""
from __future__ import annotations

import os
import re

from links import page_url_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = os.path.join(BASE_DIR, "pages")

#: Halaman tujuan bila URL hanya membawa token (tombol 🧮 memakai bentuk ini).
DEFAULT_PAGE = "holder"

#: Kunci query yang boleh berisi contract address, urut prioritas.
MINT_KEYS = ("mint", "ca", "token", "address")

#: Kunci query yang memilih halaman tujuan.
PAGE_KEYS = ("page", "p", "target", "view")

#: Nilai ``page`` yang berarti "tetap di halaman utama" (tidak di-router).
MAIN_PAGE_VALUES = {"", "main", "home", "dashboard", "index", "app", "0"}

#: Alias tambahan di luar slug/nama file (slug sudah dihitung otomatis dari
#: isi folder ``pages/``; ini sekadar toleransi ejaan).
EXTRA_ALIASES = {
    "analytic": "holder",
    "analytica": "holder",
    "holderanalytic": "holder",
    "dust": "holder",
    "akumulasi": "deteksi_akumulasi",
    "deteksiakumulasi": "deteksi_akumulasi",
    "deteksi-akumulasi": "deteksi_akumulasi",
    "accumulation": "deteksi_akumulasi",
    "prepump": "pre-pump",
    "pre_pump": "pre-pump",
    "prepump-screener": "pre-pump",
}

SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_CA_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

#: Penanda sesi: deep link ini sudah pernah diikuti (mencegah loop redirect).
ROUTED_KEY = "_deep_link_routed"


def is_valid_ca(value) -> bool:
    """True bila string adalah contract address Solana atau Robinhood Chain."""
    addr = str(value or "").strip()
    return bool(SOLANA_CA_RE.fullmatch(addr) or EVM_CA_RE.fullmatch(addr))


def _first_value(query_params, keys) -> str:
    """Ambil nilai pertama yang terisi dari ``keys`` (list → elemen terakhir).

    ``st.query_params`` bisa mengembalikan list untuk kunci yang diulang;
    ``?mint=…&mint=…`` berarti nilai terakhir yang dipakai (sama seperti
    perilaku ``st.query_params[key]`` di Streamlit).
    """
    for key in keys:
        try:
            raw = query_params.get(key)
        except Exception:  # noqa: BLE001 - mapping asing tanpa .get
            try:
                raw = query_params[key]
            except Exception:  # noqa: BLE001
                raw = None
        if isinstance(raw, (list, tuple)):
            raw = raw[-1] if len(raw) else ""
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def page_aliases() -> dict[str, str]:
    """Peta ``alias (lowercase) -> path halaman relatif dari app utama``.

    Dibangun dari folder ``pages/`` supaya tetap benar kalau file diganti
    nama: slug URL (``Holder``), nama file tanpa ``.py`` (``5_🧮_Holder``),
    dan prefiks nomornya (``5``) semuanya ikut terdaftar.
    """
    aliases: dict[str, str] = {}
    try:
        names = sorted(name for name in os.listdir(PAGES_DIR)
                       if name.endswith(".py") and not name.startswith("."))
    except OSError:  # pragma: no cover - folder pages selalu ada di repo
        names = []
    for name in names:
        rel = f"pages/{name}"
        stem = name[:-3]
        for candidate in (page_url_path(name), stem):
            key = str(candidate or "").strip().lower()
            if key:
                aliases.setdefault(key, rel)
        number = re.match(r"([0-9]+)", stem)
        if number:
            aliases.setdefault(number.group(1), rel)
    return aliases


def known_pages() -> dict[str, str]:
    """Alias halaman + :data:`EXTRA_ALIASES` yang sudah diresolusi."""
    aliases = page_aliases()
    for alias, target in EXTRA_ALIASES.items():
        rel = aliases.get(target)
        if rel:
            aliases.setdefault(alias, rel)
    return aliases


def normalize_page_value(value) -> str:
    """Kecilkan + buang path/``.py`` agar ``pages/5_🧮_Holder.py`` ≙ ``holder``."""
    text = str(value or "").strip().lower().replace("\\", "/")
    if not text:
        return ""
    text = text.rsplit("/", 1)[-1]
    if text.endswith(".py"):
        text = text[:-3]
    return text.strip("/ ")


def resolve_page(value, aliases: dict[str, str] | None = None) -> str:
    """Path relatif halaman untuk satu nilai ``page`` (``""`` = tidak kenal)."""
    known = aliases if aliases is not None else known_pages()
    key = normalize_page_value(value)
    if not key or key in MAIN_PAGE_VALUES:
        return ""
    if key in known:
        return known[key]
    # Slug boleh mengandung underscore; user sering menulis spasi/hyphen.
    for variant in (key.replace("-", "_"), key.replace("_", "-"),
                    re.sub(r"[-_\s]", "", key)):
        if variant in known:
            return known[variant]
    return ""


def resolve(query_params) -> dict:
    """Resolusi deep link → ``{}`` (tidak ada yang harus di-router).

    Return ``{"page": <path relatif>, "mint": <ca>|None,
    "params": {…untuk st.switch_page…}, "requested": <nilai page mentah>}``.
    """
    if not query_params:
        return {}
    try:
        items = dict(query_params)
    except Exception:  # noqa: BLE001 - mapping/objek aneh: pakai .get saja
        items = {}
    aliases = known_pages()
    mint = ""
    raw_mint = _first_value(items, MINT_KEYS)
    if is_valid_ca(raw_mint):
        mint = raw_mint
    requested = _first_value(items, PAGE_KEYS)
    page = resolve_page(requested, aliases) if requested else ""
    if not page and mint:
        # Hanya token → halaman Holder (infonya tombol 🧮 di semua card).
        page = aliases.get(DEFAULT_PAGE, "")
    if not page:
        return {}
    params = {"mint": mint} if mint else {}
    return {"page": page, "mint": mint or None, "params": params,
            "requested": requested or None}


def apply() -> dict:
    """Router untuk halaman utama; kembalikan hasil :func:`resolve` yang diikuti.

    Dipanggil selagi belum ada output di ``app.py`` supaya ``st.switch_page``
    (yang menghentikan run ini) tidak meninggalkan paruh halaman yang
    ter-render. Return ``{}`` bila tidak ada yang di-router.
    """
    import streamlit as st

    try:
        query_params = st.query_params.to_dict()
    except Exception:  # noqa: BLE001 - di luar script run (import/skrip biasa)
        return {}
    target = resolve(query_params)
    if not target:
        return {}
    marker = (target["page"], target.get("mint"))
    try:
        if st.session_state.get(ROUTED_KEY) == marker:
            # Deep link yang sama sudah pernah diikuti sesi ini: biarkan user
            # membaca dashboard (navigasi manual tidak boleh dipantulkan).
            return {}
        st.session_state[ROUTED_KEY] = marker
    except Exception:  # noqa: BLE001 - session_state absent → tetap router
        pass
    st.switch_page(target["page"], query_params=target["params"])
    return target
