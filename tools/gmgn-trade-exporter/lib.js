/*
 * GMGN Trade Exporter — logika murni (tanpa DOM / chrome API).
 * Dipakai oleh popup.js di browser dan oleh lib.test.js di Node.
 *
 * Endpoint dan pola pagination mengikuti cvd.py di repo ini:
 *   GET https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}?limit=100&from=&to=&cursor=
 *   - `to` adalah batas atas EKSKLUSIF (detik Unix), data terurut terbaru dulu.
 *   - `from` tidak selalu dihormati, jadi filter waktu tetap dilakukan di sisi klien.
 *   - halaman berikutnya memakai `cursor` dari respons (atau kunci trade terakhir).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GmgnExport = api;
})(typeof self !== 'undefined' ? self : globalThis, function () {
  const WIB_OFFSET_SEC = 7 * 3600; // Asia/Jakarta, UTC+7, tanpa DST
  const TRADE_URL = 'https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}';
  const PAGE_LIMIT = 100;
  const CA_IN_URL_RE = /\/sol\/token\/(?:[^\/?#]*?_)?([1-9A-HJ-NP-Za-km-z]{32,44})(?=[\/?#]|$)/;
  const CA_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  const TX_KEYS = ['transaction_hash', 'tx_hash', 'txHash', 'signature', 'hash', 'tx', 'id'];

  // ---------- util waktu ----------

  /** Ambil CA Solana dari URL halaman token GMGN. Mengembalikan '' bila tidak ada. */
  function caFromUrl(url) {
    const m = String(url || '').match(CA_IN_URL_RE);
    return m ? m[1] : '';
  }

  function isValidCa(ca) {
    return CA_RE.test(String(ca || ''));
  }

  /** "2026-11-04T03:00" (dianggap WIB) -> detik Unix. NaN bila format salah. */
  function parseWibToEpochSec(text) {
    const m = String(text || '').trim()
      .match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (!m) return NaN;
    const ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
    return Math.floor(ms / 1000) - WIB_OFFSET_SEC;
  }

  /** Detik Unix -> "2026-11-04 03:00:00 WIB". */
  function formatWib(sec) {
    const d = new Date((sec + WIB_OFFSET_SEC) * 1000);
    return d.toISOString().slice(0, 19).replace('T', ' ') + ' WIB';
  }

  /** Rentang default: hari ini (WIB) jam fromHour s.d. toHour. */
  function wibDefaultRange(nowSec, fromHour = 3, toHour = 7) {
    const d = new Date((nowSec + WIB_OFFSET_SEC) * 1000);
    const pad = (n) => String(n).padStart(2, '0');
    const day = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
    return { from: `${day}T${pad(fromHour)}:00`, to: `${day}T${pad(toHour)}:00` };
  }

  /** Terima detik, milidetik, atau string ISO; kembalikan detik Unix (NaN bila gagal). */
  function toEpochSec(v) {
    if (v === undefined || v === null || v === '') return NaN;
    let n;
    if (typeof v === 'number') n = v;
    else if (/^\d+(\.\d+)?$/.test(String(v).trim())) n = Number(v);
    else n = Date.parse(String(v)) / 1000;
    if (!Number.isFinite(n) || n <= 0) return NaN;
    while (n > 1e10) n /= 1000; // ms / µs -> detik
    return Math.floor(n);
  }

  // ---------- parsing respons GMGN ----------

  /** Ambil nilai dari beberapa kandidat kunci (mendukung path bertitik, mis. "maker_info.address"). */
  function pick(obj, keys) {
    for (const key of keys) {
      let cur = obj;
      for (const part of key.split('.')) {
        cur = cur && typeof cur === 'object' ? cur[part] : undefined;
      }
      if (cur !== undefined && cur !== null && cur !== '') return cur;
    }
    return undefined;
  }

  function num(v) {
    const n = typeof v === 'number' ? v : parseFloat(v);
    return Number.isFinite(n) ? n : NaN;
  }

  /** Cari array trade di berbagai bentuk respons (sama dengan _find_trade_list di cvd.py). */
  function findTradeList(obj) {
    if (Array.isArray(obj)) return obj.filter((x) => x && typeof x === 'object');
    if (!obj || typeof obj !== 'object') return [];
    for (const k of ['trades', 'history', 'activities', 'items', 'list', 'rows', 'transactions', 'result', 'data']) {
      if (k in obj) {
        const found = findTradeList(obj[k]);
        if (found.length) return found;
      }
    }
    for (const v of Object.values(obj)) {
      const found = findTradeList(v);
      if (found.length) return found;
    }
    return [];
  }

  function findNextCursor(payload) {
    const c = pick(payload, ['data.next', 'data.next_cursor', 'data.nextCursor', 'data.cursor',
      'pagination.next', 'next', 'next_cursor', 'nextCursor', 'cursor']);
    return c === undefined ? null : String(c);
  }

  /** Lempar error bila GMGN membalas kode non-sukses di dalam JSON. */
  function assertPayloadOk(payload) {
    if (!payload || typeof payload !== 'object') return;
    const code = payload.code;
    if (code !== undefined && code !== null && code !== 0 && code !== '0' && code !== 'success') {
      const msg = payload.message || payload.msg || '';
      throw new Error(`GMGN code=${code} ${msg}`.trim());
    }
  }

  /** Ubah satu trade mentah GMGN menjadi baris yang seragam. Nama field mengikuti cvd.py. */
  function normalizeTrade(raw) {
    const tagLists = [pick(raw, ['maker_tags', 'makerTags']),
      pick(raw, ['maker_token_tags', 'makerTokenTags']),
      pick(raw, ['maker_event_tags', 'makerEventTags'])];
    const tags = [];
    for (const list of tagLists) if (Array.isArray(list)) tags.push(...list.map(String));
    const evRaw = String(pick(raw, ['event', 'side', 'action', 'trade_type']) || '').toLowerCase();
    return {
      ts: toEpochSec(pick(raw, ['timestamp', 'time', 'block_time', 'created_at'])),
      side: evRaw.includes('buy') ? 'buy' : evRaw.includes('sell') ? 'sell' : evRaw,
      usd: num(pick(raw, ['amount_usd', 'amountUSD', 'cost_usd', 'costUsd', 'usd'])),
      price: num(pick(raw, ['price_usd', 'priceUsd', 'price'])),
      tokenAmount: num(pick(raw, ['base_amount', 'baseAmount', 'token_amount', 'amount'])),
      quoteAmount: num(pick(raw, ['quote_amount', 'quoteAmount', 'sol_amount'])),
      wallet: String(pick(raw, ['maker', 'wallet', 'maker_info.address', 'address']) || ''),
      tx: String(pick(raw, TX_KEYS) || ''),
      tags: [...new Set(tags)].join('|'),
    };
  }

  // ---------- URL & pagination ----------

  function buildTradeUrl(ca, { fromSec, toSec, cursor, limit = PAGE_LIMIT, base = TRADE_URL } = {}) {
    const p = new URLSearchParams({
      from_app: 'gmgn', tz_name: 'Asia/Jakarta', tz_offset: '25200',
      app_lang: 'en-US', os: 'web', worker: '0', limit: String(limit),
    });
    if (fromSec != null) p.set('from', String(fromSec));
    if (toSec != null) p.set('to', String(toSec));
    if (cursor) p.set('cursor', String(cursor));
    return base.replace('{ca}', ca) + '?' + p.toString();
  }

  async function withRetry(fn, retries, sleep) {
    let delay = 1000;
    let last;
    for (let i = 0; i <= retries; i++) {
      try {
        return await fn();
      } catch (e) {
        last = e;
        if (i === retries) break;
        await sleep(delay);
        delay *= 2;
      }
    }
    throw last;
  }

  /**
   * Ambil semua trade dalam [fromSec, toSec) lewat pagination cursor.
   * fetchJson(url) harus mengembalikan JSON respons GMGN (atau melempar error).
   * Mengembalikan { trades (terurut naik), pages, complete, warning }.
   * complete = true bila sudah mencapai awal rentang atau data habis.
   */
  async function fetchTradeWindow(opts) {
    const {
      ca, fromSec, toSec, fetchJson,
      onProgress = () => {},
      sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
      pageDelayMs = 200, maxPages = 300, retries = 3,
    } = opts;
    if (!isValidCa(ca)) throw new Error('CA Solana tidak valid');
    if (!(fromSec < toSec)) throw new Error('rentang waktu tidak valid');

    const seen = new Set();
    const seenCursors = new Set();
    const trades = [];
    const pages = [];
    let cursor = null;
    let warning = '';
    let complete = false;
    let n = 0;

    for (;;) {
      if (n >= maxPages) { warning = `berhenti di batas ${maxPages} halaman`; break; }
      const url = buildTradeUrl(ca, { fromSec, toSec, cursor });
      let payload;
      try {
        payload = await withRetry(async () => {
          const j = await fetchJson(url);
          assertPayloadOk(j);
          return j;
        }, retries, sleep);
      } catch (e) {
        warning = `gagal di halaman ${n + 1}: ${e.message}`;
        break;
      }
      n++;
      pages.push({ url, payload });

      const rawList = findTradeList(payload);
      if (rawList.length === 0) { complete = true; break; }

      let oldest = Infinity;
      for (const raw of rawList) {
        const t = normalizeTrade(raw);
        if (!Number.isFinite(t.ts)) continue;
        oldest = Math.min(oldest, t.ts);
        if (t.ts < fromSec || t.ts >= toSec) continue;
        const key = t.tx || `${t.ts}|${t.wallet}|${t.side}|${t.tokenAmount}`;
        if (seen.has(key)) continue;
        seen.add(key);
        trades.push(t);
      }
      onProgress({ pages: n, trades: trades.length, oldest: Number.isFinite(oldest) ? oldest : null });

      if (oldest < fromSec) { complete = true; break; }

      let next = findNextCursor(payload);
      if (!next) {
        const lastTx = String(pick(rawList[rawList.length - 1], TX_KEYS) || '');
        if (rawList.length >= PAGE_LIMIT && lastTx) next = lastTx;
      }
      if (!next) {
        if (rawList.length < PAGE_LIMIT) complete = true;
        else warning = 'GMGN tidak memberi cursor; pagination berhenti';
        break;
      }
      if (seenCursors.has(next)) { warning = 'cursor GMGN berulang; pagination berhenti'; break; }
      seenCursors.add(next);
      cursor = next;
      await sleep(pageDelayMs);
    }

    trades.sort((a, b) => a.ts - b.ts);
    return { trades, pages, complete, warning };
  }

  // ---------- filter, ringkasan, CSV ----------

  /** side: 'all' | 'buy' | 'sell'. minUsd: 0 = tanpa filter. */
  function filterTrades(trades, { side = 'all', minUsd = 0 } = {}) {
    return trades.filter((t) =>
      (side === 'all' || t.side === side) &&
      (!(minUsd > 0) || (Number.isFinite(t.usd) && Math.abs(t.usd) >= minUsd)));
  }

  function summarize(trades) {
    const buys = trades.filter((t) => t.side === 'buy');
    const sells = trades.filter((t) => t.side === 'sell');
    const sum = (arr) => arr.reduce((s, t) => s + (Number.isFinite(t.usd) ? Math.abs(t.usd) : 0), 0);
    return {
      total: trades.length,
      buys: buys.length,
      sells: sells.length,
      buyUsd: sum(buys),
      sellUsd: sum(sells),
      buyWallets: new Set(buys.map((t) => t.wallet).filter(Boolean)).size,
    };
  }

  const CSV_HEADER = ['waktu_wib', 'unix_ts', 'side', 'usd', 'price_usd', 'token_amount',
    'quote_amount', 'wallet', 'tx_hash', 'tags'];

  function csvCell(v) {
    if (v === null || v === undefined) return '';
    if (typeof v === 'number' && !Number.isFinite(v)) return '';
    const s = String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  /** CSV dengan BOM UTF-8 supaya Excel membaca karakter dengan benar. */
  function toCsv(trades) {
    const lines = [CSV_HEADER.join(',')];
    for (const t of trades) {
      lines.push([formatWib(t.ts), t.ts, t.side, t.usd, t.price, t.tokenAmount,
        t.quoteAmount, t.wallet, t.tx, t.tags].map(csvCell).join(','));
    }
    return '\uFEFF' + lines.join('\r\n') + '\r\n';
  }

  return {
    WIB_OFFSET_SEC, TRADE_URL, PAGE_LIMIT,
    caFromUrl, isValidCa, parseWibToEpochSec, formatWib, wibDefaultRange, toEpochSec,
    pick, findTradeList, findNextCursor, assertPayloadOk, normalizeTrade,
    buildTradeUrl, withRetry, fetchTradeWindow,
    filterTrades, summarize, toCsv, CSV_HEADER,
  };
});
