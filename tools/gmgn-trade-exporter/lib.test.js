// Jalankan: node --test tools/gmgn-trade-exporter/lib.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const G = require('./lib.js');

const FROM = 1793736000; // 2026-11-04 03:00 WIB
const TO = 1793750400;   // 2026-11-04 07:00 WIB

/** Simulasi endpoint GMGN: data terurut terbaru dulu, `to` eksklusif, halaman = limit. */
function mockGmgn(all, { useNext = true, failFirst = 0 } = {}) {
  let failsLeft = failFirst;
  const calls = [];
  const fetchJson = async (url) => {
    calls.push(url);
    if (failsLeft > 0) { failsLeft--; throw new Error('network down'); }
    const u = new URL(url);
    const to = Number(u.searchParams.get('to'));
    const cursor = u.searchParams.get('cursor');
    const limit = Number(u.searchParams.get('limit'));
    let start;
    if (cursor === null) start = all.findIndex((t) => t.timestamp < to);
    else if (/^\d+$/.test(cursor)) start = Number(cursor);
    else start = all.findIndex((t) => t.tx_hash === cursor) + 1;
    if (start < 0) start = all.length;
    const page = all.slice(start, start + limit);
    const more = start + limit < all.length;
    const data = { history: page };
    if (useNext && more) data.next = String(start + limit);
    return { code: 0, msg: 'success', data };
  };
  return { fetchJson, calls };
}

function makeTrades() {
  // 260 trade, tiga per detik setiap 100 detik, terurut terbaru dulu.
  const out = [];
  for (let i = 0; i < 260; i++) {
    out.push({
      timestamp: 1793734000 + Math.floor(i / 3) * 100,
      tx_hash: `TX${i}`,
      event: i % 2 ? 'buy' : 'sell',
      maker: `W${i % 17}`,
      amount_usd: 50 + i,
      quote_amount: 0.5,
      base_amount: 1000 + i,
      price_usd: 0.00002,
      maker_tags: i % 4 === 0 ? ['bundler'] : [],
    });
  }
  return out.reverse();
}

test('waktu WIB: rentang 03:00–07:00 cocok dengan epoch yang dipakai di repo', () => {
  assert.equal(G.parseWibToEpochSec('2026-11-04T03:00'), FROM);
  assert.equal(G.parseWibToEpochSec('2026-11-04T07:00'), TO);
  assert.equal(G.formatWib(FROM), '2026-11-04 03:00:00 WIB');
  assert.ok(Number.isNaN(G.parseWibToEpochSec('04-11-2026 03:00')));
});

test('wibDefaultRange memakai tanggal WIB, bukan UTC', () => {
  // 2026-11-03 20:30 UTC = 2026-11-04 03:30 WIB
  const now = Date.UTC(2026, 10, 3, 20, 30) / 1000;
  assert.deepEqual(G.wibDefaultRange(now), { from: '2026-11-04T03:00', to: '2026-11-04T07:00' });
});

test('caFromUrl mengambil CA dari URL token GMGN', () => {
  const ca = '5ubruMYp' + 'a'.repeat(36);
  assert.equal(G.caFromUrl(`https://gmgn.ai/sol/token/${ca}`), ca);
  assert.equal(G.caFromUrl(`https://gmgn.ai/sol/token/pump_${ca}?chain=sol`), ca);
  assert.equal(G.caFromUrl('https://gmgn.ai/sol/address/abc'), '');
  assert.equal(G.isValidCa(ca), true);
  assert.equal(G.isValidCa('0OIl'), false);
});

test('toEpochSec menerima detik, milidetik, dan ISO', () => {
  assert.equal(G.toEpochSec(1793740000), 1793740000);
  assert.equal(G.toEpochSec(1793740000123), 1793740000);
  assert.equal(G.toEpochSec('2026-11-04T03:00:00Z'), Date.UTC(2026, 10, 4, 3) / 1000);
  assert.ok(Number.isNaN(G.toEpochSec(undefined)));
});

