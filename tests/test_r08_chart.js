// R08 (REQ-041/042/043/044/045) 前端口径回归
// 模型：与 test_r04_chart_viewport.js 相同的「全量源码 + vm 沙箱」加载方式 ——
//       直接在整个 web/app.js 上求值，只补 DOM 桩，保证断言对象永远是文件里的那一份实现，
//       避免按标记切片拼装时「后加载的同名函数静默覆盖旧副本」导致测试跑的不是真实代码。
// 全部为构造数据，不触网、不触碰产品数据库与浏览器。
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const { loadWebSource, loadIndexHtml } = require('./load_web_sources');
const src = loadWebSource();  // 需求REQ-053: 按页面顺序装载 util.js + app.js
const html = loadIndexHtml();

function stubEl() {
  return {
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    dataset: {}, children: [], value: '', textContent: '', innerHTML: '', hidden: false,
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
  getElementById: () => stubEl(), querySelector: () => stubEl(), querySelectorAll: () => [],
  createElement: () => stubEl(), addEventListener() {}, removeEventListener() {},
  documentElement: stubEl(), body: stubEl(), title: 'test'
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'web/app.js' });
const get = expr => vm.runInContext(expr, ctx);

// ================= REQ-044: 分时维度移除「1分K线」Tab =================
// 前端子 Tab 集合只剩「当日分时 / 5分K线」；klinem1 不再有入口，旧键也不会切到该颗粒度。
assert.deepEqual(Array.from(get('MINUTE_SUBTABS.map(t => t.key)')), ['timeline', 'm5'],
  '分时维度必须只剩「当日分时 / 5分K线」两个子 Tab');
assert.equal(get('MINUTE_SUBTABS.some(t => t.period === "klinem1")'), false, '不得再有 1分K线 的子 Tab');
assert.equal(get('MINUTE_SUBTAB_MAP.m1 === undefined'), true, '子 Tab 映射中不得再有 m1');
assert.equal(get('createPanelChartState("minute").minuteSub'), 'timeline', '分时面板默认必须是「当日分时」');
// 旧调用 switchMinuteSub('m1') 必须被拒绝并保持原颗粒度（而不是切到一个不存在的 Tab）
vm.runInContext('switchMinuteSub("m1", "left")', ctx);
assert.equal(get('chartPanels.left.st.minuteSub'), 'timeline', 'm1 已移除，调用必须被拒绝且不改变当前颗粒度');
// 旧键 klinem1 的兼容入口必须回落到 5分K线，不得再指向 m1
assert.match(src, /p === 'kline5m' \|\| p === 'klinem5' \|\| p === 'klinem1'\) return switchMinuteSub\('m5'/,
  '旧键 klinem1 必须回落到 5分K线');
// 页面静态标记：不得再出现 1分K线 的按钮或其文案
assert.equal(/data-sub="m1"/.test(html), false, 'index.html 不得再渲染 1分K线 按钮');
assert.equal(/1分K线/.test(html), false, 'index.html 不得再出现「1分K线」文案');

// ================= REQ-045: 默认「分时图 + 日线图」双图，无需点击添加 =================
assert.equal(get('chartPanels.left.visible'), true, '分时面板必须默认可见');
assert.equal(get('chartPanels.right.visible'), true, '日线面板必须默认可见');
assert.equal(get('chartPanels.left.st.minuteSub'), 'timeline', '左侧默认是当日分时图');
assert.equal(get('chartPanels.right.st.klineGroup'), 'daily', '右侧默认是日线图');
assert.match(html, /id="chartPanelRow" class="chart-panel-row dual-panel"/, '首屏布局必须是双图并排（dual-panel）');
assert.match(html, /id="btnAddMinutePanel" class="chart-open-btn" hidden/, '两图默认已显示，「调出分时图」按钮首屏必须隐藏');
// 面板可见性不得持久化：每次进入详情页都必须回到「双图默认态」（面板状态写回函数内不得出现 localStorage）
const persistStart = src.indexOf('function persistPanelFromAppState(');
assert.ok(persistStart > 0, '未定位 persistPanelFromAppState');
const persistBody = src.slice(persistStart, src.indexOf('\n}', persistStart));
assert.equal(/localStorage/.test(persistBody), false, '面板状态写回函数不得使用 localStorage（否则收起过的面板会被记住）');

