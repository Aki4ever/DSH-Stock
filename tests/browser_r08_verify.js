#!/usr/bin/env node
/**
 * R08 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-041/042/043/044/045
 * 覆盖：
 *   1. REQ-041：缠论买卖点(买1/2/3、卖1/2/3)在日线/周线/季线/当日分时/5分K线五类图上
 *      **默认自动标记**（零点击），各图标记数量必须与该颗粒度后端真实判定在当前视窗内的分类计数逐类一致，
 *      且图上各自标注所属级别（日线/周线/季线/分时/5分级别），关闭按钮后标记消失
 *   2. REQ-042/043：周线图与季线图成交额＝区间内日线成交额逐日相加（与日线图同一解析口径），
 *      图上标注「含估算 N 根日线」，页面内独立重算比对不得有偏差
 *   3. REQ-044：分时维度只剩「当日分时 / 5分K线」两个子 Tab，1分K线已移除且不可切换
 *   4. REQ-045：打开个股详情即为「分时图 + 日线图」双图并排，无需点击任何「调出」按钮
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态与真实接口，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-23-r08';
const PORT = Number(process.env.DSH_CDP_PORT || 9372);
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

const BS_TYPES = ['buy1', 'buy2', 'buy3', 'sell1', 'sell2', 'sell3'];

/** 面板布局与默认可见性探针（REQ-045） */
const layoutProbe = `(() => {
  const row = document.getElementById('chartPanelRow');
  const l = document.getElementById('chartPanelLeft');
  const r = document.getElementById('chartPanelRight');
  const lr = l.getBoundingClientRect(), rr = r.getBoundingClientRect();
  return {
    leftVisible: chartPanels.left.visible, rightVisible: chartPanels.right.visible,
    dual: row.classList.contains('dual-panel'), single: row.classList.contains('single-panel'),
    lHidden: !!l.hidden, rHidden: !!r.hidden,
    addMinuteHidden: !!document.getElementById('btnAddMinutePanel').hidden,
    addKlineHidden: !!document.getElementById('btnAddKlinePanel').hidden,
    lTop: Math.round(lr.top), rTop: Math.round(rr.top), lW: Math.round(lr.width), rW: Math.round(rr.width),
    lMinuteSub: chartPanels.left.st.minuteSub, rGroup: chartPanels.right.st.klineGroup
  };
})()`;

/** 分时子 Tab 探针（REQ-044） */
const subTabProbe = `(() => {
  const ctrl = document.getElementById('minuteSubControl');
  const subs = [...ctrl.querySelectorAll('.seg-btn')].map(b => b.getAttribute('data-sub'));
  return { subs, hasM1Button: /data-sub="m1"/.test(ctrl.innerHTML), active: (ctrl.querySelector('.seg-btn.active')||{getAttribute:()=>null}).getAttribute('data-sub'), current: chartPanels.left.st.minuteSub };
})()`;

/** 某个面板槽位的买卖点实际渲染探针（REQ-041） */
function bsProbe(slot) {
  const hostId = slot === 'left' ? 'chartSvgContainerLeft' : 'chartSvgContainerRight';
  return `(() => {
    const host = document.getElementById('${hostId}');
    const counts = {};
    for (const t of ['buy1','buy2','buy3','sell1','sell2','sell3']) counts[t] = host.querySelectorAll('.chanlun-' + t).length;
    const text = host.textContent.replace(/\\s+/g, ' ');
    const summary = (text.match(/自动标记买卖点（[^）]*）：[^]{0,60}/) || [''])[0].trim();
    const tips = [...host.querySelectorAll('.chanlun-bs title')].map(t => t.textContent.trim());
    const buttons = {};
    for (const t of ['buy1','buy2','buy3','sell1','sell2','sell3']) {
      const cap = t.charAt(0).toUpperCase() + t.slice(1);
      const btn = document.getElementById('btnBs' + cap + '_${slot}');
      buttons[t] = btn ? { active: btn.classList.contains('active'), count: Number(btn.dataset.count || -1) } : null;
    }
    return { counts, total: Object.values(counts).reduce((a, b) => a + b, 0), summary, tips, buttons };
  })()`;
}

