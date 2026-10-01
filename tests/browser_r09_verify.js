#!/usr/bin/env node
/**
 * R09 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-046 / REQ-047
 * 覆盖：
 *   1. REQ-046：顶栏「行情日期」徽标必须精确到分，且与后端 /api/status 的真实快照时间逐字一致；
 *      来源只给到日时不得出现任何 HH:MM，完全拿不到时必须显示「未获取」（不以本地时钟冒充）
 *   2. REQ-047：个股日K副图（成交额/成交量/换手率）、当日分时副图、大盘指数副图的「副图标题 + 统计概要」
 *      使用浏览器实测 getBBox() 判定：同一行内任意两段文字的横向包围盒交集必须为 0（真实渲染零重叠），
 *      且所有表头文字必须落在副图背景框内（不越出绘图区）
 *   3. 指数来源未披露成交额时，副图不得输出 0.00亿，必须如实标注不可得
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态与真实接口，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-24-r09';
const PORT = Number(process.env.DSH_CDP_PORT || 9373);
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

/** 顶栏行情日期徽标探针（REQ-046） */
const badgeProbe = `(() => {
  const el = document.getElementById('dataValidityBadge');
  const note = document.getElementById('quoteSourceStatus');
  return { text: el ? el.textContent.trim() : null, title: el ? el.title : null, note: note ? note.textContent.trim() : null };
})()`;

/**
 * 副图表头真实渲染探针（REQ-047）：用 getBBox() 取得每段文字的真实包围盒，
 * 逐对判定「同一行内横向交集 > 0.5px」即为重叠；同时给出副图背景框右缘用于越界判定。
 */
function headerProbe(hostId) {
  return `(() => {
    const host = document.getElementById('${hostId}');
    if (!host) return { error: '容器不存在' };
    const svgs = [...host.querySelectorAll('svg')];
    const svg = svgs[svgs.length - 1];
    if (!svg) return { error: '未渲染 SVG' };
    const box = (t) => { const b = t.getBBox(); return { x: b.x, right: b.x + b.width, y: b.y, bottom: b.y + b.height, w: b.width, h: b.height }; };
    const items = [];
    [...svg.querySelectorAll('g.sub-summary-group text')].forEach(t => {
      const b = box(t);
      items.push({ text: t.textContent.replace(/\\s+/g, ' ').trim(), ...b, kind: 'stat' });
    });
    [...svg.querySelectorAll('text')].forEach(t => {
      if (/副图[:：]/.test(t.textContent) && !t.closest('g.sub-summary-group')) {
        const b = box(t);
        items.push({ text: t.textContent.replace(/\\s+/g, ' ').trim(), ...b, kind: 'title' });
      }
    });
    // 副图背景框：填充 #0f172a 的最大矩形（个股/分时）或 #070d1e 系（指数无填充则取最大矩形）
    let panel = null;
    [...svg.querySelectorAll('rect')].forEach(r => {
      const w = Number(r.getAttribute('width')) || 0;
      const h = Number(r.getAttribute('height')) || 0;
      if (w > 300 && h > 50 && h < 220) {
        const b = box(r);
        if (!panel || b.bottom > panel.bottom) panel = { x: b.x, right: b.right, top: b.y, bottom: b.bottom, h: h };
      }
    });
    const overlaps = [];
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i], b = items[j];
        const sameRow = !(a.bottom <= b.y + 0.5 || b.bottom <= a.y + 0.5);
        if (!sameRow) continue;
        const inter = Math.min(a.right, b.right) - Math.max(a.x, b.x);
        if (inter > 0.5) overlaps.push({ a: a.text, b: b.text, px: Number(inter.toFixed(2)) });
      }
    }
    const overflow = panel ? items.filter(i => i.right > panel.right + 0.5).map(i => ({ text: i.text, right: Number(i.right.toFixed(1)) })) : [];
    return {
      count: items.length,
      titles: items.filter(i => i.kind === 'title').map(i => i.text),
      stats: items.filter(i => i.kind === 'stat').map(i => i.text),
      overlaps, overflow,
      panel: panel ? { right: Number(panel.right.toFixed(1)), top: Number(panel.top.toFixed(1)), h: Number(panel.h.toFixed(1)) } : null,
      maxRight: items.length ? Number(Math.max(...items.map(i => i.right)).toFixed(1)) : null,
      text: svg.textContent.replace(/\\s+/g, ' ').trim()
    };
  })()`;
}

/** 截图前把目标图表滚入视口，保证副图表头在可视区内（证据截图必须能看到被验证的对象） */
const focusProbe = (id) => `(() => { const el = document.getElementById('${id}'); if (el) el.scrollIntoView({ block: 'center' }); return !!el; })()`;

const subplotText = `(() => {
  const svg = document.querySelector('#chartSvgContainerRight svg');
  return svg ? svg.textContent.replace(/\\s+/g, ' ') : '';
})()`;