// ================= REQ-041: 买卖点默认全开 + 各颗粒度级别隔离 =================
assert.equal(get('DEFAULT_BS_LEVEL'), 3, '买卖点默认等级必须是 3（第 1/2/3 类全开）');
assert.equal(get('appState.bsBuyLevel'), 3, '全局默认买点等级必须是 3（打开页面即自动标记）');
assert.equal(get('appState.bsSellLevel'), 3, '全局默认卖点等级必须是 3');
assert.equal(get('createPanelChartState("kline").bsBuyLevel'), 3, 'K线面板默认买点等级必须是 3');
assert.equal(get('createPanelChartState("minute").bsSellLevel'), 3, '分时面板默认卖点等级必须是 3');
assert.equal(get('chartBsLevelActive()'), true, '默认状态下买卖点标记必须处于激活（自动标记）状态');
// 级别标签必须齐全，且每个级别都能拿到自己的名称（不得把周线读成日线）
assert.deepEqual(Object.keys(get('CHANLUN_LEVEL_LABELS')).sort(),
  ['daily', 'intraday', 'm5', 'quarterly', 'weekly'], '级别标签必须覆盖日线/分时/5分/周线/季线');
assert.equal(get('chanlunLevelLabel({ level: "weekly" }, "klineweekly")'), '周线级别');
assert.equal(get('chanlunLevelLabel({ level: "quarterly" }, "klinequarterly")'), '季线级别');
assert.equal(get('chanlunLevelLabel({ level: "intraday" }, "timeline")'), '分时级别');
assert.equal(get('chanlunLevelLabel({}, "klinedaily")'), '日线级别');
assert.deepEqual(Array.from(get('CHANLUN_BS_TYPE_ORDER.map(x => x[1])')),
  ['1买', '2买', '3买', '1卖', '2卖', '3卖'], '图上六类买卖点标注顺序必须固定');
// 缓存键：只有「需要现场提交K线判定」的颗粒度才有键；日线与当日分时走后端既有入口
assert.equal(get('panelChanlunCacheKey({ dimension: "kline", klineGroup: "weekly" })'), 'weekly');
assert.equal(get('panelChanlunCacheKey({ dimension: "kline", klineGroup: "quarterly" })'), 'quarterly');
assert.equal(get('panelChanlunCacheKey({ dimension: "minute", minuteSub: "m5" })'), 'm5');
assert.equal(get('panelChanlunCacheKey({ dimension: "minute", minuteSub: "timeline" })'), null);
assert.equal(get('panelChanlunCacheKey({ dimension: "kline", klineGroup: "daily" })'), null);

// ================= REQ-042/043: 周/季成交额＝日线成交额逐日相加 =================
// 一个自然周内 5 个交易日：前 2 天有真实成交额，中间 2 天来源未披露（走「均价×成交量」兜底），
// 最后 1 天成交量也为 0（连兜底都不可得）。聚合结果必须与日线图逐日相加完全一致。
const DAILY = [
  { date: '2026-09-21', open: 10, close: 11, high: 12, low: 9, volume: 1000, amount_yi: 1.5 },
  { date: '2026-09-22', open: 11, close: 12, high: 13, low: 10, volume: 2000, amount_yi: 2.5 },
  { date: '2026-09-23', open: 12, close: 13, high: 14, low: 11, volume: 3000, amount_yi: null },
  { date: '2026-09-24', open: 13, close: 14, high: 15, low: 12, volume: 4000, amount_yi: null },
  { date: '2026-09-25', open: 14, close: 15, high: 16, low: 13, volume: 0, amount_yi: null }
];
ctx.__daily = DAILY;
const weekly = get('aggregateBarsForGroup(__daily, "weekly")');
assert.equal(weekly.length, 1, '同一自然周必须聚合成 1 根周K');
const w0 = weekly[0];
const expectedDerived1 = ((12 + 13 + 14 + 11) / 4 * 3000 * 100) / 1e8;
const expectedDerived2 = ((13 + 14 + 15 + 12) / 4 * 4000 * 100) / 1e8;
const expectedTotal = 1.5 + 2.5 + expectedDerived1 + expectedDerived2;
assert.ok(Math.abs(w0.amount_yi - expectedTotal) < 1e-6,
  `周K成交额必须等于日线逐日相加 ${expectedTotal}，实际 ${w0.amount_yi}`);
