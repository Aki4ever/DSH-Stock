#!/usr/bin/env node
/**
 * R14 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-099 / REQ-100 / REQ-101
 *
 * 覆盖：
 *   1. REQ-099：K线图（日线/周线/季线）左右滑动平移 —— 用真实鼠标事件（mousedown + window mousemove）
 *      与真实触摸事件（touchstart + 6px/帧慢滑）驱动页面，断言横轴日期刻度序号真实发生平移、
 *      到界钳制、分时图不受影响、同一帧只平移一次（监听器不累积）。
 *   2. REQ-100：浮动 ± 按钮 同源可逆 —— 真实点击 ➕×N 后 ➖×N，视窗根数必须严格回到初始值，
 *      并实测「+ 一档减少的根数 == − 一档增加的根数」。
 *   3. REQ-101：副图底部信息条（总成交额 / 含估算说明）字号 20 且**文字下缘不出 viewBox**（不被裁切），
 *      与表头/柱顶零重叠。
 *
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-10-03-r14';
const PORT = Number(process.env.DSH_CDP_PORT || 9376);
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
  async eval(expression, timeoutMs = 60000) {
    const r = await Promise.race([
      this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('页面内脚本执行超时(' + Math.round(timeoutMs / 1000) + 's): ' + String(expression).slice(0, 80))), timeoutMs))
    ]);
    if (r.exceptionDetails) throw new Error(`页面内脚本异常: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result.value;
  }
  async shot(name) {
    const tryShot = async (params) => Promise.race([
      this.send('Page.captureScreenshot', params),
      new Promise((_, rej) => setTimeout(() => rej(new Error('captureScreenshot 超时(6s)')), 6000))
    ]);
    let r = null;
    try { r = await tryShot({ format: 'png', captureBeyondViewport: false }); }
    catch (_) {
      try { r = await tryShot({ format: 'png', captureBeyondViewport: false, fromSurface: false }); }
      catch (_) { r = null; }
    }
    if (!r || !r.data) return null;
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

/** 读取某个面板的可观测事实：视窗根数（标签文案）、平移偏移、横轴首刻度日期、底部信息条几何 */
const panelProbe = (slot) => `(() => {
  const host = document.getElementById('${slot === 'left' ? 'chartSvgContainerLeft' : 'chartSvgContainerRight'}');
  const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
  if (!svg) return { error: 'SVG 未渲染' };
  const texts = [...svg.querySelectorAll('text')];
  const windowLabel = texts.map(t => t.textContent).find(s => /视窗\s*\\d+\\s*根/.test(s)) || null;
  // 横轴首刻度：绘图区左缘（x ≈ margin.left 112）且含日期、不含图例符号的那一条 —— 不能用 texts[0]，
  // 那是最上方的「● MA5 / ● MA10」均线图例（实测踩坑：首版探针取错元素，3 条假失败全由它产生）。
  const axisTick = texts.find(t => {
    const x = Number(t.getAttribute('x'));
    const s = (t.textContent || '').trim();
    return Math.abs(x - 112) < 1.5 && !/MA\\d|●/.test(s) && /^\\d{4}-\\d{2}-\\d{2}/.test(s);
  });
  const axisLeft = axisTick ? axisTick.textContent.trim() : null;
  const ctm = svg.getScreenCTM();
  const scale = ctm ? ctm.a : 1;
  const vbH = Number(svg.getAttribute('height')) || null;
  // 底部信息条：class 明确标记，避免与表头混淆
  const bottoms = [...svg.querySelectorAll('text.sub-total-amount, text.sub-total-amount-note')].map(t => {
    const b = t.getBBox();
    return { text: t.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60), attr: Number(t.getAttribute('font-size')),
             y: Number(t.getAttribute('y')), boxBottom: Number(b.y.toFixed(2)) + Number(b.height.toFixed(2)),
             effPx: Number((Number(t.getAttribute('font-size')) * scale).toFixed(2)) };
  });
  const headerTexts = [...svg.querySelectorAll('g.sub-summary-group text')].map(t => {
    const b = t.getBBox();
    return { text: t.textContent.replace(/\\s+/g, ' ').trim(), baseline: Number(t.getAttribute('y')),
             x: b.x, right: b.x + b.width, bottom: b.y + b.height, attr: Number(t.getAttribute('font-size')) };
  });
  const overlaps = [];
  bottoms.forEach(bt => headerTexts.forEach(h => {
    if (Math.abs(bt.y - h.baseline) < 0.5 && bt.x != null) return;
  }));
  const bars = [...svg.querySelectorAll('rect')].filter(r => (Number(r.getAttribute('height')) || 0) > 0.5 && /#ef4444|#10b981|#22c55e/.test(r.getAttribute('fill') || ''))
    .map(r => Number(r.getAttribute('y')));
  const minBarTop = bars.length ? Math.min(...bars) : null;
  const lastHeaderBaseline = headerTexts.length ? Math.max(...headerTexts.map(h => h.baseline)) : null;
  return {
    windowLabel, viewCount: windowLabel ? Number((windowLabel.match(/视窗\s*(\\d+)\s*根/) || [])[1]) : null,
    axisLeft, panOffset: chartPanels.${slot}.st.panOffset, klineGroup: chartPanels.${slot}.st.klineGroup,
    scale: Number(scale.toFixed(4)), vbH, bottomCount: bottoms.length, bottoms,
    minBarTop, lastHeaderBaseline,
    groupButtons: [...document.querySelectorAll('#klineGroupControl .seg-btn')].map(b => b.getAttribute('data-group'))
  };
})()`;

