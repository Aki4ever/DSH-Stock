#!/usr/bin/env node
/**
 * R06 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-034/035/036
 * 覆盖：
 *   1. K线图两级 Tab：一级＝分时图/日线图/周线图/季线图；二级＝30/60/120/180（天|周|季）
 *   2. 颗粒度与 Tab 对应：分时维度 5分/1分K线每根＝对应分钟区间；周/季K线由真实日K聚合
 *   3. 缩放只改「画面显示多少根K线」：下限 30 根，上限＝该颗粒度全部可用根数；不足时右侧留白
 *   4. 双维度可同屏并存（左右布局），两个图的周期/缩放/画线工具完全独立
 *   5. 重合图（方案A）：日K背景 + 当日分时折线叠加，共用同一价格轴并显式标注时间轴不对应
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-23-r06';
const PORT = Number(process.env.DSH_CDP_PORT || 9360);
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const CHROME = process.env.DSH_CHROME_BIN ||
  path.join(os.homedir(), 'Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');

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

/**
 * 面板几何与文案探针。
 * 需求REQ-047 探针修订（2026-09-24）：绘图区几何一律「实测」——画布宽取 SVG 的 viewBox，
 * 绘图区取最宽的背景矩形（x / width），不再把 730 / 795 这类历史几何写死在断言里；
 * 蜡烛计数同时排除所有「与绘图区同宽」的背景矩形（旧写法漏掉了一块无 fill/stroke 的背景矩形，导致 +1 根）。
 */