assert.equal(w0.amount_derived_days, 2, '必须如实记录含估算的日线根数（2 根）');
assert.equal(w0.amount_derived, true, '含估算时聚合根必须带 amount_derived 标记');
assert.equal(w0.amount_missing_days, 1, '连兜底都不可得的日线根数必须如实记录');
assert.equal(w0.amount_partial, true, '覆盖不完整必须标记');
assert.equal(w0.amounts_summed, 4, '实际参与相加的日线根数必须如实记录');
assert.equal(w0.aggregated_from, 5, '聚合来源根数必须是 5 根日线');
// 参考实现：与「逐日调用日线图同一解析口径后求和」逐位一致
const manual = DAILY.reduce((sum, b) => {
  const r = get('resolveKlineAmount')(b);
  return r.amountYi === null ? sum : sum + r.amountYi;
}, 0);
assert.ok(Math.abs(w0.amount_yi - manual) < 1e-9, '聚合值必须与日线图显示值的逐日相加逐位一致');

// 全部不可得时必须为 null（绝不以 0 充当成交额）
ctx.__dead = DAILY.map(b => Object.assign({}, b, { amount_yi: null, volume: 0 }));
const dead = get('aggregateBarsForGroup(__dead, "weekly")');
assert.equal(dead[0].amount_yi, null, '一根都不可得时成交额必须为空，不得为 0');
assert.equal(dead[0].amount_missing_days, 5, '全部不可得时必须如实记录 5 根缺失');

// 季线同口径：跨两个自然季 → 2 根，成交额各自独立相加
ctx.__cross = [
  { date: '2026-03-30', open: 10, close: 11, high: 12, low: 9, volume: 1000, amount_yi: 1.0 },
  { date: '2026-03-31', open: 11, close: 12, high: 13, low: 10, volume: 1000, amount_yi: 2.0 },
  { date: '2026-06-01', open: 12, close: 13, high: 14, low: 11, volume: 1000, amount_yi: 3.0 }
];
const quarterly = get('aggregateBarsForGroup(__cross, "quarterly")');
assert.equal(quarterly.length, 2, '跨季度必须聚合成 2 根季K');
assert.ok(Math.abs(quarterly[0].amount_yi - 3.0) < 1e-9, 'Q1 两根日线成交额相加必须为 3.0');
assert.ok(Math.abs(quarterly[1].amount_yi - 3.0) < 1e-9, 'Q2 成交额必须独立相加');

