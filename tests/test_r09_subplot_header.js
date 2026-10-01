// R09 (REQ-046 行情日期精确到分 / REQ-047 副图标题与概要平铺不重叠) 前端静态回归
// 模型：与 test_r04 / test_r08 相同的「全量源码 + vm 沙箱」装载方式，只补 DOM 桩；
//       断言对象永远是 web/app.js 里的那一份真实实现。全部为构造数据，不触网、不碰产品库。
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const { loadWebSource } = require('./load_web_sources');
const src = loadWebSource();  // 需求REQ-053: 按页面顺序装载 util.js + app.js

// ---------- DOM 桩：按 id 缓存，便于断言徽标真实写入的文本 ----------
const elements = new Map();
function stubEl(id) {
  return {
    id: id || null,
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    dataset: {}, children: [], value: '', textContent: '', innerHTML: '', hidden: false,
    title: '', className: '',
    appendChild() {}, removeChild() {}, remove() {}, setAttribute() {}, getAttribute: () => null,
    addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, insertAdjacentHTML() {}, focus() {}, click() {}, contains: () => false
  };
}
const ctx = {
  console, window: {}, navigator: { userAgent: 'node-vm' },
  location: { href: 'http://127.0.0.1:0/', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  setTimeout, clearTimeout, setInterval, clearInterval,
  Math, Number, Object, Array, JSON, Map, Set, Date, isNaN, isFinite, parseFloat, parseInt,
  String, Boolean, Error, Promise, RegExp, Symbol, encodeURIComponent, decodeURIComponent
};
ctx.document = {
  getElementById: (id) => { if (!elements.has(id)) elements.set(id, stubEl(id)); return elements.get(id); },
  querySelector: () => stubEl(), querySelectorAll: () => [],
  createElement: () => stubEl(), addEventListener() {}, removeEventListener() {},
  documentElement: stubEl(), body: stubEl(), title: 'test'
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'web/app.js' });
const get = expr => vm.runInContext(expr, ctx);
const badge = elements.get('dataValidityBadge');
assert(badge, 'app.js 必须缓存 dataValidityBadge 元素');

// ================= REQ-046: 顶栏「行情日期」精确到分 =================
// 1) 来源 14 位真实时间戳（后端 quote_datetime.raw 的形态）
ctx.updateDataValidityDateBadge('20260924131808');
assert.equal(badge.textContent, '📅 行情日期: 2026年9月24日 13:18', '14 位时间戳必须渲染到「分」');
assert.match(badge.title, /精确到分/, 'title 必须说明精度为分钟');
assert.match(badge.title, /20260924131808/, 'title 必须保留来源原始值便于核对');

// 2) 后端对象形态（quote_datetime）
ctx.updateDataValidityDateBadge({ raw: '20260923153400', date: '2026-09-23', time: '15:34', datetime: '2026-09-23 15:34', precision: 'minute' });
assert.equal(badge.textContent, '📅 行情日期: 2026年9月23日 15:34', '对象形态必须同样精确到分，且与用户示例格式一致');

// 3) 带秒的时间串只取到分
ctx.updateDataValidityDateBadge('2026-09-23 15:34:59');
assert.equal(badge.textContent, '📅 行情日期: 2026年9月23日 15:34', '秒必须被截断到分，不显示秒');

// 4) 来源只给日期 → 如实降级为「日」，绝不臆造时刻
ctx.updateDataValidityDateBadge('20260923');
assert.equal(badge.textContent, '📅 行情日期: 2026年9月23日', '只有日期时不得补造时刻');
assert.doesNotMatch(badge.textContent, /\d{2}:\d{2}/, '无真实时刻时不得出现任何 HH:MM');
assert.match(badge.title, /只提供到日/, 'title 必须如实说明只到日');

// 5) 完全拿不到 → 未获取（不得用本地时钟冒充）
ctx.updateDataValidityDateBadge(null);
assert.equal(badge.textContent, '📅 行情日期未获取', '无真实行情时间时必须显示未获取');
assert.match(badge.title, /未获取/, 'title 必须说明未获取');

// ================= REQ-047: 标题与统计概要按实测宽度平铺 =================
const M = { top: 20, right: 65, bottom: 25, left: 65 };
const W = 920;           // 当前个股图表画布宽（REQ-047 验收基准）
const INNER_W = W - M.left - M.right;
const MAX_RIGHT = M.left + INNER_W - 6;
const LONG_TITLE = '副图：成交额（含估算：均价×成交量）';

