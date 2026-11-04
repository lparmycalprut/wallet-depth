// Popup GMGN Trade Exporter. Logika inti ada di lib.js (GmgnExport).
const G = GmgnExport;
const el = (id) => document.getElementById(id);

let gmgnTab = null;
let lastPages = null;
let busy = false;

document.addEventListener('DOMContentLoaded', init);

async function init() {
  const def = G.wibDefaultRange(Date.now() / 1000);
  el('from').value = def.from;
  el('to').value = def.to;
  el('run').addEventListener('click', run);
  el('raw').addEventListener('click', downloadRaw);

  gmgnTab = await findGmgnTab();
  if (gmgnTab) {
    const ca = G.caFromUrl(gmgnTab.url);
    if (ca) el('ca').value = ca;
    setStatus(ca ? 'Tab GMGN terdeteksi. Siap diekspor.' :
      'Tab GMGN terdeteksi, tetapi CA tidak terbaca dari URL. Isi CA secara manual.');
  } else {
    setStatus('Buka halaman token di gmgn.ai (mis. gmgn.ai/sol/token/…), lalu buka ulang popup ini.');
  }
}

async function findGmgnTab() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active && /^https:\/\/gmgn\.ai\//.test(active.url || '')) return active;
  const tabs = await chrome.tabs.query({ url: 'https://gmgn.ai/*' });
  return tabs[0] || null;
}

/**
 * Jalankan fetch di konteks halaman gmgn.ai (world MAIN) supaya cookie dan
 * header browser ikut terkirim, sama seperti web client GMGN.
 */
async function fetchInPage(url) {
  if (!gmgnTab) throw new Error('tab GMGN tidak ditemukan');
  const [inj] = await chrome.scripting.executeScript({
    target: { tabId: gmgnTab.id },
    world: 'MAIN',
    func: pageFetchJson,
    args: [url],
  });
  const r = inj && inj.result;
  if (!r) throw new Error('tidak ada respons dari tab GMGN (tab mungkin sudah ditutup/berpindah halaman)');
  if (r.error) throw new Error(r.error);
  return r.json;
}

// PERHATIAN: fungsi ini dikirim ke halaman dan harus berdiri sendiri (tanpa referensi ke luar).
function pageFetchJson(url) {
  return fetch(url, { credentials: 'include', headers: { accept: 'application/json, text/plain, */*' } })
    .then(async (r) => {
      if (!r.ok) return { error: `HTTP ${r.status}` };
      try {
        return { json: await r.json() };
      } catch (e) {
        return { error: 'respons bukan JSON' };
      }
    })
    .catch((e) => ({ error: String(e) }));
}

async function run() {
  if (busy) return;
  const ca = el('ca').value.trim();
  const fromSec = G.parseWibToEpochSec(el('from').value);
  const toSec = G.parseWibToEpochSec(el('to').value);
  const side = el('side').value;
  const minUsd = Number(el('minUsd').value) || 0;

  if (!G.isValidCa(ca)) return setStatus('CA Solana tidak valid.');
  if (!(fromSec < toSec)) return setStatus('Rentang waktu tidak valid: "Dari" harus sebelum "Sampai".');
  if (!gmgnTab) return setStatus('Tab GMGN tidak ditemukan. Buka halaman token di gmgn.ai dulu.');

  busy = true;
  setBusy(true);
  el('summary').style.display = 'none';
  lastPages = null;
  try {
    setStatus('Mengambil data…');
    const res = await G.fetchTradeWindow({
      ca, fromSec, toSec, fetchJson: fetchInPage,
      onProgress: (p) => setStatus(
        `Halaman ${p.pages} · terkumpul ${p.trades} trade\n` +
        `paling lama: ${p.oldest ? G.formatWib(p.oldest) : '-'}`),
    });
    lastPages = res.pages;

    const rows = G.filterTrades(res.trades, { side, minUsd });
    const s = G.summarize(rows);
    const lines = [
      `Rentang: ${G.formatWib(fromSec)} → ${G.formatWib(toSec)}`,
      `Halaman diambil: ${res.pages.length}`,
      `Trade lolos filter: ${s.total} (buy ${s.buys}, sell ${s.sells})`,
      `Total buy USD: $${s.buyUsd.toFixed(2)} · wallet buy unik: ${s.buyWallets}`,
    ];
    if (!res.complete) lines.push('⚠ Data mungkin belum lengkap sampai awal rentang.');
    if (res.warning) lines.push(`⚠ ${res.warning}`);
    showSummary(lines.join('\n'));

    if (rows.length) {
      const name = `gmgn_${ca.slice(0, 8)}_${fileTag(fromSec)}_${fileTag(toSec)}.csv`;
      download(name, G.toCsv(rows), 'text/csv;charset=utf-8');
      setStatus(`Selesai. CSV ${rows.length} baris diunduh.`);
    } else {
      setStatus('Selesai. Tidak ada trade yang cocok dengan filter, CSV tidak dibuat.');
    }
    el('raw').disabled = false;
  } catch (e) {
    setStatus(`Error: ${e.message}`);
    if (lastPages) el('raw').disabled = false;
  } finally {
    busy = false;
    setBusy(false);
  }
}

function downloadRaw() {
  if (!lastPages) return;
  const body = JSON.stringify(lastPages.map((p) => ({ url: p.url, payload: p.payload })), null, 2);
  download(`gmgn_raw_${Date.now()}.json`, body, 'application/json');
}

function fileTag(sec) {
  return G.formatWib(sec).slice(0, 16).replace(/\D/g, '');
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function setStatus(text) {
  el('status').textContent = text;
}

function showSummary(text) {
  const box = el('summary');
  box.textContent = text;
  box.style.display = 'block';
}

function setBusy(on) {
  el('run').disabled = on;
  el('run').textContent = on ? 'Mengambil…' : 'Ambil & unduh CSV';
}
