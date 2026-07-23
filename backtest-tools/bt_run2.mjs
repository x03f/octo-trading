// Надёжный прогон: ждём РЕАЛЬНОГО завершения бэктеста (socket.io status=finished), потом отчёт.
import { chromium } from 'playwright-core';
const EXE = '/root/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome';
const BASE = 'http://127.0.0.1:5002';
const DATA_FILE = process.argv[2];
const SOURCE = process.argv[3] || 'octobot_backtest';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox','--disable-gpu'] });
try {
  const page = await browser.newPage();
  await page.goto(`${BASE}/backtesting`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  // персистентный сокет статуса
  const hasIo = await page.evaluate(() => typeof io !== 'undefined');
  if (!hasIo) { console.log(JSON.stringify({error:'no socket.io on page'})); process.exit(0); }
  await page.evaluate(() => {
    window.__bt = null;
    const s = io('/backtesting');
    s.on('backtesting_status', d => { window.__bt = d; });
    setInterval(() => s.emit('backtesting_status'), 2000);
  });

  const startResp = await page.request.post(
    `${BASE}/backtesting?action_type=start_backtesting&source=${SOURCE}`,
    { data: { files: [DATA_FILE], enable_logs: false }, timeout: 60000 });
  if (startResp.status() !== 200) {
    console.log(JSON.stringify({ error: `start ${startResp.status()}: ${(await startResp.text()).slice(0,150)}` }));
    process.exit(0);
  }

  // ждём finished (до 25 мин)
  let st = null;
  for (let i = 0; i < 500; i++) {
    await sleep(3000);
    st = await page.evaluate(() => window.__bt);
    if (st && st.status === 'finished') break;
    if (i % 20 === 0 && st) process.stderr.write(`  [${st.status} ${Math.round(st.progress||0)}% err:${st.errors||0}]\n`);
  }
  if (!st || st.status !== 'finished') { console.log(JSON.stringify({ error: `not finished: ${st?st.status:'null'}` })); process.exit(0); }

  // отчёт — один раз, после завершения
  await sleep(2000);
  const r = await page.request.get(`${BASE}/backtesting?update_type=backtesting_report&source=${SOURCE}`, { timeout: 30000 });
  let j = {}; try { j = await r.json(); } catch {}
  const rep = j.report || {}; const br = rep.bot_report || {};
  const prof = br.profitability || {}; const mkt = br.market_average_profitability || {};
  const ex = Object.keys(prof)[0];
  const endp = (br.end_portfolio && ex && br.end_portfolio[ex]) || {};
  console.log(JSON.stringify({
    profitability_pct: ex ? prof[ex] : null,
    market_pct: ex ? mkt[ex] : null,
    trading_mode: br.trading_mode || null,
    trades: Array.isArray(j.trades) ? j.trades.length : null,
    end_usdt: (endp.USDT && endp.USDT.total) ?? null,
    errors: rep.errors_count ?? null,
    status_final: st.status,
  }));
} finally { await browser.close(); }