// 宽度估算器必须随文本变长而单调增，并且对中英混排给出正数
const wShort = ctx.estimateSvgTextWidth('副图：成交量', 10);
const wLong = ctx.estimateSvgTextWidth(LONG_TITLE, 10);
assert(wShort > 0 && wLong > wShort, '长标题的估算宽度必须大于短标题');

const AMT_ITEMS = [
  { label: '总和:', value: '164.66亿', fill: '#f59e0b' },
  { label: '平均:', value: '5.49亿', fill: '#f59e0b' },
  { label: '地量(最小):', value: '2.61亿', fill: '#10b981' },
  { label: '天量(最大):', value: '18.86亿', fill: '#ef4444' },
  { label: '中位数:', value: '4.94亿', fill: '#facc15' }
];

/** 从排布器产出的 SVG 中解析出每个 <text> 的 x 与该文本的估算宽度，用于严格判定零重叠 */
function parseTexts(svg, fontSize = 10) {
  const out = [];
  const re = /<text x="([\d.]+)" y="([\d.]+)"[^>]*>([\s\S]*?)<\/text>/g;
  let m;
  while ((m = re.exec(svg)) !== null) {
    const text = m[3].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
    out.push({ x: Number(m[1]), y: Number(m[2]), text, width: ctx.estimateSvgTextWidth(text, fontSize) });
  }
  return out;
}
/** 只取「副图表头」范围的文本：标题行 + sub-summary-group 内的统计项（其余同 y 的坐标轴标签不参与判定） */
function headerTexts(svg, titles, fontSize = 10) {
  const out = [];
  const groupRe = /<g class="sub-summary-group">([\s\S]*?)<\/g>/g;
  let g;
  while ((g = groupRe.exec(svg)) !== null) out.push(...parseTexts(g[1], fontSize));
  parseTexts(svg, fontSize).forEach(t => { if (titles.indexOf(t.text) >= 0) out.push(t); });
  return out;
}
function assertNoOverlap(texts, label) {
  const rows = new Map();
  texts.forEach(t => {
    const key = t.y;
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key).push(t);
  });
  for (const [y, list] of rows) {
    list.sort((a, b) => a.x - b.x);
    for (let i = 0; i + 1 < list.length; i++) {
      const gap = list[i + 1].x - (list[i].x + list[i].width);
      assert(gap >= 0, `${label} 第 ${y} 行出现重叠：「${list[i].text}」右缘 ${(list[i].x + list[i].width).toFixed(1)} > 下一项左缘 ${list[i + 1].x.toFixed(1)}`);
    }
  }
  return rows;
}

// 1) 成交额档（含最长标题）——必须单行、零重叠、且不越出绘图区右缘
const amtHeader = ctx.layoutSubplotHeader({ x0: M.left + 8, y: 100, title: LONG_TITLE, items: AMT_ITEMS, maxRight: MAX_RIGHT, fontSize: 10 });
assert.equal(amtHeader.rows, 1, '成交额档位（含估算长标题）必须单行平铺');
assert.equal(amtHeader.dropped, 0, '不得丢弃任何统计项');
assert(amtHeader.endX <= MAX_RIGHT + 0.01, `统计行不得越出绘图区右缘（实际 ${amtHeader.endX.toFixed(1)} > ${MAX_RIGHT}）`);
const amtTexts = parseTexts(amtHeader.svg);
assert.equal(amtTexts.length, 6, '标题 + 5 个统计项必须全部输出');
const titleText = amtTexts.find(t => t.text === LONG_TITLE);
assert(titleText, '标题必须原样输出（含 REQ-025 的估算口径后缀）');
AMT_ITEMS.forEach(it => assert(amtTexts.some(t => t.text.includes(it.value)), `统计项 ${it.label}${it.value} 不得丢项`));
assertNoOverlap(amtTexts, '成交额档');

// 2) 换手率 / 成交量档同样零重叠
const TURN_ITEMS = [
  { label: '总和:', value: '12.34%', fill: '#f59e0b' },
  { label: '平均:', value: '0.41%', fill: '#c084fc' },
  { label: '地量(最小):', value: '0.12%', fill: '#10b981' },
  { label: '天量(最大):', value: '0.98%', fill: '#ef4444' },
  { label: '中位数:', value: '0.37%', fill: '#facc15' }
];
const turnHeader = ctx.layoutSubplotHeader({ x0: M.left + 8, y: 100, title: '副图：换手率', items: TURN_ITEMS, maxRight: MAX_RIGHT, fontSize: 10 });
assert.equal(turnHeader.rows, 1, '换手率档必须单行平铺');
assertNoOverlap(parseTexts(turnHeader.svg), '换手率档');