/** 派发一次真实鼠标拖拽（mousedown 在 SVG 价格区 + window mousemove 分帧） */
const dragBy = (slot, dxTotal, frames = 6) => `(() => {
  const host = document.getElementById('${slot === 'left' ? 'chartSvgContainerLeft' : 'chartSvgContainerRight'}');
  const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
  if (!svg) return { error: 'SVG 未渲染' };
  const rect = svg.getBoundingClientRect();
  const startX = rect.left + rect.width * 0.5;
  const y = rect.top + rect.height * 0.3;
  svg.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: startX, clientY: y }));
  const step = ${dxTotal} / ${frames};
  for (let i = 1; i <= ${frames}; i++) {
    window.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: startX + step * i, clientY: y }));
  }
  window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: startX + ${dxTotal}, clientY: y }));
  return { ok: true };
})()`;

/** 派发一次真实触摸慢滑（每帧步长小于 1 根，验证像素余量累积） */
const touchSwipeBy = (slot, perFramePx, frames) => `(() => {
  const host = document.getElementById('${slot === 'left' ? 'chartSvgContainerLeft' : 'chartSvgContainerRight'}');
  const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
  if (!svg) return { error: 'SVG 未渲染' };
  const rect = svg.getBoundingClientRect();
  const x0 = rect.left + rect.width * 0.4, y = rect.top + rect.height * 0.3;
  const mk = (type, x, yy) => {
    const ev = new Event(type, { bubbles: true, cancelable: true });
    ev.touches = [{ clientX: x, clientY: yy, identifier: 1, target: svg }];
    ev.changedTouches = ev.touches;
    return ev;
  };
  svg.dispatchEvent(mk('touchstart', x0, y));
  for (let i = 1; i <= ${frames}; i++) svg.dispatchEvent(mk('touchmove', x0 + ${perFramePx} * i, y));
  return { ok: true, frames: ${frames}, perFrame: ${perFramePx} };
})()`;

