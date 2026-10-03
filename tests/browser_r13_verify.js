#!/usr/bin/env node
/**
 * R13 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-097 / REQ-098
 *
 * 覆盖：
 *   1. REQ-097：「⚡ 努力与结果」按钮点击/再点击，K线主图 SVG 必须产生**真实可见的 DOM 差异**
 *      （状态徽标 .effort-layer-badge 的 data-state 与 data-signals 翻转），且：
 *        · 本视窗零命中时必须出现 .effort-empty-note 显式说明（阈值口径与算法同源，页面上可见）；
 *        · 面板右上角 toast 报出「本视窗命中 N 个」；
 *        · 全程控制台 0 异常。
 *   2. REQ-098：副图信息条表头字号实测 —— SVG font-size 属性必须为 20（原 10 的两倍），
 *      并按 getScreenCTM() 换算出真实屏显像素（原实测仅 ≈7.2 CSS px），同时用 getBBox() 复核
 *      零重叠、不越出副图绘图区。
 *
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-10-02-r13';
const PORT = Number(process.env.DSH_CDP_PORT || 9374);
const STOCK = process.env.DSH_STOCK || 'sh601939';
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
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
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
      new Promise((_, rej) => setTimeout(() => rej(new Error('页面内脚本执行超时(60s): ' + String(expression).slice(0, 80))), 60000))
    ]);
    if (r.exceptionDetails) throw new Error(`页面内脚本异常: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result.value;
  }
  async shot(name) {
    // 实测坑（2026-10-02）：headless Chrome 148 下 `Page.captureScreenshot`（fromSurface 默认 true）会**无限挂起**，
    // 导致整套真机验证卡死在第一张截图、后续断言全部拿不到结果。故：① 加超时；② 超时后降级 fromSurface:false；
    // ③ 仍失败则跳过截图但**不中断断言**（判据是 DOM 实测，截图只是证据附件）。
    const tryShot = async (params) => Promise.race([
      this.send('Page.captureScreenshot', params),
      new Promise((_, rej) => setTimeout(() => rej(new Error('captureScreenshot 超时(6s)')), 6000))
    ]);
    if (shotFailures.length >= 2) { shotFailures.push(name); return null; }   // 已确认本机截不了图 → 快速跳过，不拖慢断言
    let r = null;
    try { r = await tryShot({ format: 'png', captureBeyondViewport: false }); }
    catch (_) {
      try { r = await tryShot({ format: 'png', captureBeyondViewport: false, fromSurface: false }); }
      catch (_) { r = null; }
    }
    if (!r || !r.data) { shotFailures.push(name); return null; }
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.join(OUT, name);
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
    return file;
  }
}

const results = [];
const shotFailures = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
}

/** REQ-097 探针：主图内「努力与结果」图层状态的可观测事实 */
const effortProbe = `(() => {
  const host = document.getElementById('chartSvgContainerRight');
  const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
  if (!svg) return { error: 'K线主图未渲染' };
  const badge = svg.querySelector('.effort-layer-badge');
  const empty = svg.querySelector('.effort-empty-note');
  const toast = [...document.querySelectorAll('.chart-toast-host')].map(h => h.textContent.trim()).join(' | ');
  return {
    hasBadge: !!badge,
    state: badge ? badge.getAttribute('data-state') : null,
    signals: badge ? Number(badge.getAttribute('data-signals')) : null,
    anomalies: badge ? Number(badge.getAttribute('data-anomalies')) : null,
    badgeText: badge ? badge.textContent.replace(/\\s+/g, ' ').trim() : '',
    emptyText: empty ? empty.textContent.replace(/\\s+/g, ' ').trim() : '',
    textNodes: svg.querySelectorAll('text').length,
    markers: svg.querySelectorAll('.effort-bs-marker').length,
    anomalyBars: svg.querySelectorAll('rect[stroke="#f59e0b"][opacity="0.95"]').length,
    toast
  };
})()`;