const VOL_ITEMS = [
  { label: '总和:', value: '38.3万手', fill: '#f59e0b' },
  { label: '平均:', value: '3182手', fill: '#38bdf8' },
  { label: '地量(最小):', value: '334手', fill: '#10b981' },
  { label: '天量(最大):', value: '1.3万手', fill: '#ef4444' },
  { label: '中位数:', value: '2527手', fill: '#facc15' }
];
const volHeader = ctx.layoutSubplotHeader({ x0: M.left + 8, y: 100, title: '副图：成交量', items: VOL_ITEMS, maxRight: MAX_RIGHT, fontSize: 10 });
assert.equal(volHeader.rows, 1, '成交量档必须单行平铺');
assertNoOverlap(parseTexts(volHeader.svg), '成交量档');

// 3) 极窄容器：允许换行，但绝不允许重叠、绝不丢项
const narrow = ctx.layoutSubplotHeader({ x0: M.left + 8, y: 100, title: LONG_TITLE, items: AMT_ITEMS, maxRight: M.left + 300, fontSize: 10, maxRows: 4 });
assert(narrow.rows >= 2, '容器极窄时必须换行而不是叠画');
assert.equal(narrow.dropped, 0, '换行同样不得丢项');
assertNoOverlap(parseTexts(narrow.svg), '极窄容器');

// ================= 真实 SVG 渲染：标题与统计项由同一排布器输出 =================
function mkBars(n, derived = false) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const base = 10 + i * 0.1;
    out.push({
      date: `2026-09-${String((i % 27) + 1).padStart(2, '0')}`,
      open: base, close: base + 0.2, high: base + 0.5, low: base - 0.3,
      volume: 1000 + i, amount_yi: derived ? null : (1 + i * 0.01)
    });
  }
  return out;
}
vm.runInContext("appState.chartPanelSlot = 'right'; chartPanels.right.st.klineCount = 30; chartPanels.right.st.availableCount = 30;", ctx);
const renderK = (bars, subplot) => ctx.generateDailyKlineSVG(bars, subplot, W, 440, 270, 110, M, null, 'right', null, 'klinedaily');

const TITLES = ['副图：成交额', LONG_TITLE, '副图：成交量', '副图：换手率'];

const kAmtSvg = renderK(mkBars(30), 'amt');
const kAmtTexts = headerTexts(kAmtSvg, TITLES);
assert(kAmtTexts.some(t => t.text.includes('总和:')), 'K线成交额副图必须输出平铺统计行');
assert(kAmtTexts.some(t => t.text === '副图：成交额'), 'K线成交额副图必须输出副图标题');
assertNoOverlap(kAmtTexts, 'K线成交额副图实际 SVG');
// 需求REQ-047: 「总和」必须与 computeWindowTotalAmount 同源同口径（历史实现引用了不存在的 totalYi 字段，恒显示 --）
const expectTotal = mkBars(30).reduce((a, b) => a + b.amount_yi, 0).toFixed(2);
const sumText = (kAmtTexts.find(t => t.text.startsWith('总和:')) || {}).text || '';
assert.equal(sumText, `总和: ${expectTotal}亿`, `成交额副图「总和」必须等于窗口内真实成交额之和（期望 ${expectTotal}亿）`);

const kVolSvg = renderK(mkBars(30), 'vol');
assertNoOverlap(headerTexts(kVolSvg, TITLES), 'K线成交量副图实际 SVG');

const kTurnSvg = renderK(mkBars(30), 'turnover_rate');
assertNoOverlap(headerTexts(kTurnSvg, TITLES), 'K线换手率副图实际 SVG');

// 估算兜底（来源无 amount_yi）时，标题必须仍带 REQ-025 口径后缀，且与统计项不重叠
const kDerivedSvg = renderK(mkBars(30, true), 'amt');
assert.match(kDerivedSvg, /副图：成交额（含估算：均价×成交量）/, '估算口径后缀必须保留');
const derivedSum = (headerTexts(kDerivedSvg, TITLES).find(t => t.text.startsWith('总和:')) || {}).text || '';
assert.match(derivedSum, /^总和: [\d.]+亿（含估算）$/, '全部为估算样本时「总和」必须显式标注含估算，不得伪装成来源原始值');
assertNoOverlap(headerTexts(kDerivedSvg, TITLES), 'K线成交额副图（含估算口径）');

// 分时副图同样必须由排布器输出且零重叠
const tlItems = mkBars(60).map((b, i) => Object.assign({}, b, { time: `${String(9 + Math.floor(i / 60)).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}`, price: b.close, avg_price: b.close }));
const tlSvg = ctx.generateTimelineSVG(tlItems, tlItems[0].price, 'vol', W, 440, 270, 110, M, null, 'left');
assertNoOverlap(headerTexts(tlSvg, TITLES), '分时成交量副图实际 SVG');