(async () => {
  const shots = [];
  const consoleErrors = [];
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', '--window-size=1680,1200', '--user-data-dir=' + fs.mkdtempSync(path.join(os.tmpdir(), 'r09-chrome-')),
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
    const title = await cdp.eval('document.title');
    check('页面加载成功', typeof title === 'string' && title.length > 0, title);
    // 断言意图＝「页面徽标与版本唯一权威 config/version.json 一致」，不写死版本号（发版不再连带改探针）
    const apiVersion = (await (await fetch(BASE + '/api/version')).json()).version;
    const badgeVersion = await cdp.eval(`document.getElementById('appVersionBadge').textContent.trim()`);
    check('页面版本徽标与 /api/version（config/version.json 唯一权威）一致', !!apiVersion && badgeVersion === apiVersion,
      `徽标 ${badgeVersion} vs 接口 ${apiVersion}`);

    // ================= REQ-046: 顶栏行情日期精确到分 =================
    const status = await (await fetch(BASE + '/api/status')).json();
    const qdt = status.quote_datetime;
    check('REQ-046 后端已暴露真实快照时间 quote_datetime', !!qdt && !!qdt.datetime,
      qdt ? `${qdt.datetime}（精度 ${qdt.precision}，原始值 ${qdt.raw}）` : '未暴露');
    let badge = await cdp.eval(badgeProbe);
    // 行情来源说明由首次 /api/filter 返回后回填，页面刚加载时可能仍是「正在核验…」——按真实完成时刻判定
    for (let i = 0; i < 40 && /正在核验|核验中/.test(badge.note || ''); i++) {
      await sleep(500);
      badge = await cdp.eval(badgeProbe);
    }
    if (qdt && qdt.precision === 'minute') {
      check('REQ-046 顶栏徽标精确到分（含 HH:MM）', /行情日期: \d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2}$/.test(badge.text), badge.text);
      check('REQ-046 徽标时间与后端真实快照时间逐字一致', badge.text === `📅 行情日期: ${qdt.display}`,
        `徽标「${badge.text}」 vs 接口「${qdt.display}」`);
    } else {
      check('REQ-046 来源无时刻时不得臆造 HH:MM', !/\d{2}:\d{2}/.test(badge.text || ''), badge.text);
    }
    check('REQ-046 徽标 title 说明精度与来源原始值', /精确到分/.test(badge.title || '') && /原始值/.test(badge.title || ''), badge.title);
    check('REQ-046 行情来源说明同步到分', new RegExp((qdt && qdt.datetime) || '未获取').test(badge.note || ''), badge.note);
    shots.push(await cdp.shot('01-header-minute-badge.png'));

    // ================= REQ-047: 个股副图（成交额/成交量/换手率）=================
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(11000);
    const opened = await cdp.eval(`(() => { const s = appState.activeDetailStock; return s ? { name: s.name, days: (s.daily_bars || []).length } : null; })()`);
    check('个股详情已加载真实日K', !!opened && opened.days > 0, opened ? `${opened.name} · 日K ${opened.days} 根` : '未加载');

    const SUBPLOTS = [
      { key: 'amt', label: '成交额', shot: '02-right-subplot-amt.png' },
      { key: 'vol', label: '成交量', shot: '03-right-subplot-vol.png' },
      { key: 'turnover_rate', label: '换手率', shot: '04-right-subplot-turnover.png' }
    ];
    for (const sp of SUBPLOTS) {
      await cdp.eval(`switchChartSubplot('${sp.key}', 'right')`);
      await sleep(1500);
      const probe = await cdp.eval(headerProbe('chartSvgContainerRight'));
      const txt = await cdp.eval(subplotText);
      check(`REQ-047 日K副图(${sp.label})表头已渲染标题与统计项`,
        !probe.error && probe.titles.length === 1 && probe.stats.length === 5,
        probe.error || `标题 ${JSON.stringify(probe.titles)} · 统计项 ${probe.stats.length} 个`);
      check(`REQ-047 日K副图(${sp.label})真实包围盒零重叠`, !probe.error && probe.overlaps.length === 0,
        probe.overlaps.map(o => `${o.a}×${o.b}(${o.px}px)`).join(' | ') || '0 处重叠');
      check(`REQ-047 日K副图(${sp.label})表头不越出副图绘图区`, !probe.error && probe.overflow.length === 0,
        probe.overflow.length ? `越界: ${JSON.stringify(probe.overflow)}（绘图区右缘 ${probe.panel && probe.panel.right}，表头右缘 ${probe.maxRight}）` : `表头右缘 ${probe.maxRight} ≤ 绘图区右缘 ${probe.panel && probe.panel.right}`);
      if (sp.key === 'amt') {
        check('REQ-047 成交额副图标题保留 REQ-025 兜底口径标注（若来源含估算）',
          !/含估算/.test(txt) || /副图：成交额（含估算：均价×成交量）/.test(txt),
          /副图：成交额（含估算：均价×成交量）/.test(txt) ? '含估算标注完整' : '本批真实来源无估算样本');
      }
      await cdp.eval(focusProbe('chartPanelRow'));
      await sleep(500);
      shots.push(await cdp.shot(sp.shot));
    }

    // 当日分时副图（左面板）
    for (const key of ['vol', 'amt', 'turnover_rate']) {
      await cdp.eval(`switchChartSubplot('${key}', 'left')`);
      await sleep(1500);
      const probe = await cdp.eval(headerProbe('chartSvgContainerLeft'));
      // 当日分时的成交额口径有两种**合法**结果（都是真实来源约束下的诚实呈现，不得强行要求其一）：
      //   a) 窗口内每分钟都含量额 → 5 项统计概要；
      //   b) 窗口内存在缺量额的分时点（如收盘快照行 volume=0/amount=null）→ 只给一句
      //      「当前来源未提供完整量额」兜底说明（不得用部分数据拼出总和冒充完整口径）。
      // 两种情况下都必须：标题恰好 1 个、零重叠、不越界。
      const amtFallback = key === 'amt' && probe.stats.length === 1 && /未提供完整量额/.test(probe.stats[0]);
      const statsOk = probe.stats.length === 5 || amtFallback;
      check(`REQ-047 当日分时副图(${key})真实包围盒零重叠`,
        !probe.error && probe.titles.length === 1 && probe.overlaps.length === 0 && statsOk,
        probe.error || (probe.overlaps.map(o => `${o.a}×${o.b}(${o.px}px)`).join(' | ')
          || `0 处重叠 · 统计项 ${probe.stats.length} 个${amtFallback ? '（成交额按完整性兜底口径：当前来源未提供完整量额）' : ''}`));
    }
    await cdp.eval(focusProbe('chartPanelRow'));
    await sleep(500);
    shots.push(await cdp.shot('05-timeline-subplot-header.png'));

    // ================= REQ-047 + REQ-032: 大盘指数副图 =================
    const idx = await (await fetch(BASE + '/api/index/sh000001')).json();
    const hasAmount = ((idx.data || {}).daily_bars || []).some(b => b.amount_yi != null);
    await cdp.eval(`openIndexDetail('sh000001')`);
    await sleep(6000);
    const idxTimeline = await cdp.eval(headerProbe('indexChartSvgContainer'));
    check('REQ-047 指数分时副图标题独立成行（无统计项时也不叠画）',
      !idxTimeline.error && idxTimeline.titles.length === 1 && idxTimeline.overlaps.length === 0,
      idxTimeline.error || `标题 ${JSON.stringify(idxTimeline.titles)} · 重叠 ${idxTimeline.overlaps.length} 处`);
    await cdp.eval(focusProbe('indexChartWrapper'));
    await sleep(500);
    shots.push(await cdp.shot('06-index-timeline-header.png'));

    await cdp.eval(`switchIndexChartPeriod('all')`);
    await sleep(4500);
    const idxProbe = await cdp.eval(headerProbe('indexChartSvgContainer'));
    check('REQ-047 指数K线副图表头已渲染标题与统计行',
      !idxProbe.error && idxProbe.titles.length === 1 && (idxProbe.stats.length >= 1),
      idxProbe.error || `标题 ${JSON.stringify(idxProbe.titles)} · 统计行 ${JSON.stringify(idxProbe.stats)}`);
    check('REQ-047 指数K线副图表头真实包围盒零重叠', !idxProbe.error && idxProbe.overlaps.length === 0,
      idxProbe.overlaps.map(o => `${o.a}×${o.b}(${o.px}px)`).join(' | ') || '0 处重叠');
    check('REQ-047 指数K线副图表头不越出绘图区', !idxProbe.error && idxProbe.overflow.length === 0,
      idxProbe.overflow.length ? JSON.stringify(idxProbe.overflow) : `表头右缘 ${idxProbe.maxRight} ≤ 绘图区右缘 ${idxProbe.panel && idxProbe.panel.right}`);
    if (!hasAmount) {
      check('REQ-032 指数成交额不可得时不得输出 0.00亿，必须如实标注',
        !/0\.00亿/.test(idxProbe.text) && /不可得|未披露/.test(idxProbe.text),
        (idxProbe.text.match(/不可得[^ ]*/) || [''])[0] || idxProbe.text.slice(0, 80));
    } else {
      check('REQ-032 指数成交额可得时四维分布必须出数', /平均:/.test(idxProbe.text), idxProbe.text.slice(0, 80));
    }
    await cdp.eval(focusProbe('indexChartWrapper'));
    await sleep(500);
    shots.push(await cdp.shot('07-index-kline-subplot-header.png'));

    check('控制台无脚本错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | ') || '0 条');
  } catch (err) {
    check('验证脚本执行完成', false, err.message);
  } finally {
    try { chrome.kill('SIGKILL'); } catch (_) {}
  }

  const report = {
    at: new Date().toISOString(), base: BASE, total: results.length,
    passed: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).length,
    consoleErrors, shots: shots.map(s => path.basename(s)), results
  };
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(`\n=== R09 真机验证：${report.passed}/${report.total} PASS ===`);
  if (report.failed) {
    console.log('失败项：\n' + results.filter(r => !r.ok).map(r => ` - ${r.name}：${r.detail}`).join('\n'));
    process.exit(1);
  }
})();
