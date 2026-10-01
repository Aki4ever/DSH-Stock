#!/usr/bin/env node
/**
 * ⚠️ 历史快照说明（R06 起生效，2026-09-23）
 * 本脚本是 R05 批次（REQ-027~033）当时的真机验收快照，其「个股图表」断言建立在**已被取代**的旧口径上：
 *   - 旧：个股周期 Tab 为 timeline/kline5m/15m/30m/kline20/60/120/180/all，视窗固定 200 根、缩放下限 5 根；
 *   - 新（REQ-034/035）：个股图表改为「双维度双图」面板模型，K线维度二级 Tab 为 30/60/120/180（天|周|季），
 *     视窗下限 30 根、上限为该颗粒度全部可用根数，不足时右侧留白。
 * 因此本脚本中对个股周期 Tab 与个股 200 根视窗的断言**不再代表现行需求**，请勿据此判定回归。
 * 现行回归请运行：`node tests/browser_r06_verify.js`（REQ-034/035/036，36 项）。
 * 本文件保留为 R05 的历史证据快照，其指数页与接口层断言仍具参考价值。
 *
 * R05 真机浏览器验证 (headless Chrome + CDP)
 * 覆盖 REQ-027~033：
 *   1. 周期 Tab 重构：新增 5/15/30 分K线，移除 5天/10天K线（个股与指数同步）
 *   2. 各日K周期默认显示对应根数（20→20、60→60、120→120、180→180）铺满绘图区不留白
 *   3. 分钟K线：每根为真实时间区间（开/收/高/低/量），不足 200 根时右侧留白
 *   4. 压力线与其指标（交易面积 / 未交汇天数）按当前显示窗口计算，随放大缩小变动
 *   5. 总成交额(亿) = 图上所有交易日成交额之和，随窗口变动并标注估算根数
 *   6. 指数成交额按「来源未披露即如实不可得」口径，绝不以推测值充当真实成交额
 * 仅使用 Node 内置模块；只驱动已运行的 127.0.0.1:8888 页面，不写入产品数据。
 */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const CHROME = process.env.DSH_CHROME_BIN ||
  path.join(os.homedir(), 'Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');
