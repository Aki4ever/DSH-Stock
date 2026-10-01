#!/usr/bin/env node
/**
 * R07 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-037/038/039/040
 * 覆盖：
 *   1. REQ-037（口径已修订）：副图控件合并为唯一「幅图联动」控件，首屏两图统一默认「成交额」并与控件高亮一致；
 *      手动选择后两图联动同步、且不被颗粒度/子Tab切换改写；
 *      用户手动选择后不再被自动改写
 *   2. REQ-038：双图模式下工具区间固定高度（264px），两个面板的图表区绝对同高（top 差值＝0），
 *      内容不足处留白、内容超出时容器内部滚动
 *   3. REQ-039：画线工具新增分组标题栏「压力线」（自动线控件之前）与「缠论相关」（缠论画线之前）
 *   4. REQ-040：缠论三类买卖点开关（买点1-3/卖点1-3），选 3 即同时画出第 1、2、3 类；
 *      图上标记数量必须与后端 analyze_bars 的真实返回逐类一致，判定依据可核对
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-23-r07';
const PORT = Number(process.env.DSH_CDP_PORT || 9370);
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
 * 副图探针：读取统一幅图控件的当前档位 + 该面板实际渲染出的副图标题。
 * 口径修订（2026-09-24，REQ-037 演进）：左右面板原先各有独立控件（chartSubPlotControlLeft/Right），
 * 现按产品需求合并为**唯一**的「幅图联动」控件 `#chartSubPlotControlUnified`——单点切换、两图同步。
 * 因此 active 档位取自该统一控件，面板侧只断言「实际渲染出的副图标题」与之一致。
 */
function subplotProbe(slot) {
  return `(() => {
    const activeBtn = document.querySelector('#chartSubPlotControlUnified .seg-btn.active');
    const allActive = [...document.querySelectorAll('[data-subplot].active')].map(b => b.getAttribute('data-subplot'));
    const controls = [...document.querySelectorAll('.segmented-control')].filter(c => c.querySelector('[data-subplot]'));
    const host = document.getElementById('chartSvgContainer${slot === 'left' ? 'Left' : 'Right'}');
    const text = host ? host.textContent.replace(/\\s+/g, ' ') : '';
    return {
      active: activeBtn ? activeBtn.getAttribute('data-subplot') : null,
      allActive: allActive,
      controlCount: controls.length,
      controlIds: controls.map(c => c.id || '(无id)'),
      title: (text.match(/副图：[^ ]{0,16}/) || [''])[0].trim(),
      hasAmt: text.includes('副图：成交额'),
      hasVol: text.includes('副图：成交量')
    };
  })()`;
}

/** 买卖点探针：按钮状态 + 图上实际标记数量 */
const bsProbe = `(() => {
  const counts = {};
  for (const t of ['buy1','buy2','buy3','sell1','sell2','sell3']) {
    counts[t] = document.querySelectorAll('#chartSvgContainerRight .chanlun-' + t).length;
  }
  const buttons = {};
  for (const t of ['buy1','buy2','buy3','sell1','sell2','sell3']) {
    const cap = t.charAt(0).toUpperCase() + t.slice(1);
    const btn = document.getElementById('btnBs' + cap + '_right');
    buttons[t] = btn ? { active: btn.classList.contains('active'), count: Number(btn.dataset.count || -1), empty: btn.classList.contains('bs-level-empty'), title: btn.getAttribute('title') || '' } : null;
  }
  const marks = [...document.querySelectorAll('#chartSvgContainerRight .chanlun-bs text')].map(t => t.textContent.trim());
  const tip = document.querySelector('#chartSvgContainerRight .chanlun-bs title');
  return { counts, buttons, marks, tip: tip ? tip.textContent.trim() : '' };
})()`;

/** 页面内期望值：后端真实返回的买卖点中，落在「当前实际渲染视窗」日期范围内的分类计数。
 *  视窗数据必须用 panelWindowBars 取，与画图所用数据完全同源，否则期望值与实际渲染不可比。 */