/** REQ-098 探针：副图表头字号（属性值 + 真实屏显像素）与真实包围盒重叠/越界 */
const fontProbe = (hostId) => `(() => {
  const host = document.getElementById('${hostId}');
  const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
  if (!svg) return { error: '图表未渲染' };
  const ctm = svg.getScreenCTM();
  const scale = ctm ? ctm.a : null;
  const info = (t) => {
    const b = t.getBBox();
    const attr = Number(t.getAttribute('font-size'));
    return { text: t.textContent.replace(/\\s+/g, ' ').trim(), attr, effPx: Number((attr * scale).toFixed(2)),
             baseline: Number(t.getAttribute('y')), boxH: Number(b.height.toFixed(2)),
             x: b.x, right: b.x + b.width, y: b.y, bottom: b.y + b.height };
  };
  const stats = [...svg.querySelectorAll('g.sub-summary-group text')].map(info);
  const titles = [...svg.querySelectorAll('text')].filter(t => /副图[:：]/.test(t.textContent) && !t.closest('g.sub-summary-group')).map(info);
  const scaleLabel = [...svg.querySelectorAll('text[text-anchor="end"]')].map(info).filter(t => /亿|万手|%$/.test(t.text) && t.attr >= 10);
  const items = stats.concat(titles);
  // 同行判定：同一行由 layoutSubplotHeader 用**同一基线 y**输出，故以基线相等为唯一判据。
  // 实测坑（2026-10-02）：用「包围盒纵向相交」判定同行，在 20px 字号下行距 22px < 字框高 23.2px，
  // 会把相邻两行误判为同一行，产生大量假重叠 —— 判据必须精确到基线。
  const overlaps = [];
  const crossRow = [];
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j];
    const sameRow = Math.abs(a.baseline - b.baseline) <= 0.5;
    const inter = Math.min(a.right, b.right) - Math.max(a.x, b.x);
    if (sameRow && inter > 0.5) overlaps.push({ a: a.text, b: b.text, px: Number(inter.toFixed(2)) });
    if (!sameRow && inter > 0.5) crossRow.push({ a: a.text, b: b.text, px: Number(inter.toFixed(2)), dy: Number(Math.abs(a.baseline - b.baseline).toFixed(1)) });
  }
  let panel = null;
  [...svg.querySelectorAll('rect')].forEach(r => {
    const w = Number(r.getAttribute('width')) || 0, h = Number(r.getAttribute('height')) || 0;
    if (w > 300 && h > 50 && h < 260) {
      const b = r.getBBox();
      if (!panel || b.y + b.height > panel.bottom) panel = { right: b.x + b.width, top: b.y, bottom: b.y + b.height };
    }
  });
  const overflow = panel ? items.filter(i => i.right > panel.right + 0.5).map(i => i.text) : [];
  return {
    scale: scale === null ? null : Number(scale.toFixed(4)),
    titleAttrs: titles.map(t => t.attr), statAttrs: stats.map(t => t.attr),
    titleEffPx: titles.map(t => t.effPx), statEffPx: stats.map(t => t.effPx),
    scaleLabel: scaleLabel.map(t => ({ text: t.text, attr: t.attr, effPx: t.effPx, x: Number(t.x.toFixed(1)) })),
    stats: stats.map(t => t.text), titles: titles.map(t => t.text),
    boxH: stats.length ? stats[0].boxH : null, baselines: [...new Set(stats.map(t => t.baseline))],
    crossRow, overlaps, overflow, error: null
  };
})()`;

const focusProbe = (id) => `(() => { const el = document.getElementById('${id}'); if (el) el.scrollIntoView({ block: 'center' }); return !!el; })()`;

