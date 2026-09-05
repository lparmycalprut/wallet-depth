/**
 * Historical Dust % Market Cap Tracker
 * Simpan di cron/ dan jalankan via cron job (contoh: 0 * * * * node /path/to/historical_dust_tracker.js)
 * 
 * Catat % Market Cap dust ($0-$10) setiap jam
 */

const fs = require('fs');
const path = require('path');

// Path file database sederhana (JSON)
const DB_PATH = path.join(__dirname, 'dust_history.json');

// Inisialisasi DB jika belum ada
function initDB() {
  if (!fs.existsSync(DB_PATH)) {
    fs.writeFileSync(DB_PATH, JSON.stringify({ entries: [] }, null, 2));
  }
}

// Simpan data baru
function saveDustData(timestamp, dustPercentage) {
  const db = JSON.parse(fs.readFileSync(DB_PATH));
  
  db.entries.push({
    timestamp: timestamp.toISOString(),
    date: timestamp.toISOString().split('T')[0], // Format: YYYY-MM-DD
    time: timestamp.toISOString().split('T')[1].split('.')[0], // Format: HH:MM:SS
    dust_percentage: dustPercentage, // Nilai desimal (contoh: 0.59 untuk 0.59%)
    dust_percentage_display: `${dustPercentage.toFixed(2)}%` // Format untuk display
  });
  
  // Keep only last 30 days of data
  const thirtyDaysAgo = new Date(timestamp.getTime() - 30 * 24 * 60 * 60 * 1000);
  db.entries = db.entries.filter(entry => new Date(entry.timestamp) >= thirtyDaysAgo);
  
  fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2));
  console.log(`[${timestamp.toISOString()}] Saved dust % MCAP: ${dustPercentage.toFixed(2)}%`);
}

// Contoh: Ambil data dari API Helius atau fungsi yang sudah ada
// Ganti ini dengan logic asli dari cron job Anda
async function fetchCurrentDustPercentage() {
  // CONTOH: Ambil dari data yang sudah ada
  // Dalam data Anda: $0-$10: 0.59% Market Cap
  // Jika Anda punya fungsi untuk fetch data wallet, panggil di sini
  
  // Simulasi: Ambil dari file atau API
  // const response = await fetch('YOUR_HELIUS_API_ENDPOINT');
  // const data = await response.json();
  
  // Untuk sekarang, pakai nilai dari data snapshot Anda
  return 0.59; // 0.59% -> simpan sebagai 0.59 (bukan 0.0059)
}

// Main
async function main() {
  initDB();
  
  const now = new Date();
  const dustPercentage = await fetchCurrentDustPercentage();
  
  saveDustData(now, dustPercentage);
}

// Jalankan
main().catch(console.error);

// Export untuk testing
module.exports = { initDB, saveDustData, fetchCurrentDustPercentage };
