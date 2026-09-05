/**
 * Simple Express Server untuk serve dust chart
 * Jalankan: node server.js
 * 
 * Chart akan tersedia di: http://localhost:3000/dust-chart
 * Data JSON: http://localhost:3000/api/dust-history
 */

const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// API: Get dust history data
app.get('/api/dust-history', (req, res) => {
    const dbPath = path.join(__dirname, 'dust_history.json');
    
    if (fs.existsSync(dbPath)) {
        const data = JSON.parse(fs.readFileSync(dbPath));
        res.json(data);
    } else {
        res.json({ entries: [] });
    }
});

// API: Get latest dust percentage
app.get('/api/dust-latest', (req, res) => {
    const dbPath = path.join(__dirname, 'dust_history.json');
    
    if (fs.existsSync(dbPath)) {
        const data = JSON.parse(fs.readFileSync(dbPath));
        if (data.entries && data.entries.length > 0) {
            const latest = data.entries[data.entries.length - 1];
            res.json(latest);
        } else {
            res.json({ dust_percentage: 0, dust_percentage_display: '0%' });
        }
    } else {
        res.json({ dust_percentage: 0, dust_percentage_display: '0%' });
    }
});

// Serve chart HTML
app.get('/dust-chart', (req, res) => {
    res.sendFile(path.join(__dirname, 'dust_chart.html'));
});

// Root redirect
app.get('/', (req, res) => {
    res.redirect('/dust-chart');
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`✅ Server running on http://localhost:${PORT}`);
    console.log(`📊 Chart: http://localhost:${PORT}/dust-chart`);
    console.log(`📋 API: http://localhost:${PORT}/api/dust-history`);
});

module.exports = app;