test('normalizeTrade memetakan field GMGN ke baris seragam', () => {
  const t = G.normalizeTrade({
    event: 'buy', amount_usd: 150.5, timestamp: 1793740000000, maker: 'W1',
    tx_hash: 'TX1', quote_amount: 1.2, base_amount: 9000, price_usd: 0.0000281,
    maker_tags: ['bundler'], maker_token_tags: ['top_holder', 'bundler'],
  });
  assert.equal(t.side, 'buy');
  assert.equal(t.usd, 150.5);
  assert.equal(t.ts, 1793740000);
  assert.equal(t.wallet, 'W1');
  assert.equal(t.tx, 'TX1');
  assert.equal(t.tags, 'bundler|top_holder');
  assert.equal(G.normalizeTrade({ side: 'SELL', maker_info: { address: 'W2' } }).side, 'sell');
  assert.equal(G.normalizeTrade({ side: 'SELL', maker_info: { address: 'W2' } }).wallet, 'W2');
});

test('findTradeList mengenali beberapa bentuk respons', () => {
  const trade = { tx_hash: 'X' };
  assert.equal(G.findTradeList({ data: { history: [trade] } }).length, 1);
  assert.equal(G.findTradeList({ data: { list: [trade, trade] } }).length, 2);
  assert.equal(G.findTradeList([trade]).length, 1);
  assert.equal(G.findTradeList({ data: { data: { trades: [trade] } } }).length, 1);
  assert.equal(G.findTradeList({ data: { history: [] } }).length, 0);
});

test('fetchTradeWindow: semua trade dalam rentang diambil tepat sekali (cursor = next)', async () => {
  const all = makeTrades();
  const { fetchJson, calls } = mockGmgn(all);
  const res = await G.fetchTradeWindow({
    ca: '5ubruMYp' + 'a'.repeat(36), fromSec: FROM, toSec: TO - 10000,
    fetchJson, sleep: async () => {}, pageDelayMs: 0,
  });
  const expected = all.filter((t) => t.timestamp >= FROM && t.timestamp < TO - 10000)
    .map((t) => t.tx_hash).sort();
  const got = res.trades.map((t) => t.tx).sort();
  assert.equal(new Set(got).size, got.length, 'tidak ada duplikat');
  assert.deepEqual(got, expected);
  assert.equal(res.complete, true);
  assert.equal(res.warning, '');
  assert.ok(calls.length > 1, 'harus lebih dari satu halaman');
  // hasil terurut naik
  for (let i = 1; i < res.trades.length; i++) assert.ok(res.trades[i - 1].ts <= res.trades[i].ts);
});

test('fetchTradeWindow: batas atas eksklusif dan tie di batas tidak ikut', async () => {
  const all = makeTrades();
  const { fetchJson } = mockGmgn(all);
  const toSec = 1793734000 + 60 * 100; // ada trade tepat di detik ini
  const res = await G.fetchTradeWindow({
    ca: '5ubruMYp' + 'a'.repeat(36), fromSec: 1793734000 + 20 * 100, toSec,
    fetchJson, sleep: async () => {}, pageDelayMs: 0,
  });
  assert.ok(res.trades.every((t) => t.ts >= 1793734000 + 2000 && t.ts < toSec));
  const expectedCount = all.filter((t) => t.timestamp >= 1793736000 && t.timestamp < toSec).length;
  assert.equal(res.trades.length, expectedCount);
});

test('fetchTradeWindow: fallback cursor = tx terakhir bila next tidak ada', async () => {
  const all = makeTrades();
  const { fetchJson } = mockGmgn(all, { useNext: false });
  const res = await G.fetchTradeWindow({
    ca: '5ubruMYp' + 'a'.repeat(36), fromSec: FROM, toSec: TO,
    fetchJson, sleep: async () => {}, pageDelayMs: 0,
  });
  const expected = all.filter((t) => t.timestamp >= FROM && t.timestamp < TO).length;
  assert.equal(res.trades.length, expected);
  assert.equal(new Set(res.trades.map((t) => t.tx)).size, expected);
});