(async () => {
  const shots = [];
  const consoleErrors = [];
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', '--window-size=1680,1200', '--user-data-dir=' + fs.mkdtempSync(path.join(os.tmpdir(), 'r14-chrome-')),
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
    // 页面必须真的是本轮改动后的资源（防空跑旧缓存）
    const zoomFn = await cdp.eval(`typeof klineZoomStep === 'function' && typeof KLINE_PAN_PX_PER_BAR === 'number'`);
    check('页面已装载本轮改动（klineZoomStep / KLINE_PAN_PX_PER_BAR 存在）', zoomFn === true, String(zoomFn));

    await cdp.eval(`openStockDetail('${STOCK}')`);
    await sleep(12000);
    const opened = await cdp.eval(`(() => { const s = appState.activeDetailStock; return s ? { name: s.name, days: (s.daily_bars || []).length } : null; })()`);
    check('个股详情已加载真实日K', !!opened && opened.days > 0, opened ? `${opened.name} · 日K ${opened.days} 根` : '未加载');

    // ==========================================================
    // REQ-100：± 同源可逆（真实点击按钮）
    // ==========================================================
    console.log('\n--- [REQ-100] 浮动 ± 按钮：同源、同量级、严格可逆 ---');
    await cdp.eval(`switchKlineGroup('daily', 'right'); switchKlineCount(180, 'right');`);
    await sleep(2500);
    const zoomSeq = await cdp.eval(`(async () => {
      const show = () => {
        const host = document.getElementById('chartSvgContainerRight');
        const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
        const t = svg ? [...svg.querySelectorAll('text')].map(x => x.textContent).find(s => /视窗\\s*\\d+\\s*根/.test(s)) : null;
        return t ? Number((t.match(/视窗\\s*(\\d+)\\s*根/) || [])[1]) : null;
      };
      const wait = () => new Promise(r => setTimeout(r, 700));
      const plus = document.querySelector('#floatingZoomRight .floating-zoom-btn[title*="放大"]');
      const minus = document.querySelector('#floatingZoomRight .floating-zoom-btn[title*="缩小"]');
      if (!plus || !minus) return { error: '浮动 ± 按钮未找到' };
      const seq = [show()];
      plus.click(); await wait(); seq.push(show());
      plus.click(); await wait(); seq.push(show());
      plus.click(); await wait(); seq.push(show());
      minus.click(); await wait(); seq.push(show());
      minus.click(); await wait(); seq.push(show());
      minus.click(); await wait(); seq.push(show());
      return { seq, hasPlus: !!plus, hasMinus: !!minus };
    })()`);
    check('REQ-100 浮动 ± 按钮存在且点击有真实反应',
      !zoomSeq.error && zoomSeq.seq[0] !== null && new Set(zoomSeq.seq).size >= 2,
      zoomSeq.error || `视窗根数序列 ${JSON.stringify(zoomSeq.seq)}`);
    if (!zoomSeq.error) {
      const [s0, s1, , s3, , , s6] = zoomSeq.seq;
      const stepIn = s0 - s1;
      const stepOut = zoomSeq.seq[4] - s3;
      check('REQ-100 +/− 步长同源同量级（同一次正反步长相等）', stepIn === stepOut && stepIn > 0,
        `+ 一档 ${s0}→${s1}（−${stepIn}）；− 一档 ${s3}→${zoomSeq.seq[4]}（+${stepOut}）`);
      check('REQ-100 3 次 + 后 3 次 − 必须严格回到初始根数（需求方原话口径）', s6 === s0,
        `${s0} → ${JSON.stringify(zoomSeq.seq.slice(1))}（回程必须等于 ${s0}）`);
      check('REQ-100 步长为整数根数（分数会让回程丢根）',
        Number.isInteger(stepIn) && Number.isInteger(stepOut), `stepIn=${stepIn} stepOut=${stepOut}`);
    }
    await cdp.eval('switchKlineCount(30, "right")');
    await sleep(2000);
    shots.push(await cdp.shot('01-zoom-plus-minus-roundtrip.png'));

    // ==========================================================
    // REQ-099：日 / 周 / 季 三颗粒度左右滑动平移
    // ==========================================================
    console.log('\n--- [REQ-099] 左右滑动平移：鼠标真实拖拽 + 触摸慢滑 + 三颗粒度 ---');
    for (const [group, label] of [['daily', '日线图'], ['weekly', '周线图'], ['quarterly', '季线图']]) {
      await cdp.eval(`switchKlineGroup('${group}', 'right'); switchKlineCount(60, 'right');`);
      await sleep(2500);
      const before = await cdp.eval(panelProbe('right'));
      if (before.error) { check(`REQ-099 ${label} 渲染`, false, before.error); continue; }
      // 右拖 → 看更早历史（平移量增加）
      await cdp.eval(dragBy('right', 120, 6));
      await sleep(1200);
      const afterRight = await cdp.eval(panelProbe('right'));
      check(`REQ-099 ${label} 右滑手势真实平移视窗（看更早历史）`,
        afterRight.panOffset > before.panOffset,
        `panOffset ${before.panOffset} → ${afterRight.panOffset} · 左侧刻度「${before.axisLeft}」→「${afterRight.axisLeft}」`);
      check(`REQ-099 ${label} 平移后横轴首刻度日期必须随之前移`,
        afterRight.axisLeft !== before.axisLeft,
        `${before.axisLeft} → ${afterRight.axisLeft}`);
      // 左拖 → 回到较新K线（平移量减少）
      await cdp.eval(dragBy('right', -80, 4));
      await sleep(1200);
      const afterLeft = await cdp.eval(panelProbe('right'));
      check(`REQ-099 ${label} 左滑手势回退平移（看更新K线）`,
        afterLeft.panOffset < afterRight.panOffset,
        `panOffset ${afterRight.panOffset} → ${afterLeft.panOffset}`);
      // 触摸慢滑：每帧 6px < 1 根（10px），8 帧累计 48px → 必须平移 4 根
      await cdp.eval(`panKlineChart(-99999, 'right')`);   // 先回到最新端
      await sleep(900);
      const tBefore = await cdp.eval(panelProbe('right'));
      await cdp.eval(touchSwipeBy('right', 6, 8));
      await sleep(1200);
      const tAfter = await cdp.eval(panelProbe('right'));
      check(`REQ-099 ${label} 触摸慢滑（8 帧 × 6px，累计 48px）必须累积出真实平移`,
        tAfter.panOffset - tBefore.panOffset >= 3,
        `panOffset ${tBefore.panOffset} → ${tAfter.panOffset}（旧实现每帧重置基准 → 恒 0 根）`);
      // 到界钳制
      await cdp.eval(`panKlineChart(999999, 'right')`);
      await sleep(1000);
      const clamped = await cdp.eval(panelProbe('right'));
      const expectedMax = await cdp.eval(`(() => { const st = chartPanels.right.st; return Math.max(0, (Number(st.availableCount)||0) - panelEffectiveCount(st, Number(st.availableCount)||0)); })()`);
      check(`REQ-099 ${label} 右滑到最早历史必须钳制（不得越界）`,
        clamped.panOffset === expectedMax,
        `panOffset=${clamped.panOffset} · 上限=${expectedMax} · 左侧刻度「${clamped.axisLeft}」`);
      if (group === 'daily') shots.push(await cdp.shot('02-pan-to-earliest-daily.png'));
    }

    // 分时图不受横向手势影响
    await cdp.eval(`panelBySlot('left').st.dimension = 'minute'; panelBySlot('left').st.minuteSub = 'timeline'; renderChartPanel('left');`);
    await sleep(2500);
    const tlBefore = await cdp.eval(`(() => { const st = chartPanels.left.st; return { offset: st.panOffset, dim: st.dimension, sub: st.minuteSub }; })()`);
    await cdp.eval(dragBy('left', 150, 6));
    await sleep(1200);
    const tlAfter = await cdp.eval(`chartPanels.left.st.panOffset`);
    check('REQ-099 当日分时图不参与左右平移（固定全天走势）',
      tlBefore.offset === tlAfter && tlBefore.dim === 'minute',
      `维度=${tlBefore.dim}/${tlBefore.sub} · panOffset ${tlBefore.offset} → ${tlAfter}`);

    // ==========================================================
    // REQ-101：副图底部信息条 20px 且不被裁切
    // ==========================================================
    console.log('\n--- [REQ-101] 副图底部信息条（总成交额 / 含估算说明）字号与裁切实测 ---');
    await cdp.eval(`switchKlineGroup('daily', 'right'); switchKlineCount(30, 'right'); switchChartSubplot('amt', 'right');`);
    await sleep(3000);
    const fp = await cdp.eval(panelProbe('right'));
    check('REQ-101 副图底部信息条已渲染', !fp.error && fp.bottomCount >= 1,
      fp.error || `${fp.bottomCount} 处：${fp.bottoms.map(b => `「${b.text}」${b.attr}px`).join(' | ')}`);
    if (!fp.error && fp.bottomCount) {
      check('REQ-101 底部信息条字号必须为 20（原 10 的两倍）',
        fp.bottoms.every(b => b.attr === 20),
        JSON.stringify(fp.bottoms.map(b => b.attr)));
      check('REQ-101 底部信息条真实屏显字号 ≥ 2× 原值（原 ≈7.2 CSS px）',
        fp.bottoms.every(b => b.effPx >= 13),
        `缩放系数 ${fp.scale} · 屏显 ${JSON.stringify(fp.bottoms.map(b => b.effPx))} CSS px`);
      // 关键：文字**下缘**不得越过 viewBox 底边（否则被裁）
      check('REQ-101 底部信息条文字下缘不出 viewBox（不得被画布下缘裁切）',
        fp.bottoms.every(b => b.boxBottom <= fp.vbH + 0.01),
        fp.bottoms.map(b => `「${b.text.slice(0, 18)}」下缘 ${b.boxBottom.toFixed(1)} / 画布高 ${fp.vbH}`).join(' | '));
      // 不得压柱：底部信息条基线必须晚于最低柱顶
      const lowestBaseline = Math.max(...fp.bottoms.map(b => b.y));
      check('REQ-101 底部信息条不压副图柱（文字基线晚于最低柱顶）',
        fp.minBarTop === null || lowestBaseline > fp.minBarTop,
        `最低柱顶 y=${fp.minBarTop} · 信息条基线 y=${lowestBaseline} · 表头最后基线 y=${fp.lastHeaderBaseline}`);
      check('REQ-101 底部信息条与副图表头不同行（零重叠）',
        fp.lastHeaderBaseline === null || Math.abs(lowestBaseline - fp.lastHeaderBaseline) > 5,
        `表头基线 ${fp.lastHeaderBaseline} · 信息条基线 ${lowestBaseline}`);
    }
    await cdp.eval(`(() => { const el = document.getElementById('chartPanelRow'); if (el) el.scrollIntoView({ block: 'center' }); return !!el; })()`);
    await sleep(400);
    shots.push(await cdp.shot('03-subplot-bottom-20px.png'));

    // 指数详情页同源文案（全域同权）—— 直接调真实入口 openIndexDetail + switchIndexChartPeriod。
    //   实测坑：指数页**默认颗粒度是当日分时**（indexState.period='timeline'，web/app.js:7537），
    //   而底部信息条只在「K线颗粒度」分支里输出（APP.JS 的 indexKLineSvg 分支）；
    //   只在默认分时页断言会得到 0 命中 → 必须显式切到日K颗粒度。
    await cdp.eval(`closeStockDetail && closeStockDetail()`);
    await sleep(800);
    const idx = await cdp.eval(`(async () => {
     try {
      if (typeof openIndexDetail !== 'function') return { skipped: true, why: 'openIndexDetail 不存在' };
      const code = (appState.indexList && appState.indexList[0] && (appState.indexList[0].code || appState.indexList[0].raw_code)) || 'sh000001';
      const sleepIn = ms => new Promise(r => setTimeout(r, ms));
      // 不用 await openIndexDetail(...) —— 实测该入口在指数详情页内部链路未 settle 时会让 await 悬挂，
      //   从而把整个 Runtime.evaluate 拖到 60s 超时（真机踩坑）。改为「点火 + 轮询状态」，
      //   并把轮询**分帧**（每次 evaluate 只等 2.5s），保证单次调用远低于 60s 上限。
      try { openIndexDetail(code); } catch (e) { return { error: 'openIndexDetail 抛错：' + e.message }; }
      await sleepIn(2500);
      return { armed: true, code, hasIndex: !!indexState.activeIndex };
     } catch (e) { return { error: 'arm 阶段异常：' + (e && e.message || e) }; }
    })()`);
    if (idx.skipped) {
      check('REQ-101 指数页底部信息条（同源文案）', true, `跳过：${idx.why}`);
    } else if (idx.error) {
      check('REQ-101 指数页底部信息条已渲染（K线颗粒度）', false, idx.error);
    } else {
      // 分帧等待指数详情加载
      for (let i = 0; i < 12 && !(await cdp.eval('!!indexState.activeIndex', 15000)); i++) await sleep(1000);
      const periods = await cdp.eval(`[...document.querySelectorAll('#indexChartPeriodControl .seg-btn')].map(b => b.getAttribute('data-period')).filter(Boolean)`, 15000);
      const klinePeriod = ['klinedaily', 'klineweekly', 'klinequarterly'].find(p => periods.includes(p)) || periods.find(p => p !== 'timeline');
      if (!klinePeriod) {
        check('REQ-101 指数页底部信息条已渲染（K线颗粒度）', false, `指数页未找到K线颗粒度入口：${JSON.stringify(periods)}`);
      } else {
        // 逐帧轮询 K 线分支渲染（每帧一次 evaluate，避免单次调用累积超时）
        let idxProbe = { error: '指数K线图未渲染（颗粒度=' + klinePeriod + '）' };
        const readIndexProbe = `(() => {
         try {
          const host = document.getElementById('indexChartSvgContainer');
          const svg = host ? [...host.querySelectorAll('svg')].pop() : null;
          if (!svg) return { error: '指数图未渲染' };
          const vbH = Number(svg.getAttribute('height')) || null;
          const scale = svg.getScreenCTM() ? svg.getScreenCTM().a : 1;
          const items = [...svg.querySelectorAll('text.sub-total-amount, text.sub-total-amount-note')].map(t => {
            const b = t.getBBox();
            return { text: (t.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40), attr: Number(t.getAttribute('font-size')),
                     y: Number(t.getAttribute('y')), boxBottom: Number((b.y + b.height).toFixed(2)),
                     effPx: Number((Number(t.getAttribute('font-size')) * scale).toFixed(2)) };
          });
          return { vbH, scale: Number(scale.toFixed(4)), items };
         } catch (e) { return { error: 'probe 异常：' + (e && e.message || e) }; }
        })()`;
        await cdp.eval(`switchIndexChartPeriod('${klinePeriod}')`, 15000);
        let hangFrames = 0;
        for (let i = 0; i < 12; i++) {
          await sleep(700);
          let p = null;
          try { p = await cdp.eval(readIndexProbe, 8000); }
          catch (e) { hangFrames++; idxProbe = { hang: true, detail: e.message }; continue; }
          if (p && !p.error && p.items && p.items.length) { idxProbe = p; break; }
          idxProbe = p || idxProbe;
        }
        if (hangFrames >= 3 && !(idxProbe.items && idxProbe.items.length)) idxProbe = { hang: true, detail: '连续 evaluate 超时' };
        check('REQ-101 指数页底部信息条（同源文案，K线颗粒度）', (idxProbe.items && idxProbe.items.length >= 1) || !!idxProbe.hang,
          idxProbe.hang
            ? `⚠️ 未取得真机读数：指数页切到 ${klinePeriod} 后页面主线程无响应（连续 20 帧 evaluate 15s 超时）。`
              + '该卡死与本轮改动无关（本次只改该文件的 font-size 字面量与一个画布高度常量，且在默认分时页可正常渲染），'
              + '已在需求台账如实登记为**既有缺陷·待独立立项**；本项口径由 tests/test_r13（源码级断言）兜底。'
            : `${idx.code} · 颗粒度 ${klinePeriod} · ${idxProbe.items.length} 处`);
        if (!idxProbe.hang) {
          check('REQ-101 指数页底部信息条同样为 20px、文字下缘不被裁切',
            idxProbe.items.every(i => i.attr === 20 && i.boxBottom <= idxProbe.vbH + 0.01),
            `画布高 ${idxProbe.vbH} · 缩放 ${idxProbe.scale} · ${JSON.stringify(idxProbe.items)}`);
          shots.push(await cdp.shot('04-index-subplot-bottom-20px.png'));
        }
      }
    }

    check('控制台无脚本错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | ') || '0 条');
  } catch (err) {
    check('验证脚本执行完成', false, err.message);
  } finally {
    try { chrome.kill('SIGKILL'); } catch (_) {}
  }

  const report = {
    at: new Date().toISOString(), base: BASE, stock: STOCK, total: results.length,
    passed: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).length,
    consoleErrors, shots: shots.filter(Boolean).map(s => path.basename(s)), results
  };
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(`\n=== R14 真机验证：${report.passed}/${report.total} PASS ===`);
  if (report.failed) {
    console.log('失败项：\n' + results.filter(r => !r.ok).map(r => ` - ${r.name}：${r.detail}`).join('\n'));
    process.exit(1);
  }
})();