// ================= REQ-042/043: 聚合口径必须画在图上（含估算 N 根日线） =================
const KLINES = [
  { date: '2026-08-29', open: 10, close: 11, high: 12, low: 9, volume: 1000, amount_yi: 1.2, amount_derived_days: 3, amount_missing_days: 1 },
  { date: '2026-09-05', open: 11, close: 12, high: 13, low: 10, volume: 1100, amount_yi: 1.4, amount_derived_days: 0, amount_missing_days: 0 },
  { date: '2026-09-12', open: 12, close: 13, high: 14, low: 11, volume: 1200, amount_yi: 1.6, amount_derived_days: 1, amount_missing_days: 0 }
];
const M = { top: 20, right: 65, bottom: 25, left: 65 };
const bsAnalysis = {
  level: 'weekly', status: 'available',
  buy_sell_points: [
    { type: 'buy3', time: '2026-09-05', price: 10, index: 1, status: 'confirmed', label: '第三类买点', reason: '中枢 ZG 100.00，回调低点 101.00 未回中枢' },
    { type: 'sell2', time: '2026-09-12', price: 14, index: 2, status: 'confirmed', label: '第二类卖点', reason: '反弹高点 140.00 未创新高' }
  ],
  counts: { buy1: 0, buy2: 0, buy3: 1, sell1: 0, sell2: 1, sell3: 0 },
  pens: [], segments: [], pivots: [], divergences: [], ma_entanglements: [], ma: {}, parameters: { ma_periods: [5, 10, 20] }
};
const svgWeekly = get('generateDailyKlineSVG')(KLINES, 'amt', 860, 440, 270, 110, M, bsAnalysis, 'right', null, 'klineweekly');
assert.match(svgWeekly, /成交额＝区间内日线成交额逐日相加/, '周线图必须标注成交额由日线逐日相加');
assert.match(svgWeekly, /含估算 4 根日线/, '必须标注含估算的日线根数（3+0+1＝4）');
assert.match(svgWeekly, /1 根日线成交额不可得未计入/, '覆盖不完整必须如实标注缺失日线根数');
assert.match(svgWeekly, /自动标记买卖点（周线级别）/, '图上必须标注买卖点所属级别');
assert.match(svgWeekly, /3买 1/, '图上必须给出六类买卖点的真实识别数量');
assert.match(svgWeekly, /2卖 1/, '图上必须给出六类买卖点的真实识别数量');
assert.match(svgWeekly, /class="chanlun-bs chanlun-buy3"/, '买卖点必须实际绘制在图上');
assert.match(svgWeekly, /级别：周线级别/, '每个标记的判定依据里必须写明级别');
// 日线图不得出现聚合口径标注（成交额本来就来自日线本身）
const svgDaily = get('generateDailyKlineSVG')(KLINES, 'amt', 860, 440, 270, 110, M, null, 'right', null, 'klinedaily');
assert.equal(/成交额＝区间内日线成交额逐日相加/.test(svgDaily), false, '日线图不得出现周/季聚合口径标注');

// ================= REQ-041: 提交给后端的 K线序列构造 =================
ctx.__stock = { code: 'sh600519', daily_bars: DAILY, __groupBars: {} };
ctx.__p = get('createPanelChartState("kline")');
ctx.__p.klineGroup = 'weekly';
const weeklyPayload = get('buildPanelChanlunPayload(__stock, __p)');
assert.equal(weeklyPayload.level, 'weekly', '周线面板必须提交 level=weekly');
assert.equal(weeklyPayload.bars.length, 1, '提交的必须是聚合后的周K序列');
assert.equal(weeklyPayload.bars[0].date, '2026-09-25', '周K日期取该区间最后一个交易日');
assert.deepEqual(Object.keys(weeklyPayload.bars[0]).sort(),
  ['close', 'date', 'high', 'low', 'open', 'volume'], '提交字段必须严格为分析所需字段');
// 分钟K线：日期必须与时间合成唯一键（否则后端会按「日期必须唯一且递增」拒绝）
ctx.__stockMin = {
  code: 'sh600519', __groupBars: {},
  minute_kline_loaders: { klinem5: { bars: [
    { date: '2026-09-23', time: '09:35', open: 10, close: 10.2, high: 10.3, low: 9.9, volume: 100 },
    { date: '2026-09-23', time: '09:40', open: 10.2, close: 10.4, high: 10.5, low: 10.1, volume: 120 }
  ] } }
};
ctx.__p5 = get('createPanelChartState("minute")');
ctx.__p5.minuteSub = 'm5';
const m5Payload = get('buildPanelChanlunPayload(__stockMin, __p5)');
assert.equal(m5Payload.level, 'm5', '5分K线面板必须提交 level=m5');
assert.deepEqual(Array.from(m5Payload.bars.map(b => b.date)),
  ['2026-09-23 09:35', '2026-09-23 09:40'], '分钟K线必须以「日期 时间」为唯一递增键');
// 价格不完整时不得提交（绝不让后端按缺失值判定）
ctx.__stockBad = { code: 'sh600519', __groupBars: {}, daily_bars: [Object.assign({}, DAILY[0], { high: null })] };
ctx.__pBad = get('createPanelChartState("kline")');
ctx.__pBad.klineGroup = 'weekly';
assert.equal(get('buildPanelChanlunPayload(__stockBad, __pBad)'), null, '价格不完整时必须拒绝提交');

console.log('PASS: R08 —— 分时移除1分Tab / 默认双图 / 买卖点默认全开且级别隔离 / 周季成交额按日线逐日相加并标注 (REQ-041/042/043/044/045)');