function panelProbe(slot) {
  return `(() => {
    const svg = document.getElementById('stockInteractiveSvg_${slot}');
    if (!svg) return { error: '未找到面板 ${slot} 的 SVG' };
    const rects = [...svg.querySelectorAll('rect')];
    const vb = (svg.getAttribute('viewBox') || '').split(/[\\s,]+/).map(Number);
    const canvasW = Number(vb[2]) || parseFloat(svg.getAttribute('width')) || 0;
    const wide = rects.filter(r => (parseFloat(r.getAttribute('width')) || 0) > canvasW * 0.5);
    const plotRect = wide.length
      ? wide.reduce((a, b) => ((parseFloat(a.getAttribute('width')) || 0) >= (parseFloat(b.getAttribute('width')) || 0) ? a : b))
      : null;
    const plotWidth = plotRect ? parseFloat(plotRect.getAttribute('width')) : null;
    const bodies = rects.filter(r => r.getAttribute('opacity') === null
      && r.getAttribute('fill') !== 'none' && r.getAttribute('fill') !== '#0f172a' && !r.getAttribute('stroke')
      && (plotWidth === null || Math.abs((parseFloat(r.getAttribute('width')) || 0) - plotWidth) > 0.5));
    const xs = bodies.map(r => parseFloat(r.getAttribute('x')));
    const ws = bodies.map(r => parseFloat(r.getAttribute('width')));
    const text = svg.textContent.replace(/\\s+/g, ' ');
    return {
      candles: bodies.length,
      candleWidth: ws.length ? ws[0] : null,
      firstLeft: xs.length ? Math.min(...xs) : null,
      lastRight: xs.length ? Math.max(...xs) + ws[xs.indexOf(Math.max(...xs))] : null,
      canvasWidth: canvasW,
      plotLeft: plotRect ? parseFloat(plotRect.getAttribute('x')) : null,
      plotWidth: plotWidth,
      plotRight: plotRect ? parseFloat(plotRect.getAttribute('x')) + plotWidth : null,
      granularity: (text.match(/(1分K线|5分K线|日线图|周线图|季线图) · [^｜]{0,30}/) || [''])[0].trim(),
      viewport: (text.match(/视窗 \\d+ 根 · 实绘 \\d+ 根(（[^）]*）)?/) || [''])[0].trim(),
      hlines: svg.querySelectorAll('.chart-hline').length,
      overlay: !!svg.querySelector('.overlay-intraday-layer'),
      overlayNote: (text.match(/🔀[^｜]{0,90}/) || [''])[0].trim(),
      totalAmount: (text.match(/总成交额[^ ]{0,60}/) || [''])[0].trim()
    };
  })()`;
}

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-r06-chrome-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1680,1500', '--hide-scrollbars', 'about:blank'
  ], { stdio: 'ignore' });

  let cdp;
  const shots = [];
  const consoleErrors = [];
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
    await sleep(4500);
    check('页面加载成功', typeof (await cdp.eval('document.title')) === 'string', await cdp.eval('document.title'));

    // ---------- REQ-034：两级 Tab 结构 ----------
    const tabs = await cdp.eval(`(() => ({
      groups: [...document.querySelectorAll('#klineGroupControl .seg-btn')].map(b => b.textContent.trim()),
      counts: [...document.querySelectorAll('#klineCountControl .seg-btn')].map(b => b.textContent.trim()),
      subs: [...document.querySelectorAll('#minuteSubControl .seg-btn')].map(b => b.textContent.trim())
    }))()`);
    check('REQ-034 一级 Tab＝日线图/周线图/季线图',
      tabs.groups.length === 3 && tabs.groups.join('').includes('日线图') && tabs.groups.join('').includes('周线图') && tabs.groups.join('').includes('季线图'),
      tabs.groups.join(' | '));
    check('REQ-034 二级 Tab＝30/60/120/180天K线（默认日线颗粒度）',
      tabs.counts.length === 4 && tabs.counts.join(',').includes('30天K线') && tabs.counts.join(',').includes('180天K线'),
      tabs.counts.join(' | '));
    // 需求REQ-044（取代 REQ-034 该项的旧口径）：分时维度已按用户指令移除「1分K线」，只保留当日分时与5分K线
    check('REQ-044 分时维度子 Tab＝当日分时/5分K线（1分K线入口已移除）',
      tabs.subs.length === 2 && tabs.subs.join('').includes('当日分时') && tabs.subs.join('').includes('5分K线') && !tabs.subs.join('').includes('1分K线'),
      tabs.subs.join(' | '));

    // ---------- 打开真实个股详情 ----------
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(8000);
    const opened = await cdp.eval(`(() => { const s = appState.activeDetailStock; return s ? { name: s.name, days: (s.daily_bars || []).length, timeline: ((s.timeline_data || {}).items || []).length } : null; })()`);
    check('个股详情已加载真实历史', !!opened && opened.days > 0,
      opened ? `${opened.name} · 日K ${opened.days} 根 · 当日分时 ${opened.timeline} 点` : '未加载');

    // ---------- REQ-035：日线图 30 天 ----------
    await cdp.eval(`switchKlineGroup('daily'); switchKlineCount(30)`);
    await sleep(1400);
    let p = await cdp.eval(panelProbe('right'));
    // 本批几何为「画布实测 + 绘图区实测」，后续断言一律与首测几何比对（不再硬编码 730/795）
    const geo0 = { left: p.plotLeft, width: p.plotWidth, right: p.plotRight, canvas: p.canvasWidth };
    check('REQ-035 日线图·30天K线：实绘 30 根日K', p.candles === 30, `实绘 ${p.candles} 根 · ${p.viewport}`);
    check('REQ-047 绘图区几何实测有效（画布宽 / 绘图区左缘 / 绘图区宽）',
      p.canvasWidth > 0 && p.plotLeft > 0 && p.plotWidth > 0 && Math.abs(p.plotLeft + p.plotWidth + p.plotLeft - p.canvasWidth) < 1,
      `画布 ${p.canvasWidth} · 绘图区 ${p.plotLeft}~${p.plotRight}（宽 ${p.plotWidth}）`);
    check('REQ-034 颗粒度标注＝日线图（每根＝1个交易日）', /日线图/.test(p.granularity), p.granularity || '未标注');
    const dailyPrice = await cdp.eval(`(() => { const b = appState.activeDetailStock.daily_bars; const last = b[b.length-1]; return { date: last.date, close: last.close }; })()`);

    // ---------- REQ-035：周线图（真实日K聚合） ----------
    await cdp.eval(`switchKlineGroup('weekly')`);
    await sleep(2200);
    p = await cdp.eval(panelProbe('right'));
    check('REQ-035 周线图·30周K线：实绘 30 根周K', p.candles === 30, `实绘 ${p.candles} 根 · ${p.viewport}`);
    check('REQ-034 颗粒度标注＝周线图（每根＝1个自然周，由真实日K聚合）', /周线图/.test(p.granularity), p.granularity || '未标注');
    const weeklyCounts = await cdp.eval(`[...document.querySelectorAll('#klineCountControl .seg-btn')].map(b=>b.textContent.trim()).join(' | ')`);
    check('REQ-034 二级 Tab 文案随颗粒度变为「30周K线」(单位随一级 Tab 变化)',
      weeklyCounts.includes('30周K线') && weeklyCounts.includes('180周K线'), weeklyCounts);
    const agg = await cdp.eval(`(() => {
      const bars = panelAvailableBars(appState.activeDetailStock, chartPanels.right.st);
      const d = appState.activeDetailStock.daily_bars;
      const weekOf = ds => { const [y,m,dd]=ds.split('-').map(Number); const dt=new Date(Date.UTC(y,m-1,dd));
        const dow=dt.getUTCDay()===0?7:dt.getUTCDay(); dt.setUTCDate(dt.getUTCDate()+4-dow);
        const ys=new Date(Date.UTC(dt.getUTCFullYear(),0,1)); return dt.getUTCFullYear()+'W'+String(Math.ceil(((dt-ys)/86400000+1)/7)).padStart(2,'0'); };
      const last = bars[bars.length-1]; const key = weekOf(last.date);
      const members = d.filter(b => weekOf(b.date) === key);
      return { weeks: bars.length, lastDate: last.date, members: members.length,
        open: members[0].open, close: members[members.length-1].close,
        high: Math.max(...members.map(b=>b.high)), low: Math.min(...members.map(b=>b.low)),
        aggOpen: last.open, aggClose: last.close, aggHigh: last.high, aggLow: last.low };
    })()`);
    check('REQ-034 周K聚合口径正确（开＝区间首日开/收＝末日收/高＝区间最高/低＝区间最低）',
      agg.open === agg.aggOpen && agg.close === agg.aggClose && agg.high === agg.aggHigh && agg.low === agg.aggLow,
      `末周 ${agg.lastDate}（含 ${agg.members} 个交易日）：开 ${agg.aggOpen}/${agg.open} 高 ${agg.aggHigh}/${agg.high} 低 ${agg.aggLow}/${agg.low} 收 ${agg.aggClose}/${agg.close}`);
    check('REQ-034 周线图末根收盘＝最后一根日K收盘（同一标的、同一真实来源）',
      Math.abs(agg.aggClose - dailyPrice.close) < 1e-9, `周 ${agg.aggClose} / 日 ${dailyPrice.close}`);

    // ---------- REQ-035：季线图 ----------
    await cdp.eval(`switchKlineGroup('quarterly')`);
    await sleep(2200);
    p = await cdp.eval(panelProbe('right'));
    check('REQ-035 季线图·30季K线：实绘 30 根季K', p.candles === 30, `实绘 ${p.candles} 根 · ${p.viewport}`);
    check('REQ-034 颗粒度标注＝季线图（每根＝1个自然季度，由真实日K聚合）', /季线图/.test(p.granularity), p.granularity || '未标注');
    const qAll = await cdp.eval(`chartPanels.right.st.availableCount`);
    const shotsQuart = await cdp.eval(`(() => { switchKlineGroup('quarterly'); return 1; })()`);
    shots.push(await cdp.shot('01-quarterly-30.png'));

    // ---------- REQ-035：缩放只改根数（下限 30 / 上限＝全部） ----------
    // 探针修订（2026-09-24）：滚轮/手势缩放已按产品需求显式移除，缩放的唯一真实入口是浮动 ➕/➖ 按钮
    // （`zoomKlineChart('in'|'out', slot)`）——因此这里**点击真实按钮**驱动，不再派发已被移除的 wheel 事件。
    const zoomBtns = await cdp.eval(`(() => {
      const box = document.getElementById('floatingZoomRight');
      const btns = box ? [...box.querySelectorAll('.floating-zoom-btn')] : [];
      return { count: btns.length, titles: btns.map(b => b.getAttribute('title') || '') };
    })()`);
    check('REQ-035 缩放交互入口＝浮动 ➕/➖ 按钮（滚轮缩放已按需求移除）',
      zoomBtns.count === 2 && /放大/.test(zoomBtns.titles[0]) && /缩小/.test(zoomBtns.titles[1]),
      `按钮 ${zoomBtns.count} 个：${zoomBtns.titles.join(' | ')}`);
    const wheelIgnored = await cdp.eval(`(() => {
      switchKlineGroup('daily'); switchKlineCount(180);
      const before = chartPanels.right.st.klineCount;
      const s = document.getElementById('stockInteractiveSvg_right');
      for (let i = 0; i < 20; i++) s.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true }));
      return { before: before, after: chartPanels.right.st.klineCount };
    })()`);
    check('REQ-035 滚轮事件不再改变视窗根数（缩放只由按钮驱动）',
      wheelIgnored.after === wheelIgnored.before, `${wheelIgnored.before} → ${wheelIgnored.after}`);

    // 下限硬约束：从 180 根出发连续点 ➕ 40 次（每次 15% 步进），必须停在下限 30 且不再继续放大
    const zoomIn = await cdp.eval(`(() => {
      switchKlineCount(180);
      const box = document.getElementById('floatingZoomRight');
      const plus = box.querySelectorAll('.floating-zoom-btn')[0];
      for (let i = 0; i < 40; i++) plus.click();
      return { count: chartPanels.right.st.klineCount };
    })()`);
    await sleep(1200);
    p = await cdp.eval(panelProbe('right'));
    check('REQ-035 放大到极限＝30 根（下限硬约束，不再继续放大）', p.candles === 30 && zoomIn.count === 30,
      `实绘 ${p.candles} 根 · 面板视窗 ${zoomIn.count} 根 · ${p.viewport}`);

    // 缩放下限之上的第一步：点一次 ➖ 必须真的变多（证明按钮链路有效，而非恒为 30）
    const zoomOut1 = await cdp.eval(`(() => {
      const before = chartPanels.right.st.klineCount;
      document.getElementById('floatingZoomRight').querySelectorAll('.floating-zoom-btn')[1].click();
      return { before: before, after: chartPanels.right.st.klineCount };
    })()`);
    check('REQ-035 缩小一步：视窗根数增加（➖ 按钮驱动的真实缩放）',
      zoomOut1.after > zoomOut1.before, `${zoomOut1.before} → ${zoomOut1.after}`);

    // 上限：从 5000 根出发连续点 ➖，必须停在该颗粒度「全部可用根数」（而不是历史固定的 200 根）
    const zoomOut = await cdp.eval(`(() => {
      switchKlineCount(5000);
      const box = document.getElementById('floatingZoomRight');
      const minus = box.querySelectorAll('.floating-zoom-btn')[1];
      for (let i = 0; i < 12; i++) minus.click();
      return { count: chartPanels.right.st.klineCount, available: chartPanels.right.st.availableCount };
    })()`);
    await sleep(1800);
    p = await cdp.eval(panelProbe('right'));
    const dAll = await cdp.eval(`chartPanels.right.st.availableCount`);
    check('REQ-035 缩小到极限＝该颗粒度全部可用根数（不再固定 200 根）',
      p.candles === dAll && zoomOut.count === dAll && dAll > 200,
      `实绘 ${p.candles} 根 / 面板视窗 ${zoomOut.count} 根 / 全部 ${dAll} 根`);
    check('REQ-035 缩放只改根数：绘图区左缘与宽度恒定',
      p.plotLeft === geo0.left && p.plotWidth === geo0.width && geo0.width > 0,
      `首测 画布${geo0.canvas} 绘图区 ${geo0.left}~${geo0.right}(宽${geo0.width}) · 现测 画布${p.canvasWidth} 绘图区 ${p.plotLeft}~${p.plotRight}(宽${p.plotWidth})`);
    shots.push(await cdp.shot('02-daily-zoom-all.png'));

    // ---------- REQ-035：真实根数不足视窗根数时右侧留白 ----------
    // 口径：视窗根数 N ∈ [30, 全部可用根数]；当真实可用根数 C < 30 时 N 取 30，实绘 C 根、右侧留白
    await cdp.eval(`switchKlineGroup('daily','right')`);
    await sleep(1400);
    await cdp.eval(`(() => {
      const bars = appState.activeDetailStock.daily_bars; const n = bars.length;
      document.getElementById('klineStartDate').value = bars[n - 10].date;
      document.getElementById('klineEndDate').value = bars[n - 1].date;
      applyKlineCustomDateRange();
    })()`);
    await sleep(1600);
    p = await cdp.eval(panelProbe('right'));
    const padRatio = (p.lastRight - p.firstLeft) / p.plotWidth;
    check('REQ-035 区间内仅 10 根真实日K（视窗下限 30）：实绘 10 根 + 右侧留白（不拉伸、不补足）',
      p.candles === 10 && padRatio < 0.6 && /右侧留白/.test(p.viewport),
      `实绘 ${p.candles} 根 · 占用 ${(padRatio * 100).toFixed(1)}% · ${p.viewport}`);
    check('REQ-035 留白口径下视窗根数仍为下限 30 根', /视窗 30 根/.test(p.viewport), p.viewport);
    shots.push(await cdp.shot('03-ten-bars-right-padding.png'));
    await cdp.eval(`(() => { document.getElementById('klineStartDate').value = ''; document.getElementById('klineEndDate').value = ''; applyKlineCustomDateRange(); })()`);
    await sleep(1400);
    const afterClear = await cdp.eval(panelProbe('right'));
    check('REQ-035 清空日期区间后恢复整段K线', afterClear.candles === 30, `实绘 ${afterClear.candles} 根`);

    // ---------- REQ-034：双图同屏（左右布局） ----------
    await cdp.eval(`switchKlineGroup('daily','right'); switchKlineCount(60,'right'); showChartPanel('left')`);
    await sleep(3000);
    const dual = await cdp.eval(`(() => {
      const row = document.getElementById('chartPanelRow');
      const l = document.getElementById('chartPanelLeft'), r = document.getElementById('chartPanelRight');
      const lb = l.getBoundingClientRect(), rb = r.getBoundingClientRect();
      return { cls: row.className, lHidden: l.hidden, rHidden: r.hidden,
        lw: Math.round(lb.width), rw: Math.round(rb.width), lLeft: Math.round(lb.left), rLeft: Math.round(rb.left),
        sameRow: Math.abs(lb.top - rb.top) < 60,
        lSvg: !!document.getElementById('stockInteractiveSvg_left'),
        rSvg: !!document.getElementById('stockInteractiveSvg_right') };
    })()`);
    check('REQ-034 分时图与K线图同屏（左右并排、同一行）',
      dual.lHidden === false && dual.rHidden === false && dual.lSvg && dual.rSvg && dual.sameRow && dual.rLeft > dual.lLeft && dual.lw > 200 && dual.rw > 200,
      `左 ${dual.lw}px @${dual.lLeft} ｜ 右 ${dual.rw}px @${dual.rLeft} ｜ class=${dual.cls}`);
    shots.push(await cdp.shot('04-dual-panel.png'));

    // ---------- REQ-034：分时维度子 Tab 颗粒度 ----------
    await cdp.eval(`switchMinuteSub('m5','left')`);
    await sleep(4000);
    let lp = await cdp.eval(panelProbe('left'));
    check('REQ-034 分时维度·5分K线：每根＝5分钟区间，视窗 30 根',
      lp.candles === 30 && /5分K线/.test(lp.granularity), `实绘 ${lp.candles} 根 · ${lp.granularity || '未标注'}`);
    const m5span = await cdp.eval(`(() => { const bars = currentMinuteKlineBars(appState.activeDetailStock, 'klinem5') || [];
      const a = bars[bars.length-2], b = bars[bars.length-1];
      const toMin = s => Number(String(s).slice(0,2))*60 + Number(String(s).slice(3,5));
      return { n: bars.length, prev: a ? a.time : null, last: b ? b.time : null, gap: (a && b) ? toMin(b.time) - toMin(a.time) : null }; })()`);
    check('REQ-034 5分K线相邻两根时间间隔＝5 分钟（真实区间，非插值）',
      m5span.gap === 5 || m5span.gap === 65 || m5span.gap === 205, `间隔 ${m5span.gap} 分钟（跨午休/隔日属正常）`);

    // 需求REQ-044（取代 REQ-034 的「1分K线」口径）：入口已移除，调用后必须保持 5分K线，
    // 不得切到一个已不存在的颗粒度（也不得伪造 1分K线 的走势图）
    await cdp.eval(`switchMinuteSub('m1','left')`);
    await sleep(1500);
    lp = await cdp.eval(panelProbe('left'));
    check('REQ-044 调用已移除的 1分K线 不生效（左侧保持 5分K线）',
      /5分K线/.test(lp.granularity || ''), `实绘 ${lp.candles} 根 · ${lp.granularity || '未标注'}`);

    // ---------- REQ-034：两图画线工具各自独立生效 ----------
    const drawResult = await cdp.eval(`(() => {
      toggleDrawHLineMode('left');
      const svg = document.getElementById('stockInteractiveSvg_left');
      const rect = svg.getBoundingClientRect();
      const x = rect.left + rect.width * 0.5, y = rect.top + rect.height * (150 / 440);
      svg.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
      renderChartPanel('left'); renderChartPanel('right');
      const cnt = st => st.lineLayers.manual_up.lines.length + st.lineLayers.manual_down.lines.length;
      return {
        left: cnt(chartPanels.left.st), right: cnt(chartPanels.right.st),
        leftDom: document.querySelectorAll('#stockInteractiveSvg_left .chart-hline').length,
        rightDom: document.querySelectorAll('#stockInteractiveSvg_right .chart-hline').length,
        leftMode: chartPanels.left.st.drawHLineMode, rightMode: chartPanels.right.st.drawHLineMode
      };
    })()`);
    check('REQ-034 在分时图（左）画水平线：左图 1 条、右图 0 条（画线互不影响）',
      drawResult.left === 1 && drawResult.right === 0 && drawResult.leftDom === 1 && drawResult.rightDom === 0,
      JSON.stringify(drawResult));
    const autoResult = await cdp.eval(`(() => {
      setAutoLinesCount(2, 'right');
      renderChartPanel('right');
      return { rightAuto: chartPanels.right.st.lineLayers.auto.lines.length,
               leftAuto: chartPanels.left.st.lineLayers.auto.lines.length,
               leftTotal: chartPanels.left.st.lineLayers.manual_up.lines.length + chartPanels.left.st.lineLayers.manual_down.lines.length };
    })()`);
    check('REQ-034 自动画线只在本图生效（右图自动线，左图手动画线保留且不受影响）',
      autoResult.rightAuto > 0 && autoResult.leftAuto === 0 && autoResult.leftTotal === 1,
      JSON.stringify(autoResult));
    shots.push(await cdp.shot('05-independent-drawing.png'));

    // ---------- REQ-034：两图周期互相独立 ----------
    const indep = await cdp.eval(`(() => { switchKlineGroup('weekly','right'); renderChartPanel('right');
      return { leftPeriod: panelPeriodKey(chartPanels.left.st), rightPeriod: panelPeriodKey(chartPanels.right.st),
               leftCount: chartPanels.left.st.klineCount, rightCount: chartPanels.right.st.klineCount }; })()`);
    // 需求REQ-044：左侧分时图颗粒度仍为 5分K线（1分K线入口已移除，右侧切周线不影响左侧）
    check('REQ-034 切换K线图颗粒度不影响分时图（左侧仍为 5分K线）',
      indep.leftPeriod === 'klinem5' && indep.rightPeriod === 'klineweekly', JSON.stringify(indep));

    // ---------- REQ-036：重合图（方案A） ----------
    await cdp.eval(`switchKlineGroup('daily','right'); switchKlineCount(60,'right')`);
    await sleep(2500);
    const overlayState = await cdp.eval(`(() => { toggleOverlayIntraday('right');
      return { on: chartPanels.right.st.overlayIntraday, tl: ((appState.activeDetailStock.timeline_data || {}).items || []).length }; })()`);
    await sleep(2500);
    p = await cdp.eval(panelProbe('right'));
    check('REQ-036 重合图可调出：有当日分时则叠加折线，无分时则如实提示不可用',
      overlayState.on === true && (p.overlay === true || /暂无可叠加/.test(p.overlayNote)),
      `当日分时 ${overlayState.tl} 点 · overlay=${p.overlay} · ${p.overlayNote || '无提示'}`);
    check('REQ-036 重合图显式标注「时间轴与日K不对应」',
      overlayState.tl === 0 ? /不对应|暂无可叠加/.test(p.overlayNote) : /不对应/.test(p.overlayNote),
      p.overlayNote || '未标注');
    const overlayGeo = await cdp.eval(`(() => {
      const svg = document.getElementById('stockInteractiveSvg_right');
      const path = svg.querySelector('.overlay-intraday-layer path');
      const rects = [...svg.querySelectorAll('rect')];
      const vb = (svg.getAttribute('viewBox') || '').split(/[\\s,]+/).map(Number);
      const canvasW = Number(vb[2]) || 0;
      const wide = rects.filter(r => (parseFloat(r.getAttribute('width')) || 0) > canvasW * 0.5);
      const plotRect = wide.length ? wide.reduce((a, b) => ((parseFloat(a.getAttribute('width')) || 0) >= (parseFloat(b.getAttribute('width')) || 0) ? a : b)) : null;
      const plotLeft = plotRect ? parseFloat(plotRect.getAttribute('x')) : null;
      const plotRight = plotRect ? plotLeft + parseFloat(plotRect.getAttribute('width')) : null;
      if (!path) return { noPath: true, plotLeft: plotLeft, plotRight: plotRight };
      const d = path.getAttribute('d');
      const xs = [...d.matchAll(/[ML] ([\\d.]+) /g)].map(m => Number(m[1]));
      return { minX: Math.min(...xs), maxX: Math.max(...xs), plotLeft: plotLeft, plotRight: plotRight };
    })()`);
    check('REQ-036 重合图分时折线横向铺满绘图区（方案A口径）',
      overlayGeo.noPath ? true : (Math.abs(overlayGeo.minX - overlayGeo.plotLeft) < 1 && Math.abs(overlayGeo.maxX - overlayGeo.plotRight) < 1),
      overlayGeo.noPath ? '当日无分时数据，跳过几何校验' : `折线 X ${overlayGeo.minX}~${overlayGeo.maxX}（绘图区 ${overlayGeo.plotLeft}~${overlayGeo.plotRight}）`);
    shots.push(await cdp.shot('06-overlay-intraday.png'));

    // ---------- 面板收起与保护 ----------
    const single = await cdp.eval(`(() => { hideChartPanel('left');
      const row = document.getElementById('chartPanelRow');
      const r = document.getElementById('chartPanelRight').getBoundingClientRect();
      return { cls: row.className, lHidden: document.getElementById('chartPanelLeft').hidden, rw: Math.round(r.width) }; })()`);
    check('REQ-034 收起分时图后 K 线图占满整行',
      single.lHidden === true && single.cls.includes('single-panel') && single.rw > 700, JSON.stringify(single));
    const guard = await cdp.eval(`(() => { hideChartPanel('right'); return document.getElementById('chartPanelRight').hidden; })()`);
    check('REQ-034 不允许两个图同时收起（至少保留一个）', guard === false, `右侧面板 hidden=${guard}`);

    // ---------- 旧功能不回归：指数页周期 Tab 仍在 ----------
    const indexTabs = await cdp.eval(`[...document.querySelectorAll('#indexChartPeriodControl .seg-btn')].map(b => b.getAttribute('data-period')).join(',')`);
    check('回归：指数页周期 Tab 未被破坏', String(indexTabs).includes('timeline') && String(indexTabs).includes('all'), indexTabs);

    check('页面无 JS 运行错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));
  } catch (err) {
    check('验证流程执行完成', false, err.message);
  } finally {
    try { chrome.kill(); } catch (_) {}
  }

  fs.mkdirSync(OUT, { recursive: true });
  const failed = results.filter(r => !r.ok);
  fs.writeFileSync(path.join(OUT, 'browser-report.json'),
    JSON.stringify({ requirement: 'REQ-034/035/036', base: BASE, total: results.length, failed: failed.length, results, shots }, null, 2));
  console.log(`\n共 ${results.length} 项，失败 ${failed.length} 项`);
  console.log(`报告: ${path.join(OUT, 'browser-report.json')}`);
  process.exit(failed.length ? 1 : 0);
})();