test('fetchTradeWindow: retry saat jaringan gagal sementara', async () => {
  const all = makeTrades();
  const { fetchJson, calls } = mockGmgn(all, { failFirst: 2 });
  const sleeps = [];
  const res = await G.fetchTradeWindow({
    ca: '5ubruMYp' + 'a'.repeat(36), fromSec: FROM, toSec: TO,
    fetchJson, sleep: async (ms) => { sleeps.push(ms); }, pageDelayMs: 0,
  });
  assert.equal(res.warning, '');
  assert.deepEqual(sleeps.slice(0, 2), [1000, 2000]);
  assert.ok(calls.length >= 3);
});

test('fetchTradeWindow: kode error GMGN menghasilkan peringatan, bukan hasil palsu', async () => {
  const fetchJson = async () => ({ code: 40000, message: 'bad request' });
  const res = await G.fetchTradeWindow({
    ca: '5ubruMYp' + 'a'.repeat(36), fromSec: FROM, toSec: TO,
    fetchJson, sleep: async () => {}, pageDelayMs: 0, retries: 1,
  });
  assert.equal(res.trades.length, 0);
  assert.equal(res.complete, false);
  assert.match(res.warning, /gagal di halaman 1: GMGN code=40000/);
});

test('fetchTradeWindow: maxPages membatasi dan memberi peringatan', async () => {
  const all = makeTrades();
  const { fetchJson } = mockGmgn(all);
  const res = await G.fetchTradeWindow({
    ca: '5ubruMYp' + 'a'.repeat(36), fromSec: 0, toSec: 1793800000,
    fetchJson, sleep: async () => {}, pageDelayMs: 0, maxPages: 2,
  });
  assert.equal(res.pages.length, 2);
  assert.match(res.warning, /batas 2 halaman/);
});

test('filterTrades: side dan minimal USD (nilai absolut)', () => {
  const trades = [
    { side: 'buy', usd: 150 }, { side: 'buy', usd: 50 },
    { side: 'sell', usd: -200 }, { side: 'sell', usd: NaN },
  ];
  assert.equal(G.filterTrades(trades).length, 4);
  assert.equal(G.filterTrades(trades, { side: 'buy' }).length, 2);
  assert.deepEqual(G.filterTrades(trades, { side: 'all', minUsd: 100 }).map((t) => t.usd), [150, -200]);
  assert.equal(G.filterTrades(trades, { side: 'sell', minUsd: 100 }).length, 1);
});

test('toCsv: BOM, header, dan quoting koma/kutip', () => {
  const csv = G.toCsv([{
    ts: FROM, side: 'buy', usd: 187.4, price: 0.00002, tokenAmount: 9000, quoteAmount: 1.1,
    wallet: 'W1', tx: 'TX,1"x', tags: 'bundler|top_holder',
  }]);
  assert.equal(csv.charCodeAt(0), 0xfeff);
  const lines = csv.slice(1).trimEnd().split('\r\n');
  assert.equal(lines[0], G.CSV_HEADER.join(','));
  assert.equal(lines[1], `2026-11-04 03:00:00 WIB,${FROM},buy,187.4,0.00002,9000,1.1,W1,"TX,1""x",bundler|top_holder`);
});

test('summarize menghitung buy/sell dan wallet unik', () => {
  const s = G.summarize([
    { side: 'buy', usd: 100, wallet: 'A' }, { side: 'buy', usd: 200, wallet: 'A' },
    { side: 'sell', usd: -50, wallet: 'B' },
  ]);
  assert.deepEqual(s, { total: 3, buys: 2, sells: 1, buyUsd: 300, sellUsd: 50, buyWallets: 1 });
});

test('buildTradeUrl menyertakan from/to/cursor dan zona waktu', () => {
  const url = G.buildTradeUrl('CA1', { fromSec: FROM, toSec: TO, cursor: 'abc' });
  const u = new URL(url);
  assert.equal(u.origin + u.pathname, 'https://gmgn.ai/vas/api/v1/token_trades/sol/CA1');
  assert.equal(u.searchParams.get('from'), String(FROM));
  assert.equal(u.searchParams.get('to'), String(TO));
  assert.equal(u.searchParams.get('cursor'), 'abc');
  assert.equal(u.searchParams.get('tz_name'), 'Asia/Jakarta');
  assert.equal(u.searchParams.get('limit'), '100');
});
