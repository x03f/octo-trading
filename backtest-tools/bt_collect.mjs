import { chromium } from 'playwright-core';
const EXE = '/root/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome';
const BASE = 'http://127.0.0.1:5002';
const TOP20 = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT","DOGE/USDT","ADA/USDT",
  "TRX/USDT","LINK/USDT","AVAX/USDT","DOT/USDT","LTC/USDT","BCH/USDT","XLM/USDT",
  "HBAR/USDT","SUI/USDT","NEAR/USDT","UNI/USDT","APT/USDT","ATOM/USDT"];
const now = Date.now();
const start = now - 183*24*3600*1000;   // ~6 месяцев

const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox','--disable-gpu'] });
try {
  const page = await browser.newPage();
  await page.goto(`${BASE}/backtesting`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  const resp = await page.request.post(`${BASE}/data_collector?action_type=start_collector`, {
    data: { exchange: "binance", symbols: TOP20, time_frames: ["1h","1d"],
            startTimestamp: start, endTimestamp: now },
    headers: { 'Content-Type': 'application/json' },
    timeout: 60000,
  });
  console.log('collect POST status:', resp.status());
  console.log('body:', (await resp.text()).slice(0, 300));
} finally { await browser.close(); }