/** 期望值探针：该颗粒度后端真实判定落在「当前实际渲染视窗」内的分类计数（与画图同源） */
function expectProbe(slot, sourceExpr) {
  return `(() => {
    const stock = appState.activeDetailStock;
    const panel = panelBySlot('${slot}');
    const analysis = ${sourceExpr};
    if (!analysis) return { error: '未获取分析数据' };
    if (!Array.isArray(analysis.buy_sell_points)) return { error: analysis.error || '该颗粒度分析不可用', status: analysis.status };
    const all = panelAvailableBars(stock, panel.st);
    // 需求REQ-024: 当日分时是全天全景、不参与根数缩放，其视窗就是全部分钟点；
    // 只有 K 线颗粒度才按「视窗根数 N」裁剪。
    const win = panelIsTimeline(panel.st) ? { bars: all } : panelWindowBars(all, panel.st);
    const n = win.bars.length;
    const total = (analysis.dates || []).length;
    // 与渲染完全同源的口径：面板视窗取序列末尾 N 根 → 视窗第一根在分析序列中的索引＝total-n，
    // 渲染侧按该 offset 换算 x 坐标，期望值按同一 offset 取点（避免键格式差异导致口径不一致）。
    const startIdx = Math.max(0, total - n);
    const pts = (analysis.buy_sell_points || []).filter(p => {
      const i = Number(p.index);
      return Number.isFinite(i) && i >= startIdx && i < total;
    });
    const counts = { buy1: 0, buy2: 0, buy3: 0, sell1: 0, sell2: 0, sell3: 0 };
    pts.forEach(p => { if (counts[p.type] !== undefined) counts[p.type]++; });
    return { counts, total: pts.length, startIdx, windowBars: n, analysisBars: total, allCounts: analysis.counts, level: analysis.level || null };
  })()`;
}

/** 周/季成交额独立重算探针（REQ-042/043）：在页面内按同一分桶口径逐日相加，与实现结果逐根比对 */
function amountRecomputeProbe(group) {
  return `(() => {
    const stock = appState.activeDetailStock;
    const daily = (stock && stock.daily_bars) || [];
    if (!daily.length) return { error: '无日线数据' };
    const keyOf = (dateStr) => {
      const p = String(dateStr || '').split('-').map(Number);
      if (p.length !== 3 || !p[0] || !p[1] || !p[2]) return null;
      if ('${group}' === 'quarterly') return p[0] + 'Q' + (Math.floor((p[1] - 1) / 3) + 1);
      const dt = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
      const dow = dt.getUTCDay() === 0 ? 7 : dt.getUTCDay();
      dt.setUTCDate(dt.getUTCDate() + 4 - dow);
      const ys = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
      const wk = Math.ceil(((dt - ys) / 86400000 + 1) / 7);
      return dt.getUTCFullYear() + 'W' + String(wk).padStart(2, '0');
    };
    const buckets = new Map();
    for (const b of daily) {
      const key = keyOf(b.date);
      if (key === null) continue;
      if (!buckets.has(key)) buckets.set(key, { sum: 0, derived: 0, missing: 0, counted: 0, last: null, n: 0 });
      const cur = buckets.get(key);
      const r = resolveKlineAmount(b);
      if (r.amountYi === null) cur.missing++;
      else { cur.sum += r.amountYi; cur.counted++; if (r.derived) cur.derived++; }
      cur.last = b.date; cur.n++;
    }
    const agg = aggregateBarsForGroup(daily, '${group}');
    const mismatches = [];
    let derivedTotal = 0, missingTotal = 0;
    for (const bar of agg) {
      const cur = [...buckets.values()].find(v => v.last === bar.date);
      if (!cur) { mismatches.push({ date: bar.date, why: '未找到对应日线区间' }); continue; }
      derivedTotal += cur.derived; missingTotal += cur.missing;
      const implAmount = bar.amount_yi, manualAmount = cur.counted > 0 ? Number(cur.sum.toFixed(4)) : null;
      if (implAmount === null || manualAmount === null) {
        if (implAmount !== manualAmount) mismatches.push({ date: bar.date, why: '空值口径不一致', impl: implAmount, manual: manualAmount });
        continue;
      }
      if (Math.abs(implAmount - manualAmount) > 0.01) mismatches.push({ date: bar.date, why: '成交额不一致', impl: implAmount, manual: manualAmount });
      if (bar.amount_derived_days !== cur.derived) mismatches.push({ date: bar.date, why: '含估算日线根数不一致', impl: bar.amount_derived_days, manual: cur.derived });
      if (bar.amount_missing_days !== cur.missing) mismatches.push({ date: bar.date, why: '缺失日线根数不一致', impl: bar.amount_missing_days, manual: cur.missing });
    }
    const text = document.getElementById('chartSvgContainerRight').textContent.replace(/\\s+/g, ' ');
    return {
      buckets: agg.length, mismatchCount: mismatches.length, mismatches: mismatches.slice(0, 4),
      derivedTotal, missingTotal,
      hasNote: text.includes('成交额＝区间内日线成交额逐日相加'),
      derivedNote: (text.match(/含估算 \\d+ 根日线（均价×成交量）/) || [''])[0],
      missingNote: (text.match(/覆盖不完整·\\d+ 根日线成交额不可得未计入/) || [''])[0],
      sampleAmount: agg.length ? agg[agg.length - 1].amount_yi : null,
      sampleDate: agg.length ? agg[agg.length - 1].date : null
    };
  })()`;
}