// ================= 指数副图：不得输出 0.00亿 / 不得用「点位×成交量」冒充成交额 =================
// REQ-032: 指数成交额样本只采信来源原始披露值，兜底估算值（点位×成交量）必须整段剔除
const idxNoSource = ctx.indexDisclosedAmountSamples([
  { amount_yi: null, volume: 186492535, open: 2870, close: 2880, high: 2890, low: 2860 },
  { amount_yi: null, volume: 200000000, open: 2880, close: 2900, high: 2910, low: 2870 }
]);
assert.equal(idxNoSource.length, 0, '指数来源未披露成交额时，点位×成交量的估算值绝不能被采信');
const idxReal = ctx.indexDisclosedAmountSamples([
  { amount_yi: 3.5, volume: 1 }, { amount: 250000000, volume: 1 }, { amount_yi: null, volume: 1, price: 10 }
]);
assert.deepEqual(Array.from(idxReal), [3.5, 2.5], '来源真实披露的 amount_yi 与 amount 必须保留，估算值必须剔除');
// 指数辅助线的交易面积同样不得用估算值求和，也不得以 0.00亿 冒充「面积为 0」
const idxArea = ctx.computeTradeArea([
  { date: '2026-09-01', open: 3900, close: 3910, high: 3920, low: 3890, volume: 186492535, amount_yi: null },
  { date: '2026-09-02', open: 3910, close: 3900, high: 3930, low: 3880, volume: 176492535, amount_yi: null }
], 3915, 0, { disclosedOnly: true });
assert.equal(idxArea.tradeAreaYi, null, '指数（来源未披露成交额）的交易面积必须为不可得，不得求和估算值');
assert.match(idxArea.reason, /未披露/, '交易面积不可得必须给出原因');
assert.equal(ctx.formatTradeArea(idxArea), '交易面积: 未交汇', '交易面积不可得时统一显示未交汇，不得出现 0.00亿');

const idxStats = ctx.calculateDistributionSummary([]);
assert.equal(idxStats.mean, 0, '空样本的四维分布为 0 —— 因此调用方必须先判定样本是否可得');
const idxHeader = ctx.layoutSubplotHeader({
  x0: M.left + 8, y: 100, title: '💰 副图: 成交金额 (亿元)',
  items: [{ label: '当前来源未披露该指数成交额，四维分布不可得（不以点位×成交量推测值充当）', value: null, fill: '#94a3b8' }],
  maxRight: M.left + 770 - 6, fontSize: 10, titleFill: '#f59e0b', titleFontSize: 11
});
assert.doesNotMatch(idxHeader.svg, /0\.00亿/, '指数成交额不可得时不得输出 0.00亿');
assert.match(idxHeader.svg, /不可得/, '指数成交额不可得时必须如实标注');
assertNoOverlap(parseTexts(idxHeader.svg, 11), '指数副图不可得提示');

// ---------- REQ-037 口径修订（v5.4.1）：首屏两图副图档位统一为「成交额」 ----------
// 背景：左右面板副图控件已合并为唯一「幅图联动」控件（单点切换、两图同步），首屏两图若仍按维度分叉
// （K线＝成交额 / 分时＝成交量），就会出现「控件高亮成交额、左图显示成交量」的自相矛盾。
const defaultFnSrc = (src.match(/function panelDefaultSubplot\([^)]*\)\s*\{([\s\S]*?)\n\}/) || [])[1] || '';
assert.match(defaultFnSrc, /return 'amt';/, '副图默认档位必须恒为成交额');
assert.ok(!/'vol'/.test(defaultFnSrc), '副图默认档位不得再按维度分叉（分时不再默认成交量）');
assert.match(src, /subplot:\s*'amt',/, 'createPanelChartState 的面板默认副图档位必须是成交额');
assert.ok(!/dimension === 'kline' \? 'amt' : 'vol'/.test(src), '旧的按维度分叉写法必须已移除');
assert.match(src, /if \(!st\.subplotTouched\) st\.subplot = panelDefaultSubplot\(st\);/,
  '手动选择保护必须保留（subplotTouched 优先）');

console.log('PASS: REQ-046 行情日期精确到分（含降级与未获取）；REQ-047 副图标题与统计概要平铺零重叠（含换行兜底与指数不可得口径）；REQ-037 修订（首屏副图档位统一为成交额 + 手动选择保护）');