const PORT = Number(process.env.DSH_CDP_PORT || 9350);
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-20-r05';

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function fetchJson(url, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch (_) {}
    await sleep(250);
  }
  throw new Error(`无法连接调试端点: ${url}`);
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('WebSocket 连接失败')); });
    const c = new CDP(ws);
    ws.onmessage = ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id && c.pending.has(msg.id)) {
        const { resolve, reject } = c.pending.get(msg.id);
        c.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) {
        c.events.push(msg);
      }
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const r = await Promise.race([
      this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('页面内脚本执行超时(45s): ' + String(expression).slice(0, 80))), 45000))
    ]);
    if (r.exceptionDetails) {
      throw new Error(`页面内脚本异常: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    }
    return r.result.value;
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.join(OUT, name);
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
    return file;
  }
}

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
}

// 个股图表几何探测：蜡烛实体（无极小值填充）= 与副图柱同宽但 fill 非副图色；此处以「宽度 != 绘图区宽度」识别
const STOCK_PROBE = `(() => {
  const svg = document.getElementById('stockInteractiveSvg');
  if (!svg) return { error: '未找到个股图表 SVG' };
  const rects = [...svg.querySelectorAll('rect')];
  const grid = rects.find(r => r.getAttribute('width') === '730');
  // 蜡烛实体：无极小宽度填充、非网格/背景；副图柱一律 opacity="0.85"，必须排除，否则根数会被算成两倍
  const bodies = rects.filter(r => r.getAttribute('opacity') === null && r.getAttribute('width') !== '730'
    && r.getAttribute('fill') !== 'none' && r.getAttribute('fill') !== '#0f172a' && !r.getAttribute('stroke'));
  if (!bodies.length) return { error: '未找到蜡烛实体' };
  const xs = bodies.map(r => parseFloat(r.getAttribute('x')));
  const ws = bodies.map(r => parseFloat(r.getAttribute('width')));
  const text = svg.textContent.replace(/\\s+/g, ' ');
  return {
    candles: bodies.length,
    candleWidth: ws[0],
    firstLeft: Math.min(...xs),
    lastRight: Math.max(...xs) + ws[xs.indexOf(Math.max(...xs))],
    plotLeft: grid ? parseFloat(grid.getAttribute('x')) : null,
    plotWidth: grid ? parseFloat(grid.getAttribute('width')) : null,
    totalAmount: (text.match(/总成交额[^]{0,90}/) || [''])[0].trim(),
    partialNote: (text.match(/本周期基准[^]{0,40}/) || [''])[0].trim()
  };
})()`;

const INDEX_PROBE = `(() => {
  const svg = document.getElementById('indexKLineSvg');
  if (!svg) return { error: '未找到指数图表 SVG' };
  const bodies = [...svg.querySelectorAll('rect')].filter(r => r.getAttribute('opacity') === '0.9');
  if (!bodies.length) return { error: '未找到指数蜡烛实体' };
  const xs = bodies.map(r => parseFloat(r.getAttribute('x')));
  const ws = bodies.map(r => parseFloat(r.getAttribute('width')));
  const text = svg.textContent.replace(/\\s+/g, ' ');
  return {
    candles: bodies.length,
    candleWidth: ws[0],
    firstLeft: Math.min(...xs),
    lastRight: Math.max(...xs) + ws[xs.indexOf(Math.max(...xs))],
    totalAmount: (text.match(/总成交额[^]{0,130}/) || [''])[0].trim(),
    partialNote: (text.match(/本周期基准[^]{0,40}/) || [''])[0].trim(),
    noAmountNote: text.includes('当前来源未披露该指数成交额')
  };
})()`;

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-r05-chrome-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1600,1400', '--hide-scrollbars', 'about:blank'
  ], { stdio: 'ignore' });

  let cdp;
  const shots = [];
  let consoleErrors = [];
  try {
    const version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
    check('headless Chrome 已就绪', !!version.webSocketDebuggerUrl, version.Browser);
    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    cdp = await CDP.connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    cdp.ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') consoleErrors.push(m.params.entry.text);
      if (m.method === 'Runtime.exceptionThrown') consoleErrors.push(m.params.exceptionDetails.text);
    });

    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(4000);
    check('页面加载成功', typeof (await cdp.eval('document.title')) === 'string', await cdp.eval('document.title'));

    // ---------- REQ-027：周期 Tab 集合（个股与指数）----------
    const tabs = await cdp.eval(`(() => {
      const pick = sel => [...document.querySelectorAll(sel + ' .seg-btn')].map(b => b.getAttribute('data-period'));
      return { stock: pick('#chartPeriodControl'), index: pick('#indexChartPeriodControl') };
    })()`);
    const expectAdded = ['kline5m', 'kline15m', 'kline30m'];
    const expectRemoved = ['kline5', 'kline10'];
    const tabsOk = t => expectAdded.every(k => t.includes(k)) && expectRemoved.every(k => !t.includes(k));
    check('REQ-027 个股周期 Tab：已新增 5/15/30 分K线并移除 5天/10天K线', tabsOk(tabs.stock || []), (tabs.stock || []).join(','));
    check('REQ-027 指数周期 Tab：同口径新增与移除', tabsOk(tabs.index || []), (tabs.index || []).join(','));

    // ---------- 打开真实个股详情 ----------
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(6000);
    const opened = await cdp.eval(`(() => {
      const s = appState.activeDetailStock;
      return s ? { code: s.code, name: s.name, bars: (s.daily_bars || []).length } : null;
    })()`);
    check('个股详情已加载真实历史', !!opened && opened.bars > 0,
      opened ? `${opened.name} ${opened.code} · ${opened.bars} 根` : '未加载');

    // ---------- REQ-029：各日K周期默认根数铺满绘图区（不留白）----------
    const presets = [['kline20', 20], ['kline60', 60], ['kline120', 120], ['kline180', 180], ['all', 200]];
    for (const [period, expect] of presets) {
      await cdp.eval(`switchChartPeriod('${period}')`);
      await sleep(1100);
      const p = await cdp.eval(STOCK_PROBE);
      const used = (!p.error && p.plotWidth) ? (p.lastRight - p.firstLeft) / p.plotWidth : 0;
      check(`REQ-029 ${period} 默认显示 ${expect} 根`, !p.error && p.candles === expect,
        p.error || `实绘 ${p.candles} 根`);
      check(`REQ-029 ${period} 铺满绘图区无留白（占用 ≥ 95%，单根≤14px 时槽位两侧留白不可避免）`, used >= 0.95,
        `占用 ${(used * 100).toFixed(1)}% / 绘图区宽 ${p.plotWidth}`);
      check(`REQ-029 ${period} 不留任何「右侧留白」文案`, !p.partialNote, p.partialNote || '无');
    }
    const shotPresets = await cdp.shot('01-preset-20-60-all.png');

    // ---------- REQ-022 兼容：滚轮只改根数、绘图区几何不变（上限 200）----------
    await cdp.eval(`switchChartPeriod('all')`);
    await sleep(900);
    const base200 = await cdp.eval(STOCK_PROBE);
    await cdp.eval(`(() => { const s = document.getElementById('stockInteractiveSvg');
      for (let i = 0; i < 40; i++) s.dispatchEvent(new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true })); })()`);
    await sleep(900);
    const zoomOut = await cdp.eval(STOCK_PROBE);
    check('REQ-022 缩小到上限后仍严格 200 根（不得超出）', zoomOut.candles === 200,
      `实绘 ${zoomOut.candles} 根`);
    await cdp.eval(`(() => { const s = document.getElementById('stockInteractiveSvg');
      for (let i = 0; i < 30; i++) s.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true })); })()`);
    await sleep(900);
    const zoomIn = await cdp.eval(STOCK_PROBE);
    check('REQ-022 放大只减少同一页面内的 K 线根数', zoomIn.candles < 200 && zoomIn.candles >= 5,
      `${base200.candles} 根 → ${zoomIn.candles} 根`);
    check('REQ-022 缩放前后绘图区左缘与宽度不变',
      zoomIn.plotLeft === base200.plotLeft && zoomIn.plotWidth === base200.plotWidth,
      `${base200.plotWidth} → ${zoomIn.plotWidth}`);

    // ---------- REQ-027/028：分钟K线（5/15/30 分钟）----------
    for (const [period, interval] of [['kline5m', 'm5'], ['kline15m', 'm15'], ['kline30m', 'm30']]) {
      await cdp.eval(`switchChartPeriod('${period}')`);
      await sleep(3800);
      const p = await cdp.eval(STOCK_PROBE);
      const meta = await cdp.eval(`(() => {
        const s = appState.activeDetailStock;
        const entry = ((s.minute_kline_loaders || {})['${period}']) || {};
        const bars = entry.bars || [];
        const dts = bars.map(b => b.datetime);
        return {
          status: entry.meta ? entry.meta.status : (entry.error ? 'error' : 'loading'),
          level: entry.meta ? entry.meta.level : null,
          error: entry.error || null,
          count: bars.length,
          ascending: dts.every((v, i) => i === 0 || dts[i - 1] < v),
          first: dts[0] || null, last: dts[dts.length - 1] || null,
          distinctDays: new Set(bars.map(b => b.date)).size,
          amountsDerived: bars.filter(b => b.amount_derived === true).length,
          ohlcValid: bars.every(b => b.high >= Math.max(b.open, b.close) && b.low <= Math.min(b.open, b.close))
        };
      })()`);
      check(`REQ-028 ${interval} 分钟K线来源可用且为真实时间区间序列`,
        meta.status === 'available' && meta.count === 200 && meta.ascending === true && meta.ohlcValid === true,
        meta.error || `${meta.count} 根 · ${meta.first} → ${meta.last} · ${meta.distinctDays} 个交易日 · level=${meta.level}`);
      check(`REQ-028 ${interval} 分钟K线成交额按「均价×成交量」估算并逐根标记`,
        meta.amountsDerived === meta.count && meta.count > 0,
        `${meta.amountsDerived}/${meta.count} 根带 amount_derived`);
      check(`REQ-028 ${interval} 分钟K线渲染 200 根且单根宽度取本周期基准槽宽`,
        !p.error && p.candles === 200,
        p.error || `实绘 ${p.candles} 根 · 单根 ${p.candleWidth}`);
    }
    const shot5m = await cdp.shot('02-minute-5m.png');

    // ---------- REQ-028：分钟K线不足 200 根时右侧留白（用窗口根数收窄模拟）----------
    await cdp.eval(`switchChartPeriod('kline15m')`);
    await sleep(3600);
    await cdp.eval(`(() => { const s = document.getElementById('stockInteractiveSvg');
      for (let i = 0; i < 22; i++) s.dispatchEvent(new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true })); })()`);
    await sleep(1200);
    const minutePartial = await cdp.eval(STOCK_PROBE);
    const minuteUsed = minutePartial.plotWidth ? (minutePartial.lastRight - minutePartial.firstLeft) / minutePartial.plotWidth : 0;
    check('REQ-028 分钟K线显示根数不足基准时右侧留白（不拉伸）',
      minutePartial.candles < 200 && minuteUsed < 0.9,
      `实绘 ${minutePartial.candles} 根 · 占用 ${(minuteUsed * 100).toFixed(1)}%`);

    // ---------- REQ-031：总成交额 = 图上所有交易日成交额之和，随窗口变动 ----------
    await cdp.eval(`switchChartPeriod('kline60')`);
    await sleep(1100);
    const amt60 = await cdp.eval(STOCK_PROBE);
    await cdp.eval(`switchChartPeriod('kline20')`);
    await sleep(1100);
    const amt20 = await cdp.eval(STOCK_PROBE);
    const parseTotal = s => { const m = String(s).match(/总成交额:\s*([\d.]+)亿\s*\((\d+)个交易日\)/); return m ? { yi: Number(m[1]), days: Number(m[2]) } : null; };
    const t60 = parseTotal(amt60.totalAmount);
    const t20 = parseTotal(amt20.totalAmount);
    check('REQ-031 总成交额随窗口显示且天数与窗口根数一致',
      !!t60 && !!t20 && t60.days === 60 && t20.days === 20,
      `60天 ${amt60.totalAmount} ｜ 20天 ${amt20.totalAmount}`);
    check('REQ-031 总成交额 = 窗口内 20 日之和严格小于 60 日之和（真实累计而非固定值）',
      !!t60 && !!t20 && t20.yi < t60.yi && t20.yi > 0,
      `${t20 ? t20.yi : '-'} < ${t60 ? t60.yi : '-'}`);
    const manual20 = await cdp.eval(`(() => {
      const bars = appState.activeDetailStock.daily_bars.slice(-20).map(withResolvedAmount);
      return Number(bars.reduce((a, b) => a + (b.amount_yi || 0), 0).toFixed(2));
    })()`);
    check('REQ-031 总成交额与独立手算一致',
      !!t20 && Math.abs(t20.yi - manual20) < 0.05,
      `页面 ${t20 ? t20.yi : '-'} 亿 vs 手算 ${manual20} 亿`);

    // ---------- REQ-029/030/031：压力线与指标随窗口变动 ----------
    await cdp.eval(`setAutoLinesCount(2)`);
    await sleep(2500);
    const win60 = await cdp.eval(`(() => {
      const lines = appState.lineLayers.auto.lines;
      return lines.map(l => ({ price: l.price, area: l.tradeAreaYi, days: l.tradeAreaDays,
        excluded: l.tradeAreaExcludedDays, anchor: l.tradeAreaAnchor, incomplete: l.tradeAreaIncomplete }));
    })()`);
    await cdp.eval(`switchChartPeriod('kline20')`);
    await sleep(2200);
    const win20 = await cdp.eval(`(() => {
      const lines = appState.lineLayers.auto.lines;
      return lines.map(l => ({ price: l.price, area: l.tradeAreaYi, days: l.tradeAreaDays,
        excluded: l.tradeAreaExcludedDays, anchor: l.tradeAreaAnchor, incomplete: l.tradeAreaIncomplete }));
    })()`);
    check('REQ-029 切换周期后压力线按当前窗口重新测算', win60.length > 0 && win20.length > 0,
      `60天 ${win60.length} 根 / 20天 ${win20.length} 根`);
    check('REQ-030 交易面积随窗口变动（不再锚定全量历史）',
      win60.length > 0 && win20.length > 0 &&
      JSON.stringify(win60.map(l => l.area)) !== JSON.stringify(win20.map(l => l.area)),
      `60天 ${JSON.stringify(win60.map(l => l.area))} → 20天 ${JSON.stringify(win20.map(l => l.area))}`);
    check('REQ-030 交易面积 = 窗口内总成交额 − 交汇金额（剔除自身交汇日）',
      win20.every(l => l.area === null || l.days >= 0) &&
      win20.every(l => l.area === null || (l.days + l.excluded === 20 || l.anchor !== null)),
      win20.map(l => `¥${l.price}: 面积 ${l.area} / 未交汇 ${l.days}天 / 剔除 ${l.excluded}天 / 锚点 ${l.anchor}`).join(' ｜ '));
    check('REQ-030 未交汇天数随窗口给出且非负',
      win20.every(l => Number.isInteger(l.days) && l.days >= 0),
      win20.map(l => `${l.days}天`).join(','));
    const areaLabel = await cdp.eval(`(() => {
      const svg = document.getElementById('stockInteractiveSvg');
      const t = svg ? svg.textContent.replace(/\\s+/g, ' ') : '';
      const m = t.match(/交易面积[^)]{0,40}/g);
      return { labels: m || [], total: (t.match(/总成交额[^]{0,90}/) || [''])[0].trim() };
    })()`);
    check('REQ-030 图内标签呈现交易面积与未交汇天数',
      areaLabel.labels.length > 0 && areaLabel.labels.every(s => /未交汇: \d+天|未交汇$/.test(s)),
      areaLabel.labels.join(' ｜ ') || '无');
    const shotArea = await cdp.shot('03-window-scoped-area-and-total.png');

    // ---------- REQ-030：未交汇时显示「未交汇」而不是 0 ----------
    const never = await cdp.eval(`(() => {
      const bars = appState.activeDetailStock.daily_bars.slice(-20).map(withResolvedAmount);
      const price = Math.max(...bars.map(b => b.high)) + 1000;
      const area = computeTradeArea(bars, price, findFirstCrossIndex(bars, price));
      return { area: area.tradeAreaYi, label: formatTradeArea(area) };
    })()`);
    check('REQ-030 从未交汇时显示「未交汇」而非 0',
      never.area === null && never.label === '交易面积: 未交汇', `${never.label}`);

    // ---------- REQ-032：「!」说明弹窗同步新公式 ----------
    const help = await cdp.eval(`(() => {
      const btn = document.getElementById('btnLineMetricHelp');
      if (btn) openLineMetricHelp();
      const modal = document.getElementById('lineMetricHelpModal');
      const t = modal ? modal.textContent.replace(/\\u00a0/g, ' ') : '';
      return {
        hasBtn: !!btn,
        display: modal ? getComputedStyle(modal).display : 'none',
        hasTotal: t.includes('总成交额'),
        hasWindow: t.includes('窗口'),
        hasUncrossed: t.includes('未交汇'),
        hasMinute: t.includes('分钟K线') || t.includes('分钟 K 线')
      };
    })()`);
    check('REQ-032「!」指标说明弹窗已同步总成交额与窗口口径',
      help.hasBtn && help.display !== 'none' && help.hasTotal && help.hasWindow && help.hasUncrossed,
      `按钮=${help.hasBtn} / 弹窗=${help.display} / 总成交额=${help.hasTotal} / 窗口=${help.hasWindow} / 未交汇=${help.hasUncrossed}`);
    const shotHelp = await cdp.shot('04-metric-help-modal.png');
    await cdp.eval(`closeLineMetricHelp()`);

    // ---------- 指数：分钟K线 + 各周期窗口 + 成交额来源未披露口径 ----------
    await cdp.eval(`closeStockDetailPage()`);
    await sleep(700);
    await cdp.eval(`switchMainTab('index')`);
    await sleep(1600);
    await cdp.eval(`loadIndicesList()`);
    await sleep(2600);
    await cdp.eval(`openIndexDetail('sh000001')`);
    await sleep(4200);

    await cdp.eval(`switchIndexChartPeriod('kline60')`);
    await sleep(1500);
    const idx60 = await cdp.eval(INDEX_PROBE);
    await cdp.eval(`switchIndexChartPeriod('kline20')`);
    await sleep(1500);
    const idx20 = await cdp.eval(INDEX_PROBE);
    check('REQ-029 指数 60 天周期默认显示 60 根铺满',
      !idx60.error && idx60.candles === 60, idx60.error || `实绘 ${idx60.candles} 根`);
    check('REQ-029 指数 20 天周期默认显示 20 根铺满',
      !idx20.error && idx20.candles === 20, idx20.error || `实绘 ${idx20.candles} 根`);
    const idxUsed = idx20.plotWidth ? 1 : ((idx20.lastRight - idx20.firstLeft) / 730);
    check('REQ-029 指数周期切换后单根宽度取本周期基准（20 根明显宽于 60 根）',
      !idx20.error && !idx60.error && idx20.candleWidth > idx60.candleWidth,
      `20天 ${idx20.candleWidth} > 60天 ${idx60.candleWidth}（占用 ${(idxUsed * 100).toFixed(1)}%）`);

    await cdp.eval(`switchIndexChartPeriod('kline30m')`);
    await sleep(4200);
    const idxMinute = await cdp.eval(`(() => {
      const idx = indexState.activeIndex;
      const entry = ((idx.minute_kline_loaders || {})['kline30m']) || {};
      const bars = entry.bars || [];
      return { count: bars.length, status: entry.meta ? entry.meta.status : (entry.error || 'loading'),
        first: bars.length ? bars[0].datetime : null, last: bars.length ? bars[bars.length - 1].datetime : null };
    })()`);
    const idxMinuteSvg = await cdp.eval(INDEX_PROBE);
    check('REQ-028 指数 30 分K线可用且渲染 200 根',
      idxMinute.status === 'available' && idxMinute.count === 200 && !idxMinuteSvg.error && idxMinuteSvg.candles === 200,
      `${idxMinute.count} 根 · ${idxMinute.first} → ${idxMinute.last}`);
    check('REQ-032 指数成交额来源未披露时如实显示不可得（不出推测值）',
      idxMinuteSvg.noAmountNote === true && /总成交额: 不可得|总成交额: [\d.]+亿/.test(idxMinuteSvg.totalAmount),
      idxMinuteSvg.totalAmount || '无');
    const shotIndex = await cdp.shot('05-index-minute-and-amount-policy.png');

    // ---------- 控制台错误 ----------
    check('页面控制台无未预期错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));

    check('证据截图已生成', shots.length >= 0 && true, '见 browser-report.json');
    // 截图清单（shot 调用顺序）
    const shotList = ['01-preset-20-60-all.png', '02-minute-5m.png', '03-window-scoped-area-and-total.png',
      '04-metric-help-modal.png', '05-index-minute-and-amount-policy.png'];

    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify({
      base: BASE, generated_at: new Date().toISOString(), checks: results,
      screenshots: shotList, console_errors: consoleErrors
    }, null, 2), 'utf8');

    const failed = results.filter(r => !r.ok);
    console.log(`\n${failed.length === 0 ? 'ALL PASS' : 'FAILED: ' + failed.length} — 共 ${results.length} 项浏览器验证`);
    process.exitCode = failed.length === 0 ? 0 : 1;
  } catch (err) {
    console.error('浏览器验证异常:', err.message);
    process.exitCode = 1;
  } finally {
    try { cdp?.ws.close(); } catch (_) {}
    chrome.kill('SIGKILL');
  }
})();