/** 期待：从「该颗粒度真实判定 + 当前渲染视窗」算出期望计数并与实际渲染逐类比对 */
function compareCounts(label, actual, expect) {
  if (!expect || expect.error) {
    check(`${label}：期望值可获得`, actual.total === 0, `实际标记 ${actual.total} 个 · 期望不可得：${expect ? expect.error : 'null'}`);
    return;
  }
  const diffs = BS_TYPES.filter(t => (actual.counts[t] || 0) !== (expect.counts[t] || 0));
  const same = diffs.length === 0;
  check(`${label}：图上标记逐类等于后端真实判定`, same,
    same ? `共 ${actual.total} 个 · ${BS_TYPES.map(t => `${t}=${actual.counts[t]}`).join(' ')}`
         : `差异 ${diffs.map(t => `${t}: 图${actual.counts[t]} vs 期望${expect.counts[t]}`).join(', ')}`);
}

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-r08-chrome-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1680,1600', '--hide-scrollbars', 'about:blank'
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
    // 断言意图＝「页面徽标与版本唯一权威 config/version.json 一致」，不写死具体版本号（避免每次发版都要改探针）
    const apiVersion = (await (await fetch(BASE + '/api/version')).json()).version;
    const badgeVersion = await cdp.eval(`document.getElementById('appVersionBadge').textContent.trim()`);
    check('页面版本徽标与 /api/version（config/version.json 唯一权威）一致', !!apiVersion && badgeVersion === apiVersion,
      `徽标 ${badgeVersion} vs 接口 ${apiVersion}`);

    // ---------- 打开真实个股详情（全程不点击任何「调出」按钮） ----------
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(11000);
    const opened = await cdp.eval(`(() => { const s = appState.activeDetailStock; return s ? { name: s.name, days: (s.daily_bars || []).length, bs: ((s.chanlun || {}).buy_sell_points || []).length, intraday: !!(s.intraday_chanlun && s.intraday_chanlun.buy_sell_points) } : null; })()`);
    check('个股详情已加载真实日K与日线缠论', !!opened && opened.days > 0 && opened.bs > 0,
      opened ? `${opened.name} · 日K ${opened.days} 根 · 日线买卖点 ${opened.bs} 个` : '未加载');

    // ================= REQ-045: 默认双图（零点击） =================
    let layout = await cdp.eval(layoutProbe);
    check('REQ-045 分时图与日线图默认同时可见', layout.leftVisible && layout.rightVisible && !layout.lHidden && !layout.rHidden,
      JSON.stringify({ left: layout.leftVisible, right: layout.rightVisible }));
    check('REQ-045 首屏即为双图并排布局(dual-panel)', layout.dual && !layout.single, layout.dual ? 'dual-panel' : 'single-panel');
    check('REQ-045 「调出分时图/调出K线图」按钮默认隐藏（无需点击添加）', layout.addMinuteHidden && layout.addKlineHidden,
      JSON.stringify({ addMinuteHidden: layout.addMinuteHidden, addKlineHidden: layout.addKlineHidden }));
    check('REQ-045 左侧默认当日分时图、右侧默认日线图', layout.lMinuteSub === 'timeline' && layout.rGroup === 'daily',
      `left=${layout.lMinuteSub} right=${layout.rGroup}`);
    check('REQ-038 双图同高且左右等宽（未被本批改动破坏）', layout.lTop === layout.rTop && Math.abs(layout.lW - layout.rW) <= 2,
      `top ${layout.lTop}/${layout.rTop} · width ${layout.lW}/${layout.rW}`);
    shots.push(await cdp.shot('01-default-dual-panel.png'));

    // ================= REQ-044: 分时维度只剩两个子 Tab =================
    const subTabs = await cdp.eval(subTabProbe);
    check('REQ-044 分时维度只剩「当日分时 / 5分K线」两个子 Tab',
      Array.isArray(subTabs.subs) && subTabs.subs.length === 2 && subTabs.subs.join(',') === 'timeline,m5',
      JSON.stringify(subTabs.subs));
    check('REQ-044 页面中不再存在 1分K线 按钮', subTabs.hasM1Button === false);
    await cdp.eval(`switchMinuteSub('m1','left')`);
    await sleep(600);
    const afterM1 = await cdp.eval(`chartPanels.left.st.minuteSub`);
    check('REQ-044 调用已移除的 1分K线 不生效（保持当日分时）', afterM1 === 'timeline', `当前=${afterM1}`);

    // ================= REQ-041: 日线图默认自动标记 =================
    let right = await cdp.eval(bsProbe('right'));
    check('REQ-041 日线图零点击即出现买卖点标记', right.total > 0, `共 ${right.total} 个`);
    check('REQ-041 六个买卖点按钮默认全部开启（等级 3）',
      BS_TYPES.every(t => right.buttons[t] && right.buttons[t].active), JSON.stringify(BS_TYPES.map(t => right.buttons[t].active)));
    check('REQ-041 图上标注买卖点所属级别与六类计数', /自动标记买卖点（日线级别）/.test(right.summary), right.summary);
    let expect = await cdp.eval(expectProbe('right', '(stock && stock.chanlun) || null'));
    compareCounts('REQ-041 日线图', right, expect);
    check('REQ-041 每个标记的判定依据里写明级别', right.tips.length > 0 && right.tips.every(t => t.includes('级别：日线级别')),
      right.tips[0] ? right.tips[0].slice(0, 90) : '无标记');

    // 关闭买卖点后标记必须消失，再打开必须恢复
    await cdp.eval(`toggleChartBsLevel('buy',3,'right'); toggleChartBsLevel('sell',3,'right')`);
    await sleep(900);
    const off = await cdp.eval(bsProbe('right'));
    check('REQ-041 关闭买卖点按钮后标记消失（按钮仍为显隐开关）', off.total === 0, `关闭后 ${off.total} 个`);
    await cdp.eval(`toggleChartBsLevel('buy',3,'right'); toggleChartBsLevel('sell',3,'right')`);
    await sleep(900);
    const on = await cdp.eval(bsProbe('right'));
    check('REQ-041 重新开启后标记恢复', on.total === right.total, `恢复后 ${on.total} 个（原 ${right.total} 个）`);

    // ================= REQ-041 + REQ-042: 周线图 =================
    await cdp.eval(`switchKlineGroup('weekly','right')`);
    await sleep(6000);
    const weeklyState = await cdp.eval(`(() => { const s = appState.activeDetailStock; const a = (s.group_chanlun || {}).weekly; return a ? { level: a.level, bars: a.submitted_bars, total: (a.buy_sell_points || []).length, counts: a.counts } : null; })()`);
    check('REQ-041 周线图已由后端现场判定（真实周K序列提交）', !!weeklyState && weeklyState.level === 'weekly' && weeklyState.bars > 0,
      weeklyState ? `提交 ${weeklyState.bars} 根周K · 买卖点 ${weeklyState.total} 个` : '未取回判定');
    right = await cdp.eval(bsProbe('right'));
    expect = await cdp.eval(expectProbe('right', '((appState.activeDetailStock.group_chanlun || {}).weekly) || null'));
    check('REQ-041 周线图标注为「周线级别」', /自动标记买卖点（周线级别）/.test(right.summary), right.summary);
    compareCounts('REQ-041 周线图', right, expect);
    // 缩放到「全部」根数：买卖点必须完整落在图上（证明标记随显示窗口完整渲染，而不只是视窗内恰好 0 个）
    await cdp.eval(`showAllKlineBars('right')`);
    await sleep(2600);
    const weeklyAll = await cdp.eval(bsProbe('right'));
    const weeklyExpectAll = await cdp.eval(expectProbe('right', '((appState.activeDetailStock.group_chanlun || {}).weekly) || null'));
    check('REQ-041 周线图缩放到「全部」后买卖点完整渲染', weeklyAll.total > 0 && weeklyAll.total === weeklyExpectAll.total,
      `图上 ${weeklyAll.total} 个 vs 后端真实判定 ${weeklyExpectAll.total} 个`);
    compareCounts('REQ-041 周线图（全部 1265 根）', weeklyAll, weeklyExpectAll);
    await cdp.eval(`showAllKlineBars('right')`);
    await sleep(600);
    let amt = await cdp.eval(amountRecomputeProbe('weekly'));
    check('REQ-042 周线成交额与「日线逐日相加」独立重算逐根一致', amt.mismatchCount === 0,
      amt.mismatchCount === 0 ? `比对 ${amt.buckets} 根周K 全部一致 · 含估算日线 ${amt.derivedTotal} 根 · 缺失 ${amt.missingTotal} 根`
                              : JSON.stringify(amt.mismatches));
    check('REQ-042 周线图标注「成交额＝区间内日线成交额逐日相加」', amt.hasNote, amt.hasNote ? amt.derivedNote || '（本次无估算根，未显示估算后缀）' : '图上无该标注');
    shots.push(await cdp.shot('02-weekly-bs.png'));

    // ================= REQ-041 + REQ-043: 季线图 =================
    await cdp.eval(`switchKlineGroup('quarterly','right')`);
    await sleep(6000);
    const qState = await cdp.eval(`(() => { const s = appState.activeDetailStock; const a = (s.group_chanlun || {}).quarterly; return a ? { level: a.level, bars: a.submitted_bars, total: (a.buy_sell_points || []).length } : null; })()`);
    check('REQ-041 季线图已由后端现场判定', !!qState && qState.level === 'quarterly' && qState.bars > 0,
      qState ? `提交 ${qState.bars} 根季K · 买卖点 ${qState.total} 个` : '未取回判定');
    right = await cdp.eval(bsProbe('right'));
    expect = await cdp.eval(expectProbe('right', '((appState.activeDetailStock.group_chanlun || {}).quarterly) || null'));
    check('REQ-041 季线图标注为「季线级别」', /自动标记买卖点（季线级别）/.test(right.summary), right.summary);
    compareCounts('REQ-041 季线图', right, expect);
    amt = await cdp.eval(amountRecomputeProbe('quarterly'));
    check('REQ-043 季线成交额与「日线逐日相加」独立重算逐根一致', amt.mismatchCount === 0,
      amt.mismatchCount === 0 ? `比对 ${amt.buckets} 根季K 全部一致 · 含估算日线 ${amt.derivedTotal} 根 · 缺失 ${amt.missingTotal} 根`
                              : JSON.stringify(amt.mismatches));
    check('REQ-043 季线图标注成交额聚合口径', amt.hasNote);
    shots.push(await cdp.shot('03-quarterly-bs.png'));

    // ================= REQ-041: 5分K线 =================
    await cdp.eval(`switchKlineGroup('daily','right')`);
    await sleep(1200);
    await cdp.eval(`switchMinuteSub('m5','left')`);
    await sleep(7000);
    const m5State = await cdp.eval(`(() => { const s = appState.activeDetailStock; const a = (s.group_chanlun || {}).m5; const bars = ((s.minute_kline_loaders||{}).klinem5||{}).bars || []; return { analysis: a ? { level: a.level, bars: a.submitted_bars, total: (a.buy_sell_points||[]).length, error: a.error || null } : null, klineBars: bars.length }; })()`);
    check('REQ-041 5分K线已由后端现场判定', !!m5State.analysis && m5State.analysis.level === 'm5',
      JSON.stringify(m5State));
    let left = await cdp.eval(bsProbe('left'));
    let expectLeft = await cdp.eval(expectProbe('left', '((appState.activeDetailStock.group_chanlun || {}).m5) || null'));
    check('REQ-041 5分K线图标注为「5分级别」', /自动标记买卖点（5分级别）/.test(left.summary), left.summary);
    compareCounts('REQ-041 5分K线图', left, expectLeft);
    // 缩放到「全部」800 根 5分K线：买卖点必须完整渲染
    await cdp.eval(`showAllKlineBars('left')`);
    await sleep(2600);
    const m5All = await cdp.eval(bsProbe('left'));
    const m5ExpectAll = await cdp.eval(expectProbe('left', '((appState.activeDetailStock.group_chanlun || {}).m5) || null'));
    check('REQ-041 5分K线缩放到「全部」后买卖点完整渲染', m5All.total > 0 && m5All.total === m5ExpectAll.total,
      `图上 ${m5All.total} 个 vs 后端真实判定 ${m5ExpectAll.total} 个`);
    compareCounts('REQ-041 5分K线图（全部 800 根）', m5All, m5ExpectAll);
    shots.push(await cdp.shot('04-m5-bs.png'));

    // ================= REQ-041: 当日分时 =================
    await cdp.eval(`switchMinuteSub('timeline','left')`);
    await sleep(4000);
    left = await cdp.eval(bsProbe('left'));
    expectLeft = await cdp.eval(expectProbe('left', '(stock && stock.intraday_chanlun) || null'));
    const intradayLevel = await cdp.eval(`(() => { const a = (appState.activeDetailStock||{}).intraday_chanlun; return a ? (a.level || null) : null; })()`);
    if (expectLeft && !expectLeft.error) {
      check('REQ-041 当日分时图标注为「分时级别」', /自动标记买卖点（分时级别）/.test(left.summary), left.summary);
      compareCounts('REQ-041 当日分时图', left, expectLeft);
    } else {
      check('REQ-041 分时来源不可用时如实提示而非伪造标记', left.total === 0,
        `level=${intradayLevel} · 原因：${expectLeft ? expectLeft.error : '未获取'}（未获取时不渲染任何标记）`);
    }
    shots.push(await cdp.shot('05-timeline-bs.png'));

    // ================= 反向验证：级别隔离 =================
    await cdp.eval(`switchMinuteSub('m5','left'); switchKlineGroup('weekly','right')`);
    await sleep(3000);
    const isolated = await cdp.eval(`(() => {
      const l = document.getElementById('chartSvgContainerLeft').textContent.replace(/\\s+/g,' ');
      const r = document.getElementById('chartSvgContainerRight').textContent.replace(/\\s+/g,' ');
      return { left: (l.match(/自动标记买卖点（[^）]*）/)||[''])[0], right: (r.match(/自动标记买卖点（[^）]*）/)||[''])[0] };
    })()`);
    check('REQ-041 左右两图各自标注自己的级别（不得串级）',
      isolated.left.includes('5分级别') && isolated.right.includes('周线级别'), JSON.stringify(isolated));
    shots.push(await cdp.shot('06-level-isolation.png'));

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
  console.log(`\n=== R08 真机验证：${report.passed}/${report.total} PASS ===`);
  if (report.failed) {
    console.log('失败项：\n' + results.filter(r => !r.ok).map(r => ` - ${r.name}：${r.detail}`).join('\n'));
    process.exit(1);
  }
})();