const expectProbe = `(() => {
  const stock = appState.activeDetailStock;
  const analysis = (stock && stock.chanlun) || null;
  if (!analysis) return { error: '未获取缠论分析' };
  const sDate = document.getElementById('klineStartDate').value;
  const eDate = document.getElementById('klineEndDate').value;
  let all = panelAvailableBars(stock, chartPanels.right.st);
  if (sDate || eDate) all = all.filter(k => (!sDate || k.date >= sDate) && (!eDate || k.date <= eDate));
  const win = panelWindowBars(all, chartPanels.right.st);
  const bars = win.bars.map(b => b.date);
  const start = bars[0], end = bars[bars.length - 1];
  const inRange = p => p.time >= start && p.time <= end;
  const pts = (analysis.buy_sell_points || []).filter(inRange);
  const counts = {};
  for (const t of ['buy1','buy2','buy3','sell1','sell2','sell3']) counts[t] = 0;
  pts.forEach(p => { if (counts[p.type] !== undefined) counts[p.type]++; });
  return { counts, total: pts.length, start, end, windowBars: bars.length, available: all.length, allCounts: analysis.counts };
})()`;

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-r07-chrome-'));
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

    // ---------- 打开真实个股详情 ----------
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(9000);
    const opened = await cdp.eval(`(() => { const s = appState.activeDetailStock; return s ? { name: s.name, days: (s.daily_bars || []).length, bs: ((s.chanlun || {}).buy_sell_points || []).length } : null; })()`);
    check('个股详情已加载真实历史与缠论买卖点', !!opened && opened.days > 0 && opened.bs > 0,
      opened ? `${opened.name} · 日K ${opened.days} 根 · 买卖点 ${opened.bs} 个` : '未加载');

    // ---------- REQ-037：K线形态图默认副图＝成交额 ----------
    let sub = await cdp.eval(subplotProbe('right'));
    check('REQ-037 K线图默认副图＝成交额(亿元)', sub.active === 'amt', `active=${sub.active} · ${sub.title}`);
    check('REQ-037 K线图实际渲染的副图标题＝成交额', sub.hasAmt && !sub.hasVol, sub.title);
    check('REQ-037 默认档位在页面唯一高亮（幅图联动控件：成交额）',
      sub.allActive.length === 1 && sub.allActive[0] === 'amt', `高亮档位 ${sub.allActive.join(',')}`);

    // ---------- REQ-039：分组标题栏 ----------
    // 用 DOM 文档顺序判断分组标题与其控件的前后关系（标题被包在 .chart-tool-group 内，不能用直接子元素索引）
    const pos = (panelId, ctrlId) => `(() => {
      const titles = [...document.querySelectorAll('#${panelId} .chart-group-title')];
      const ctrl = document.getElementById('${ctrlId}');
      const before = (a, b) => !!a && !!b && !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      return {
        titles: titles.map(t => t.textContent.trim()),
        before: titles.map(t => before(t, ctrl)),
        sameGroup: titles.map(t => { const g = t.closest('.chart-tool-group'); return !!(g && ctrl && g.contains(ctrl)); })
      };
    })()`;
    const groups = await cdp.eval(pos('chartPanelRight', 'autoLinesCountControl_right'));
    const chanlunPos = await cdp.eval(pos('chartPanelRight', 'btnChanlunDraw_right'));
    const leftGroups = await cdp.eval(`[...document.querySelectorAll('#chartPanelLeft .chart-group-title')].map(e => e.textContent.trim())`);
    check('REQ-039 分组标题栏「压力线」「缠论相关」已出现', groups.titles.length === 2, groups.titles.join(' | '));
    check('REQ-039「压力线」位于自动线控件之前且同组', groups.before[0] && groups.sameGroup[0],
      `压力线 在自动线之前=${groups.before[0]} · 同组=${groups.sameGroup[0]}`);
    check('REQ-039「缠论相关」位于缠论画线按钮之前且同组', chanlunPos.before[1] && chanlunPos.sameGroup[1],
      `缠论相关 在缠论画线之前=${chanlunPos.before[1]} · 同组=${chanlunPos.sameGroup[1]}`);
    check('REQ-039 分时图面板同样具备两个分组标题栏', leftGroups.join(',') === '压力线,缠论相关', leftGroups.join(' | '));
    const sameRow = await cdp.eval(`(() => {
      const check = (panelId, titleIdx, ctrlId) => {
        const title = [...document.querySelectorAll('#' + panelId + ' .chart-group-title')][titleIdx];
        const ctrl = document.getElementById(ctrlId);
        if (!title || !ctrl) return null;
        const a = title.getBoundingClientRect(), b = ctrl.getBoundingClientRect();
        return { rowDiff: Math.abs(a.top - b.top), titleTop: Math.round(a.top), ctrlTop: Math.round(b.top),
                 titleH: +a.height.toFixed(1), ctrlH: +b.height.toFixed(1),
                 centerDiff: Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)),
                 overlap: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) };
      };
      return { pressure: check('chartPanelLeft', 0, 'autoLinesCountControl_left'), chanlun: check('chartPanelLeft', 1, 'btnChanlunDraw_left') };
    })()`);
    // 需求REQ-039：「同一行」的准确判定＝两元素垂直中心线对齐且垂直区间有重叠。
    // 标题 span 与按钮/分段控件的高度天然不同（实测 22.5px vs 30.9/37.4px），
    // 直接比 top 会把「flex 居中同行的正常高度差」误判成换行错位；
    // 旧断言在左面板默认隐藏时取到的矩形恒为 0，属假通过，REQ-045 让左图默认可见后才暴露，故按真实几何修正口径。
    check('REQ-039 分组标题与其控件处于同一行（中心线对齐、未被换行拆散）',
      sameRow.pressure && sameRow.pressure.centerDiff < 1 && sameRow.pressure.overlap > 0
        && sameRow.chanlun && sameRow.chanlun.centerDiff < 1 && sameRow.chanlun.overlap > 0,
      `压力线 中心差 ${sameRow.pressure && sameRow.pressure.centerDiff.toFixed(2)}px · 垂直重叠 ${sameRow.pressure && sameRow.pressure.overlap.toFixed(1)}px`
      + `（标题高 ${sameRow.pressure && sameRow.pressure.titleH} vs 控件高 ${sameRow.pressure && sameRow.pressure.ctrlH}，top 差 ${sameRow.pressure && sameRow.pressure.rowDiff.toFixed(1)}px 属高度差）`
      + ` · 缠论相关 中心差 ${sameRow.chanlun && sameRow.chanlun.centerDiff.toFixed(2)}px · 垂直重叠 ${sameRow.chanlun && sameRow.chanlun.overlap.toFixed(1)}px`);

    // ---------- REQ-040：六个买卖点按钮 ----------
    const btns = await cdp.eval(`(() => {
      const r = {}, l = {};
      for (const t of ['buy1','buy2','buy3','sell1','sell2','sell3']) {
        const cap = t.charAt(0).toUpperCase() + t.slice(1);
        r[t] = !!document.getElementById('btnBs' + cap + '_right');
        l[t] = !!document.getElementById('btnBs' + cap + '_left');
      }
      return { right: r, left: l };
    })()`);
    check('REQ-040 两个面板各新增买点1/2/3、卖点1/2/3 六个开关',
      Object.values(btns.right).every(Boolean) && Object.values(btns.left).every(Boolean),
      `${Object.values(btns.right).filter(Boolean).length}/6(右) · ${Object.values(btns.left).filter(Boolean).length}/6(左)`);

    // ---------- REQ-040：把日期区间收敛到含买卖点的真实区间 ----------
    await cdp.eval(`(() => {
      document.getElementById('klineStartDate').value = '2008-09-01';
      document.getElementById('klineEndDate').value = '2010-01-31';
      applyKlineCustomDateRange();
    })()`);
    await sleep(2500);
    await cdp.eval(`switchKlineGroup('daily'); showAllKlineBars('right')`);
    await sleep(2000);
    const expect = await cdp.eval(expectProbe);
    check('区间内六类买卖点齐全，可逐类验证', !expect.error && expect.total > 0 && ['buy1','buy2','buy3','sell1','sell2','sell3'].every(t => expect.counts[t] > 0),
      expect.error || `${expect.start}~${expect.end}（视窗 ${expect.windowBars}/${expect.available} 根）共 ${expect.total} 个：买1 ${expect.counts.buy1}／买2 ${expect.counts.buy2}／买3 ${expect.counts.buy3}／卖1 ${expect.counts.sell1}／卖2 ${expect.counts.sell2}／卖3 ${expect.counts.sell3}`);

    // ---------- REQ-041（取代 REQ-040 的「默认等级 0」口径）：进入详情即自动标记六类买卖点 ----------
    let bs = await cdp.eval(bsProbe);
    check('REQ-041 默认即自动标记六类买卖点（买点1/2/3 + 卖点1/2/3 全部开启）',
      ['buy1','buy2','buy3','sell1','sell2','sell3'].every(t => bs.buttons[t] && bs.buttons[t].active),
      ['buy1','buy2','buy3','sell1','sell2','sell3'].map(t => `${t}=${bs.buttons[t] && bs.buttons[t].active}`).join(' '));
    check('REQ-041 默认状态下六类标记全部画出，且与后端判定逐类一致',
      ['buy1','buy2','buy3','sell1','sell2','sell3'].every(t => bs.counts[t] === expect.counts[t]),
      `图上 ${JSON.stringify(bs.counts)} · 后端 ${JSON.stringify(expect.counts)}`);

    // ---------- REQ-040 原始意图仍成立：按钮就是显隐开关（先全部关闭，再验证累积语义） ----------
    await cdp.eval(`toggleChartBsLevel('buy', 3, 'right'); toggleChartBsLevel('sell', 3, 'right')`);
    await sleep(1500);
    const bsOff = await cdp.eval(bsProbe);
    check('REQ-041 六个等级按钮仍可临时关闭（关闭后不残留任何标记）',
      Object.values(bsOff.counts).every(n => n === 0) && !bsOff.buttons.buy1.active && !bsOff.buttons.sell1.active,
      JSON.stringify(bsOff.counts));

    // ---------- REQ-040：选「买点3」＝同时画出 1、2、3 类 ----------
    await cdp.eval(`toggleChartBsLevel('buy', 3, 'right')`);
    await sleep(1500);
    bs = await cdp.eval(bsProbe);
    const expectBuy3 = expect.counts.buy1 + expect.counts.buy2 + expect.counts.buy3;
    const gotBuy3 = bs.counts.buy1 + bs.counts.buy2 + bs.counts.buy3;
    check('REQ-040 选「买点3」时三个买点按钮同时点亮（累积语义）',
      bs.buttons.buy1.active && bs.buttons.buy2.active && bs.buttons.buy3.active && !bs.buttons.sell1.active,
      `买1/2/3 active=${bs.buttons.buy1.active}/${bs.buttons.buy2.active}/${bs.buttons.buy3.active}，卖1 active=${bs.buttons.sell1.active}`);
    check('REQ-040 选「买点3」＝同时画出买点1、2、3（数量与后端逐类一致）',
      gotBuy3 === expectBuy3 && bs.counts.buy1 === expect.counts.buy1 && bs.counts.buy2 === expect.counts.buy2 && bs.counts.buy3 === expect.counts.buy3,
      `图上 1买=${bs.counts.buy1} 2买=${bs.counts.buy2} 3买=${bs.counts.buy3}；后端一致`);
    check('REQ-040 仅显示买点时不得出现卖点标记',
      bs.counts.sell1 + bs.counts.sell2 + bs.counts.sell3 === 0,
      `卖点合计 ${bs.counts.sell1 + bs.counts.sell2 + bs.counts.sell3}`);

    shots.push(await cdp.shot('01-buy3-cumulative.png'));

    // ---------- REQ-040：降级到「买点1」只保留第一类 ----------
    await cdp.eval(`toggleChartBsLevel('buy', 1, 'right')`);
    await sleep(1200);
    bs = await cdp.eval(bsProbe);
    check('REQ-040 改选「买点1」＝只画出第一类买点',
      bs.counts.buy1 === expect.counts.buy1 && bs.counts.buy2 === 0 && bs.counts.buy3 === 0,
      `1买=${bs.counts.buy1}（后端 ${expect.counts.buy1}）· 2买=${bs.counts.buy2} · 3买=${bs.counts.buy3}`);

    // ---------- REQ-040：卖点独立（选卖点2） ----------
    await cdp.eval(`toggleChartBsLevel('sell', 2, 'right')`);
    await sleep(1200);
    bs = await cdp.eval(bsProbe);
    check('REQ-040 卖点开关独立于点且同样累积（选卖点2＝卖点1+2）',
      bs.counts.sell1 === expect.counts.sell1 && bs.counts.sell2 === expect.counts.sell2 && bs.counts.sell3 === 0,
      `卖1=${bs.counts.sell1} 卖2=${bs.counts.sell2} 卖3=${bs.counts.sell3}（后端 ${expect.counts.sell1}/${expect.counts.sell2}）`);

    // ---------- REQ-040：买卖点同时开启时的标记文本与判定依据 ----------
    bs = await cdp.eval(bsProbe);
    check('REQ-040 买卖点可同时显示（买点1 + 卖点1、2）',
      bs.counts.buy1 === expect.counts.buy1 && bs.counts.sell1 === expect.counts.sell1 && bs.counts.sell2 === expect.counts.sell2,
      `1买=${bs.counts.buy1} 1卖=${bs.counts.sell1} 2卖=${bs.counts.sell2}`);
    const openedExpected = expect.counts.buy1 + expect.counts.sell1 + expect.counts.sell2;
    check('REQ-040 标记文本标注类别（1买/2买/1卖…）',
      bs.marks.length === openedExpected && bs.marks.every(m => /^[123][买卖]\??$/.test(m)),
      `已开启等级应显示 ${openedExpected} 个，实际 ${bs.marks.length} 个：${bs.marks.join(' ')}`);
    check('REQ-040 标记附带可核对的缠论判定依据（含中枢/背驰/MACD 数值）',
      /判定依据/.test(bs.tip) && /(中枢|趋势背驰|MACD)/.test(bs.tip), bs.tip.slice(0, 100));

    // ---------- REQ-040：按钮计数与后端一致（诚实计数） ----------
    const countsFromApi = expect.allCounts || {};
    const countMatch = ['buy1','buy2','buy3','sell1','sell2','sell3'].every(t => bs.buttons[t] && bs.buttons[t].count === countsFromApi[t]);
    check('REQ-040 按钮上标注的识别数量＝后端全部历史识别数量（与视窗无关，诚实计数）',
      countMatch, ['buy1','buy2','buy3','sell1','sell2','sell3'].map(t => `${t}:${bs.buttons[t] ? bs.buttons[t].count : '?'}/${countsFromApi[t]}`).join(' '));

    shots.push(await cdp.shot('02-buy1-sell2.png'));

    // ---------- REQ-041（取代 REQ-040 的「周线不做判定」口径）：周线由后端基于真实周K现场判定 ----------
    await cdp.eval(`switchKlineGroup('weekly')`);
    await sleep(6000);
    const weekly = await cdp.eval(`(() => {
      const btn = document.getElementById('btnBsBuy3_right');
      const a = (appState.activeDetailStock.group_chanlun || {}).weekly || {};
      const txt = document.getElementById('chartSvgContainerRight').textContent.replace(/\\s+/g, ' ');
      return { count: Number(btn.dataset.count), level: a.level || null,
               total: (a.buy_sell_points || []).length, submitted: a.submitted_bars || 0,
               marks: document.querySelectorAll('#chartSvgContainerRight .chanlun-bs').length,
               summary: (txt.match(/自动标记买卖点（[^）]*）/) || [''])[0] };
    })()`);
    check('REQ-041 周线图给出真实「周线级别」判定（不再是「未获取缠论分析」）',
      weekly.level === 'weekly' && weekly.submitted > 0 && weekly.total > 0 && weekly.summary.includes('周线级别'),
      `级别=${weekly.level} · 提交 ${weekly.submitted} 根周K · 后端识别 ${weekly.total} 个 · ${weekly.summary}`);
    await cdp.eval(`switchKlineGroup('daily')`);
    await sleep(2000);

    // ---------- REQ-038：双图模式工具区固定高度与两图同高 ----------
    await cdp.eval(`showChartPanel('left')`);
    await sleep(4500);
    const geo = await cdp.eval(`(() => {
      const tzR = document.getElementById('chartToolzoneRight');
      const tzL = document.getElementById('chartToolzoneLeft');
      const sr = document.getElementById('chartSvgContainerRight').getBoundingClientRect();
      const sl = document.getElementById('chartSvgContainerLeft').getBoundingClientRect();
      const row = document.getElementById('chartPanelRow');
      const csL = getComputedStyle(tzL), csR = getComputedStyle(tzR);
      return {
        mode: row.className,
        heightR: tzR.getBoundingClientRect().height, heightL: tzL.getBoundingClientRect().height,
        cssHeightR: csR.height, overflowR: csR.overflowY,
        svgTopDiff: Math.abs(sl.top - sr.top), svgTopLeft: sl.top, svgTopRight: sr.top,
        blankL: tzL.clientHeight - tzL.scrollHeight, blankR: tzR.clientHeight - tzR.scrollHeight,
        scrollL: tzL.scrollHeight, clientL: tzL.clientHeight
      };
    })()`);
    check('REQ-038 双图模式已进入 dual-panel 布局', /dual-panel/.test(geo.mode), geo.mode);
    check('REQ-038 工具区间为固定高度（CSS 变量 --chart-toolzone-h，两面板一致）',
      geo.cssHeightR === '500px' && Math.round(geo.heightR) === Math.round(geo.heightL) && Math.round(geo.heightR) === 500,
      `右 ${Math.round(geo.heightR)}px · 左 ${Math.round(geo.heightL)}px · CSS ${geo.cssHeightR}`);
    check('REQ-038 两个K线图从同一高度开始（SVG 顶部差值＝0）', geo.svgTopDiff < 0.5,
      `左 ${geo.svgTopLeft} / 右 ${geo.svgTopRight} → 差值 ${geo.svgTopDiff.toFixed(2)}px`);
    check('REQ-038 工具区超出内容时内部滚动（overflow-y: auto）', geo.overflowR === 'auto', geo.overflowR);

    // 需求REQ-038: 内容不足时必须留白而不是被压缩 —— 临时清空本图图层面板后，容器仍保持固定高度
    const blank = await cdp.eval(`(() => {
      const contentHeight = (zone) => [...zone.children].reduce((sum, el) => sum + el.getBoundingClientRect().height, 0);
      const tz = document.getElementById('chartToolzoneLeft');
      const host = document.getElementById('chartLayerPanelLeft');
      const saved = host.innerHTML;
      host.innerHTML = '';                       // 制造「内容不足」场景，验证固定高度不被内容压矮
      const height = tz.getBoundingClientRect().height;
      const content = contentHeight(tz);
      const spare = Math.round(tz.clientHeight - content);
      host.innerHTML = saved;
      return { height, spare, contentHeight: Math.round(content) };
    })()`);
    check('REQ-038 内容不足的工具区保持固定高度并留白（不被内容压矮）',
      Math.round(blank.height) === 500 && blank.spare > 0,
      `容器 ${Math.round(blank.height)}px · 内容 ${blank.contentHeight}px · 留白 ${blank.spare}px`);

    // 需求REQ-038: 两个面板内容多少不同（右图开 4 根自动线使其更高）时仍必须绝对同高
    await cdp.eval(`setAutoLinesCount(4, 'right')`);
    await sleep(2600);
    const geo2 = await cdp.eval(`(() => {
      const tzR = document.getElementById('chartToolzoneRight');
      const sr = document.getElementById('chartSvgContainerRight').getBoundingClientRect();
      const sl = document.getElementById('chartSvgContainerLeft').getBoundingClientRect();
      return { svgTopDiff: Math.abs(sl.top - sr.top), contentR: tzR.scrollHeight, clientR: tzR.clientHeight,
               overflowed: tzR.scrollHeight > tzR.clientHeight, lines: document.querySelectorAll('#chartSvgContainerRight .chart-hline').length };
    })()`);
    check('REQ-038 一侧内容变多（4 根自动线撑高）时两图依旧绝对同高',
      geo2.svgTopDiff < 0.5 && geo2.overflowed,
      `SVG 顶部差值 ${geo2.svgTopDiff.toFixed(2)}px · 右内容 ${geo2.contentR}px / 容器 ${geo2.clientR}px · 自动线 ${geo2.lines} 条`);
    await cdp.eval(`setAutoLinesCount(0, 'right')`);
    await sleep(1800);

    const layerVisible = await cdp.eval(`(() => {
      const rows = [...document.querySelectorAll('#chartLayerPanelRight .chart-layer-row, #chartLayerPanelRight > *')];
      const box = document.getElementById('chartLayerPanelRight').getBoundingClientRect();
      const tz = document.getElementById('chartToolzoneRight').getBoundingClientRect();
      const visibleRows = [...document.querySelectorAll('#chartLayerPanelRight *')].filter(el => {
        const r = el.getBoundingClientRect();
        return r.height > 0 && r.top >= tz.top - 1 && r.bottom <= tz.bottom + 1;
      }).length;
      const totalNodes = document.querySelectorAll('#chartLayerPanelRight *').length;
      return { boxBottom: box.bottom, tzBottom: tz.bottom, visibleRows, totalNodes,
               clipped: box.bottom > tz.bottom + 1, scrollTop: document.getElementById('chartToolzoneRight').scrollTop };
    })()`);
    check('REQ-038 图层面板完整落在固定高度内（未被裁剪，无需滚动即可看到全部图层）',
      !layerVisible.clipped && layerVisible.scrollTop === 0,
      `图层底 ${Math.round(layerVisible.boxBottom)} / 工具区底 ${Math.round(layerVisible.tzBottom)} · 可见节点 ${layerVisible.visibleRows}/${layerVisible.totalNodes}`);

    shots.push(await cdp.shot('03-dual-panel-aligned.png'));

    // ---------- REQ-037（R09 口径修订）：幅图控件已合并为「唯一联动控件」，两图同步 ----------
    // 原口径「K线＝成交额 / 当日分时＝成交量，按图独立」已被产品显式改为「单点切换，分时与K线同步联动」；
    // 断言意图保留为：①控件唯一；②当前档位在页面唯一高亮；③两面板实际渲染与所选档位一致；④手选不被颗粒度切换改写。
    sub = await cdp.eval(subplotProbe('right'));
    check('REQ-037 幅图控件已合并为唯一联动控件（单点切换）',
      sub.controlCount === 1 && sub.allActive.length === 1, `控件 ${sub.controlCount} 个：${sub.controlIds.join(' | ')} · 高亮 ${sub.allActive.join(',')}`);
    check('REQ-037 双图模式下K线面板仍为成交额', sub.active === 'amt' && sub.hasAmt, `${sub.active} · ${sub.title}`);
    const leftSubSame = await cdp.eval(subplotProbe('left'));
    // 口径修订（2026-09-24，REQ-037）：副图控件合并为唯一「幅图联动」控件后，首屏两图统一默认「成交额」，
    // 与控件高亮一致 —— 此前「当日分时＝成交量」会造成「高亮成交额 / 左图显示成交量」的自相矛盾。
    check('REQ-037 首屏两图与统一控件高亮一致＝成交额（REQ-037 口径修订后）',
      leftSubSame.active === 'amt' && leftSubSame.hasAmt && !leftSubSame.hasVol,
      `统一控件高亮 ${leftSubSame.active} · 当日分时实际渲染 ${leftSubSame.title}`);

    // ---------- REQ-037：手动选择后不被自动改写 ----------
    await cdp.eval(`switchChartSubplot('vol')`);
    await sleep(1200);
    await cdp.eval(`switchKlineGroup('weekly')`);
    await sleep(2200);
    await cdp.eval(`switchKlineGroup('daily')`);
    await sleep(2200);
    sub = await cdp.eval(subplotProbe('right'));
    check('REQ-037 用户手动选过副图后，切换颗粒度不会被强制改回默认',
      sub.active === 'vol' && sub.hasVol, `${sub.active} · ${sub.title}`);
    const leftAfterManual = await cdp.eval(subplotProbe('left'));
    check('REQ-037 手动切换后两面板联动一致（同一次选择同步生效）',
      leftAfterManual.active === 'vol' && leftAfterManual.hasVol, `${leftAfterManual.active} · ${leftAfterManual.title}`);

    // ---------- REQ-037：分钟K线跟随统一档位 ----------
    await cdp.eval(`switchKlineGroup('daily'); switchChartSubplot('amt'); switchMinuteSub('m5', 'left')`);
    await sleep(3500);
    sub = await cdp.eval(subplotProbe('left'));
    check('REQ-037 5分K线（K线形态图）跟随统一档位渲染＝成交额', sub.active === 'amt' && sub.hasAmt, `${sub.active} · ${sub.title}`);
    await cdp.eval(`switchMinuteSub('timeline', 'left')`);
    await sleep(3000);
    sub = await cdp.eval(subplotProbe('left'));
    check('REQ-037 切回当日分时后仍与统一档位一致（联动不丢失）', sub.active === 'amt' && sub.hasAmt, `${sub.active} · ${sub.title}`);

    // ---------- REQ-040：买卖点开关按面板独立 ----------
    await cdp.eval(`toggleChartBsLevel('buy', 3, 'right')`);
    await sleep(1800);
    // 需求REQ-041：两侧默认均为等级 3（全开），因此先主动把左图关掉、右图保持开启，
    // 以验证 REQ-040 的原始意图「按图独立生效」未被本批默认值改动破坏。
    const independence = await cdp.eval(`(() => {
      toggleChartBsLevel('buy', 3, 'left'); toggleChartBsLevel('sell', 3, 'left');
      renderChartPanel('left'); renderChartPanel('right');
      const leftMarks = document.querySelectorAll('#chartSvgContainerLeft .chanlun-bs').length;
      const rightMarks = document.querySelectorAll('#chartSvgContainerRight .chanlun-bs').length;
      const leftBtn = document.getElementById('btnBsBuy3_left');
      const rightBtn = document.getElementById('btnBsBuy3_right');
      return { leftMarks, rightMarks, leftActive: leftBtn.classList.contains('active'), rightActive: rightBtn.classList.contains('active'),
               leftLevel: chartPanels.left.st.bsBuyLevel, rightLevel: chartPanels.right.st.bsBuyLevel,
               leftSellLevel: chartPanels.left.st.bsSellLevel, rightSellLevel: chartPanels.right.st.bsSellLevel };
    })()`);
    // 右侧等级沿用脚本前序步骤留下的档位（可能已被降级到 1 或 2），只要求「右侧仍开启、左侧归零」
    check('REQ-040/REQ-041 买卖点开关按图独立生效（关掉左图不影响右图与右图按钮）',
      independence.rightActive && !independence.leftActive && independence.leftLevel === 0 && independence.leftSellLevel === 0
        && independence.rightLevel > 0 && independence.rightSellLevel > 0 && independence.leftMarks === 0,
      `右 active=${independence.rightActive}(等级${independence.rightLevel}/${independence.rightSellLevel}) 标记 ${independence.rightMarks} · `
      + `左 active=${independence.leftActive}(等级${independence.leftLevel}/${independence.leftSellLevel}) 标记 ${independence.leftMarks}`);

    shots.push(await cdp.shot('04-panel-independent.png'));

    // ---------- 收尾：先把视窗恢复到能覆盖买卖点的区间，再验证「再次点击同一等级即关闭」 ----------
    await cdp.eval(`switchKlineGroup('daily'); showAllKlineBars('right')`);
    await sleep(2000);
    const levelOf = side => cdp.eval(`chartPanels.right.st.${side === 'buy' ? 'bsBuyLevel' : 'bsSellLevel'}`);
    const markCount = kind => cdp.eval(kind === 'buy'
      ? `document.querySelectorAll('#chartSvgContainerRight .chanlun-buy1, #chartSvgContainerRight .chanlun-buy2, #chartSvgContainerRight .chanlun-buy3').length`
      : `document.querySelectorAll('#chartSvgContainerRight .chanlun-sell1, #chartSvgContainerRight .chanlun-sell2, #chartSvgContainerRight .chanlun-sell3').length`);
    /** 把某一方向清到 0：每次点击「当前等级」即关闭（等级语义为累积选择） */
    const clearSide = async side => {
      for (let i = 0; i < 4; i++) {
        const lv = await levelOf(side);
        if (!lv) return;
        await cdp.eval(`toggleChartBsLevel('${side}', ${lv}, 'right')`);
        await sleep(1300);
      }
    };

    if ((await levelOf('buy')) !== 3) { await cdp.eval(`toggleChartBsLevel('buy', 3, 'right')`); await sleep(1500); }
    const buyAll = await markCount('buy');
    await cdp.eval(`toggleChartBsLevel('buy', 3, 'right')`);   // 再次点击同一等级 → 关闭
    await sleep(1500);
    const buyOff = await markCount('buy');
    check('REQ-040 再次点击同一等级即关闭该方向全部买卖点标记',
      buyAll > 0 && buyOff === 0, `关闭前买点 ${buyAll} 个 → 关闭后 ${buyOff} 个`);
    await clearSide('sell');
    const closed = await cdp.eval(`document.querySelectorAll('#chartSvgContainerRight .chanlun-bs').length`);
    check('REQ-040 买、卖开关各自独立关闭后图上不再残留标记', closed === 0, `剩余标记 ${closed} 个`);

    check('页面无 JS 运行错误', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '));
  } catch (e) {
    check('R07 验证脚本执行完成', false, e.message);
  } finally {
    try { chrome.kill(); } catch (_) {}
  }

  const failed = results.filter(r => !r.ok);
  console.log(`\n===== R07 验证结果：${results.length - failed.length}/${results.length} 通过 =====`);
  if (shots.length) console.log('截图：\n' + shots.map(s => '  ' + s).join('\n'));
  const report = { round: 'R07', base: BASE, at: new Date().toISOString(), total: results.length, passed: results.length - failed.length, results, consoleErrors, shots };
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify(report, null, 2));
  process.exit(failed.length ? 1 : 0);
})();