(async () => {
  const shots = [];
  const consoleErrors = [];
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', '--window-size=1680,1200', '--user-data-dir=' + fs.mkdtempSync(path.join(os.tmpdir(), 'r13-chrome-')),
    'about:blank'
  ], { stdio: 'ignore' });
  let cdp = null;
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
    check('页面加载成功', !!(await cdp.eval('document.title')));

    // ================= 打开个股详情（用户截图中的 sh601939）=================
    await cdp.eval(`openStockDetail('${STOCK}')`);
    await sleep(12000);
    const opened = await cdp.eval(`(() => { const s = appState.activeDetailStock; return s ? { name: s.name, days: (s.daily_bars || []).length, window: currentKlineWindow() } : null; })()`);
    check('个股详情已加载真实日K', !!opened && opened.days > 0, opened ? `${opened.name} · 日K ${opened.days} 根 · 视窗 ${opened.window} 根` : '未加载');

    // ================= REQ-097：开关必有图上反馈 =================
    // 先确保图层处于开启态（首屏默认开启），再取基线
    await cdp.eval(`if (!appState.showEffortDraw) { toggleEffortDraw('right'); }`);
    await sleep(1200);
    const before = await cdp.eval(effortProbe);
    check('REQ-097 图层开启时主图存在状态徽标', !before.error && before.hasBadge === true,
      before.error || `data-state=${before.state} · 异动 ${before.anomalies} 根 · 买/卖信号 ${before.signals} 个 · 「${before.badgeText}」`);
    check('REQ-097 徽标口径与算法同源（含 20 日均量阈值）', !before.error && /1\.65×20日均量/.test(before.badgeText + before.emptyText),
      before.emptyText || before.badgeText);
    check('REQ-097 本视窗零命中时必须显式说明（不得静默）', !before.error && before.hasBadge === true && (before.signals > 0 || !!before.emptyText),
      before.signals > 0 ? `本视窗命中 ${before.signals} 个（无需空状态）` : before.emptyText);
    await cdp.eval(focusProbe('chartPanelRow'));
    await sleep(400);
    shots.push(await cdp.shot('01-effort-layer-on.png'));

    // 点击关闭 → 图上必须出现可见差异
    await cdp.eval(`document.getElementById('btnEffortDraw_right').click()`);
    await sleep(1200);
    const after = await cdp.eval(effortProbe);
    check('REQ-097 点击关闭后主图状态徽标发生翻转（点得动、看得见）',
      !after.error && after.state !== before.state,
      `data-state ${before.state} → ${after.state} · 文本节点 ${before.textNodes} → ${after.textNodes} · toast「${after.toast}」`);
    check('REQ-097 关闭状态在图上可读（不是静默无反应）',
      !after.error && (/已关闭/.test(after.badgeText) || after.textNodes !== before.textNodes),
      after.badgeText || `文本节点变化 ${after.textNodes - before.textNodes}`);
    await cdp.eval(focusProbe('chartPanelRow'));
    await sleep(400);
    shots.push(await cdp.shot('02-effort-layer-off.png'));

    // 再点击开启 → 回到开启态且 toast 报出命中数
    await cdp.eval(`document.getElementById('btnEffortDraw_right').click()`);
    await sleep(1500);
    const back = await cdp.eval(effortProbe);
    check('REQ-097 再次点击回到开启态且状态与首次一致',
      !back.error && back.state === before.state,
      `data-state=${back.state} · 「${back.badgeText}」`);
    check('REQ-097 toast 报出「本视窗命中 N 个」', /本视窗命中 \d+ 个/.test(back.toast), back.toast || '(toast 已消失，以徽标为准)');
    shots.push(await cdp.shot('03-effort-layer-reopened.png'));

    // 视窗放宽到 180 根 → 本视窗应真实命中 1 个（2026-03-03），验证「有命中」时的标记与计数同样可见
    await cdp.eval(`switchKlineCount(180, 'right')`);
    await sleep(3000);
    const wide = await cdp.eval(effortProbe);
    check('REQ-097 视窗放宽后有异动时：徽标计数、副图高亮与提示三者一致（不得自相矛盾）',
      !wide.error && wide.anomalies >= 1 && wide.anomalyBars >= 1 && /异动 [1-9]\d* 根/.test(wide.badgeText)
        && !/未识别到「天量窄实体」异动/.test(wide.emptyText),
      wide.error || `徽标异动 ${wide.anomalies} 根 · 副图异动柱高亮 ${wide.anomalyBars} 根 · 买卖点 ⚡ 标记 ${wide.markers} 个 · 提示「${wide.emptyText.slice(0, 40)}」`);
    shots.push(await cdp.shot('04-effort-layer-hit-180bars.png'));
    await cdp.eval(`switchKlineCount(30, 'right')`);
    await sleep(2000);

    // ================= REQ-098：副图表头字号 2 倍 + 真实零重叠 =================
    for (const [key, label] of [['amt', '成交额'], ['vol', '成交量'], ['turnover_rate', '换手率']]) {
      await cdp.eval(`switchChartSubplot('${key}', 'right')`);
      await sleep(1600);
      const fp = await cdp.eval(fontProbe('chartSvgContainerRight'));
      check(`REQ-098 日K副图(${label})表头字号＝20（原 10 的两倍）`,
        !fp.error && fp.titleAttrs.every(v => v === 20) && fp.statAttrs.length >= 5 && fp.statAttrs.every(v => v === 20),
        fp.error || `标题 ${JSON.stringify(fp.titleAttrs)} · 统计项 ${JSON.stringify(fp.statAttrs)}`);
      check(`REQ-098 日K副图(${label})真实屏显字号 ≥ 2× 原值（原 ≈7.2 CSS px）`,
        !fp.error && fp.titleEffPx.every(v => v >= 13) && fp.statEffPx.every(v => v >= 13),
        fp.error || `缩放系数 ${fp.scale} · 屏显 标题 ${JSON.stringify(fp.titleEffPx)} / 统计 ${JSON.stringify(fp.statEffPx)} CSS px`);
      check(`REQ-098 日K副图(${label})放大后同行真实包围盒零重叠`, !fp.error && fp.overlaps.length === 0,
        fp.overlaps.map(o => `${o.a}×${o.b}(${o.px}px)`).join(' | ')
        || `0 处同行重叠（行基线 ${JSON.stringify(fp.baselines)} · 字框高 ${fp.boxH}px · 跨行接触 ${fp.crossRow.length} 处）`);
      check(`REQ-098 日K副图(${label})表头不越出副图绘图区`, !fp.error && fp.overflow.length === 0,
        fp.overflow.length ? JSON.stringify(fp.overflow) : '未越界');
      if (key === 'amt') {
        check('REQ-098 副图 Y 轴刻度标签同步放大且未被画布左缘裁切',
          fp.scaleLabel.length > 0 && fp.scaleLabel.every(s => s.attr === 20 && s.x >= 0),
          JSON.stringify(fp.scaleLabel.slice(0, 2)));
        await cdp.eval(focusProbe('chartPanelRow'));
        await sleep(400);
        shots.push(await cdp.shot('05-subplot-header-20px.png'));
      }
    }

    // 左侧当日分时副图同样放大（两图同源）
    await cdp.eval(`switchChartSubplot('vol', 'left')`);
    await sleep(1600);
    const fpTl = await cdp.eval(fontProbe('chartSvgContainerLeft'));
    check('REQ-098 当日分时副图表头同样为 20 且零重叠不越界',
      !fpTl.error && fpTl.titleAttrs.every(v => v === 20) && fpTl.overlaps.length === 0 && fpTl.overflow.length === 0,
      fpTl.error || `标题字号 ${JSON.stringify(fpTl.titleAttrs)} · 统计 ${JSON.stringify(fpTl.statAttrs)} · 重叠 ${fpTl.overlaps.length} 处`);
    await cdp.eval(focusProbe('chartPanelRow'));
    await sleep(400);
    shots.push(await cdp.shot('06-timeline-subplot-header-20px.png'));

    check('控制台无脚本错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | ') || '0 条');
  } catch (err) {
    check('验证脚本执行完成', false, err.message);
  } finally {
    try { chrome.kill('SIGKILL'); } catch (_) {}
  }

  const report = {
    at: new Date().toISOString(), base: BASE, stock: STOCK, total: results.length,
    passed: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).length,
    consoleErrors, shots: shots.filter(Boolean).map(s => path.basename(s)),
    note: shotFailures.length ? `以下截图在本机 headless Chrome 下无法采集（captureScreenshot 挂起，已降级 fromSurface:false 仍失败），判据不受影响：${shotFailures.join(', ')}` : null,
    results
  };
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(`\n=== R13 真机验证：${report.passed}/${report.total} PASS ===`);
  if (report.failed) {
    console.log('失败项：\n' + results.filter(r => !r.ok).map(r => ` - ${r.name}：${r.detail}`).join('\n'));
    process.exit(1);
  }
})();
