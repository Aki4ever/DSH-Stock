// R04 (REQ-022/023/024/025/026/035) 视图口径与辅助线指标回归
// 全部为构造数据，只在隔离的 vm 上下文中执行，不触碰产品数据库与浏览器。
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const { loadWebSource } = require('./load_web_sources');
const src = loadWebSource();  // 需求REQ-053: 按页面顺序装载 util.js + app.js

function slice(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  assert(a >= 0, `未定位起始标记: ${startMarker}`);
  const b = src.indexOf(endMarker, a);
  assert(b > a, `未定位结束标记: ${endMarker}`);
  return src.slice(a, b);
}

// ---------- 上下文 1: 真实 app.js 全量加载 ----------
// 早期按标记切片拼装的做法存在一个致命盲点：后加载的切片会再次定义同名函数，
// 于是先前加载的「旧副本」会把新实现静默覆盖，测试看起来在验证新代码、实际跑的是旧逻辑。
// 本用例因此直接在全量源码上求值，只补 DOM/事件桩，保证断言对象永远是文件里的那一份实现。
const ctx = {
  appState: {
    showChanlunDraw: false, chanlunLayers: {}, lineLayers: {}, topLineId: null, autoLinesCount: 0,
    chartPeriod: 'all', chartCustomZoomCount: 0, chartSubplot: 'vol', activeDetailStock: null,
    intradayChanlunCode: null, intradayChanlunPending: null, autoLinesBlockedReason: null, version: 'test'
  },
  console,
  window: {},
  navigator: { userAgent: 'node-vm' },
  location: { href: 'http://127.0.0.1:0/', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  setTimeout, clearTimeout, setInterval, clearInterval,
  Math, Number, Object, Array, JSON, Map, Set, Date, isNaN, isFinite, parseFloat, parseInt,
  String, Boolean, Error, Promise, RegExp, Symbol, encodeURIComponent, decodeURIComponent
};
// DOM 桩：任何 getElementById/querySelector 都返回一个记录型空元素，避免初始化阶段抛错
function stubEl() {
  return {
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    dataset: {}, children: [], value: '', textContent: '', innerHTML: '', hidden: false,
    appendChild() {}, removeChild() {}, remove() {}, setAttribute() {}, getAttribute: () => null,
    addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, insertAdjacentHTML() {}, focus() {}, click() {}, contains: () => false
  };
}
ctx.document = {
  getElementById: () => stubEl(),
  querySelector: () => stubEl(),
  querySelectorAll: () => [],
  createElement: () => stubEl(),
  addEventListener() {}, removeEventListener() {},
  documentElement: stubEl(), body: stubEl(), title: 'test'
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'web/app.js' });
// 初始化阶段注册的 DOMContentLoaded 回调不会在 vm 中触发，此处不执行任何 DOM 初始化逻辑。
// 渲染路径依赖的既有小工具：在真实页面中由 app.js 提供，此处按原实现注入
ctx.roundTo = (num, decimals = 2) => {
  const f = Math.pow(10, decimals);
  return Math.round((Number(num) + Number.EPSILON) * f) / f;
};

const M = { top: 20, right: 65, bottom: 25, left: 65 };
const W = 860;

// ================= REQ-022/023: 标准视窗 200 根 + 标准槽宽 + 右侧留白 =================
assert.equal(vm.runInContext('STANDARD_KLINE_VIEW_COUNT', ctx), 200, '标准视窗必须是 200 根');
assert.equal(vm.runInContext('MIN_KLINE_VIEW_COUNT', ctx), 5, '缩放下限必须是 5 根');

const full = ctx.klineSlotGeometry(W, M, 200);
assert.equal(Number(full.slot.toFixed(4)), Number((730 / 200).toFixed(4)), '标准槽宽必须等于内宽/200');
assert.equal(full.rightPadding, 0, '满 200 根时不得有留白');
assert.equal(full.partial, false, '满 200 根不应标记为留白态');

const partial = ctx.klineSlotGeometry(W, M, 30);
assert.equal(partial.slot, full.slot, '根数不足 200 根时槽宽必须与标准槽宽完全一致，不得拉伸');
assert.equal(partial.partial, true, '不足 200 根必须标记留白态');
// 30 根占据左侧约 30/200，右侧必须留白，且绝不铺满
assert(partial.rightPadding > 730 * 0.8, `右侧留白必须保留（实际 ${partial.rightPadding}）`);
assert.equal(Number((partial.rightPadding + 30 * partial.slot).toFixed(6)), 730, '留白 + 已用宽度必须严格等于内宽');
assert.equal(partial.xOf(0), M.left + partial.slot / 2, '第一根必须从绘图区左缘起排');
assert(partial.xOf(29) < M.left + 730 * 0.2, '30 根必须全部聚集在左侧，不得居中或铺满');

// 200 根时左右边界贴齐绘图区（无留白）
assert(full.xOf(0) - full.barW / 2 >= M.left - 1e-9, '满窗时第一根不得越出左边界');
assert(full.xOf(199) + full.barW / 2 <= M.left + 730 + 1e-9, '满窗时最后一根不得越出右边界');

// ================= REQ-025: 成交额取值优先级与兜底 =================
// vm 沙箱对象与宿主 realm 原型不同，统一逐字段断言
const realAmt = ctx.resolveKlineAmount({ amount_yi: 3.5, volume: 1000, open: 10, close: 10, high: 10, low: 10 });
assert.equal(realAmt.amountYi, 3.5, '真实成交额必须优先');
assert.equal(realAmt.derived, false, '真实成交额不得标记为估算');
// 2) 来源原始金额（元）折算
const rawAmt = ctx.resolveKlineAmount({ amount: 250000000, volume: 1 });
assert.equal(rawAmt.amountYi, 2.5, '原始 amount 必须按 /1e8 折算');
assert.equal(rawAmt.derived, false, '来源原始金额不得标记为估算');
// 3) 兜底：日均价 = (开+收+高+低)/4，成交量单位「手」→ 股
const est = ctx.resolveKlineAmount({ amount_yi: null, volume: 20000, open: 10, close: 12, high: 13, low: 9 });
assert.equal(est.derived, true, '缺失成交额时必须标记为估算口径');
assert.equal(Number(est.amountYi.toFixed(6)), Number(((11 * 20000 * 100) / 1e8).toFixed(6)), '兜底公式必须是均价×成交量/1e8');
// 分时优先取该分钟均价
const estTl = ctx.resolveKlineAmount({ amount_yi: null, volume: 1000, avg_price: 20, price: 10 });
assert.equal(Number(estTl.amountYi.toFixed(8)), Number(((20 * 1000 * 100) / 1e8).toFixed(8)), '分时兜底必须优先使用该分钟均价');
// 4) 连均价与成交量都缺失 → null 且给出原因（不得以 0 参与排序）
const none = ctx.resolveKlineAmount({ amount_yi: null, volume: null, open: 10, close: 10, high: 10, low: 10 });
assert.equal(none.amountYi, null, '无法兜底时必须返回 null，禁止以 0 填充');
assert.match(none.reason, /无法兜底推算/, '无法兜底必须给出明确原因');
assert.equal(ctx.resolveKlineAmount({ amount_yi: null, volume: 0, price: 10 }).amountYi, null, '成交量为 0 时不得产出 0 元成交额');

// ================= REQ-026: 交易面积 =================
// 构造：价格锚定在 10，第 2 根起 5 根，其中第 3 根交汇（剔除），成交额分别为 1/2/3/4/5 亿
const areaKlines = [
  { date: '2026-09-01', open: 8, close: 9, high: 9, low: 8, amount_yi: 100 },   // 交汇日之前，不参与统计
  { date: '2026-09-02', open: 10, close: 11, high: 12, low: 9, amount_yi: 1 },  // 首个交汇日 → 锚点，但本身被剔除
  { date: '2026-09-03', open: 13, close: 14, high: 15, low: 13, amount_yi: 2 }, // 未交汇 → 计入
  { date: '2026-09-04', open: 10, close: 11, high: 12, low: 9.5, amount_yi: 3 },// 交汇 → 剔除
  { date: '2026-09-05', open: 16, close: 17, high: 18, low: 16, amount_yi: 4 }, // 未交汇 → 计入
  { date: '2026-09-06', open: 20, close: 21, high: 22, low: 20, amount_yi: 5 }  // 未交汇 → 计入
];
assert.equal(ctx.findFirstCrossIndex(areaKlines, 10.5), 1, '首个交汇日必须锚定在第一次 low<=P<=high 的那天');
const area = ctx.computeTradeArea(areaKlines, 10.5, 1);
assert.equal(area.tradeAreaYi, 11, '交易面积必须 = 首个交汇日至今「未交汇」K线成交额之和（2+4+5）');
assert.equal(area.excludedDays, 2, '必须剔除该线自身交汇的交易日（9-02 与 9-04）');
assert.equal(area.countedDays, 3, '未交汇天数必须与参与求和的 K 线数一致');
assert.equal(area.incomplete, false, '覆盖完整时不得标记为不完整');
// 关键：首个交汇日之前的历史绝不参与（第 1 根 100 亿必须被排除）
assert(area.tradeAreaYi < 100, '首个交汇日之前的历史成交额绝不可计入');
// 缩放窗口无关性：同一锚点下，传入更小的窗口必须由调用方锚定，指标本身不得随窗口漂移
assert.equal(ctx.computeTradeArea(areaKlines, 10.5, ctx.findFirstCrossIndex(areaKlines, 10.5)).tradeAreaYi, 11,
  '同一锚点下重复计算必须稳定（缩放不影响该累计口径）');
// 覆盖不完整：区间内存在无法兜底的 K 线 → 显式标注而非静默出数
const incompleteArea = ctx.computeTradeArea([
  { open: 10, close: 10, high: 11, low: 10, amount_yi: 1 },
  { open: 20, close: 20, high: 21, low: 20, amount_yi: null, volume: null }
], 10.5);
assert.equal(incompleteArea.incomplete, true, '存在不可得成交额时必须标记覆盖不完整');
assert.match(incompleteArea.reason, /覆盖不完整|不完全/, '覆盖不完整必须给出原因说明');
// 从未交汇 → 无定义，显示「未交汇」而不是 0
const never = ctx.computeTradeArea([{ open: 50, close: 51, high: 52, low: 50, amount_yi: 9 }], 10);
assert.equal(never.tradeAreaYi, null, '未交汇不得以 0 冒充交易面积');
assert.equal(ctx.formatTradeArea(never), '交易面积: 未交汇', '未交汇必须显式显示「未交汇」');
assert.match(ctx.formatTradeArea(area), /交易面积: 11\.00亿 \(未交汇: 3天\)/, '交易面积文案必须含金额与未交汇天数');

// ================= REQ-025 解封：兜底后自动多阶线可以生成 =================
// 旧口径（amount_yi=null 一律拒绝）已被 REQ-025 修订：只要成交量与均价可得即应产出
const fallbackBars = [
  { date: '2026-09-01', open: 10, close: 10.5, high: 11, low: 9.5, volume: 10000, amount_yi: null },
  { date: '2026-09-02', open: 10.5, close: 11, high: 11.5, low: 10, volume: 12000, amount_yi: null },
  { date: '2026-09-03', open: 11, close: 10.5, high: 11.6, low: 10.2, volume: 9000, amount_yi: null }
].map(ctx.withResolvedAmount);
assert(fallbackBars.every(b => b.amount_derived === true && b.amount_yi > 0), '兜底后每根都必须带有估算标记与正成交额');
assert(ctx.calculateAutoSupportResistanceLevels(fallbackBars, 11, 1).length > 0, '兜底口径下自动多阶线必须能够生成');
// 估算标记的「粘性」：withResolvedAmount 补齐后 amount_yi 已是具体数值，
// 覆盖判定必须仍能识别其来源为估算，否则副图/指数图的估算标注会静默消失。
const enrichedBars = fallbackBars.map(ctx.withResolvedAmount);
const enrichedFlags = ctx.amountCoverageFlags(enrichedBars);
assert.equal(enrichedFlags.derived, enrichedBars.length, '已补齐的估算样本必须仍被判定为估算口径（标记不得因补齐而丢失）');
assert.equal(enrichedFlags.anyDerived, true, 'anyDerived 必须在补齐后仍为真');
assert.equal(ctx.amountCoverageFlags(fallbackBars).derived, fallbackBars.length, '未补齐的原始样本同样必须被判定为估算');
const realBars = [{ amount_yi: 3.2, volume: 10000, open: 10, close: 10, high: 10, low: 10 }];
assert.equal(ctx.amountCoverageFlags(realBars).anyDerived, false, '真实成交额不得被误判为估算口径');

// 连成交量都缺失 → 仍然严格拒绝
const blockedBars = [{ date: '2026-09-01', open: 10, close: 10.5, high: 11, low: 9.5, amount_yi: null, volume: null }];
assert.equal(ctx.calculateAutoSupportResistanceLevels(blockedBars, 10.5, 1).length, 0, '无成交额且无法兜底时仍必须拒绝生成');

// ================= REQ-035: 个股面板口径「视窗 N 根 ∈ [30, 全部]」=================
// 需求REQ-035 取代 REQ-029 的「标准 200 根铺满」口径：指数字段仍走 200 根基准（上方断言保持不变），
// 个股图表改为「槽宽 ＝ 绘图区内宽 / 本面板视窗根数 N」，N 下限 30、上限为该颗粒度全部可用根数。
function mkBars(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const base = 10 + i * 0.1;
    out.push({ date: `2026-0${(i % 9) + 1}-${String((i % 27) + 1).padStart(2, '0')}`, open: base, close: base + 0.2, high: base + 0.5, low: base - 0.3, volume: 1000 + i, amount_yi: 1 + i * 0.01 });
  }
  return out;
}
function candleRects(svg) {
  return Array.from(svg.matchAll(/<rect x="([\d.eE+-]+)" y="[-\d.eE+]+" width="([\d.eE+-]+)" height="[-\d.eE+]+" fill="#(?:ef4444|10b981)"\/>/g))
    .map(m => ({ x: Number(m[1]), w: Number(m[2]) }));
}
// 图上的留白说明文案（避免与源代码注释「右侧留白区段」混淆）
const PANEL_PAD_NOTE = /视窗 \d+ 根 · 实绘 \d+ 根（不足，右侧留白）/;
// appState / chartPanels 均以 const 声明在 vm 全局词法作用域中（非 context 属性），
// 因此必须在该作用域内赋值，宿主侧的 ctx.appState 写入不会影响 vm 内的实现
function setPanelViewport(count, available) {
  vm.runInContext(`appState.chartPanelSlot = 'right';
    chartPanels.right.st.klineCount = ${count}; chartPanels.right.st.availableCount = ${available};`, ctx);
}
const renderStock = (bars, subplot = 'vol') =>
  ctx.generateDailyKlineSVG(bars, subplot, W, 440, 270, 110, M, null, 'right', null, 'klinedaily');

// 视窗 30 根 + 真实 30 根 → 铺满绘图区
setPanelViewport(30, 30);
const svg30 = renderStock(mkBars(30));
const rects30 = candleRects(svg30);
const geoPanel30 = ctx.klineSlotGeometry(W, M, 30, 30);
assert.equal(rects30.length, 30, `30 根 K 线必须渲染 30 根蜡烛（实际 ${rects30.length}）`);
assert(/视窗 30 根 · 实绘 30 根/.test(svg30), '面板必须显式标注视窗根数与实绘根数');
assert(!PANEL_PAD_NOTE.test(svg30), '视窗 30 根且真实 30 根时不得出现留白说明');
assert(Math.abs(rects30[0].w - geoPanel30.candleW) < 1e-6, '槽宽基准必须＝绘图区内宽 / 视窗根数(30)');
assert(Math.abs(geoPanel30.slot - 730 / 30) < 1e-6, '视窗 30 根时槽宽必须＝内宽/30');
assert(rects30[29].x + rects30[29].w > M.left + 730 * 0.95, '视窗 30 根且真实 30 根必须铺满绘图区');

// 真实根数不足视窗 → 右侧留白（不拉伸、不补足）
setPanelViewport(30, 10);
const svg10 = renderStock(mkBars(10));
const rects10 = candleRects(svg10);
assert.equal(rects10.length, 10, '实绘根数必须严格等于真实可用根数，禁止补足');
assert(PANEL_PAD_NOTE.test(svg10), '真实根数不足视窗时必须显式说明「不足，右侧留白」');
assert(rects10[9].x + rects10[9].w < M.left + 730 * 0.5, '10 根只应占据绘图区左侧约 1/3，右侧留白');
assert(Math.abs(rects10[0].w - geoPanel30.candleW) < 1e-6, '留白态槽宽必须与满窗槽宽一致，不得因根数不足而拉伸');

// 缩放下限 30 根 / 上限＝全部可用根数
setPanelViewport(5, 30);
assert.equal(ctx.currentKlineSlotBasis(), 30, '缩放下限必须是 30 根（请求 5 根也必须按 30 根视窗绘制）');
setPanelViewport(9999, 200);
assert.equal(ctx.currentKlineSlotBasis(), 200, '缩放上限必须＝该颗粒度全部可用根数，而非固定 200 根');
const svg200 = renderStock(mkBars(200));
const rects200 = candleRects(svg200);
const geoPanel200 = ctx.klineSlotGeometry(W, M, 200, 200);
assert.equal(rects200.length, 200, '200 根必须渲染 200 根蜡烛');
assert(!PANEL_PAD_NOTE.test(svg200), '视窗与真实根数一致时不得出现留白说明');
assert(rects200[199].x + rects200[199].w > M.left + 730 * 0.95, '全部根数必须铺满绘图区');
// 主图蜡烛与副图柱必须共用同一槽位与宽度基准：逐根比较矩形左缘（同一 x）
const subBarRects = Array.from(svg200.matchAll(/<rect x="([\d.eE+-]+)" y="[-\d.eE+]+" width="([\d.eE+-]+)" height="[-\d.eE+]+" fill="#(?:ef4444|10b981)" opacity="0\.85"\/>/g))
  .map(m => ({ x: Number(m[1]), w: Number(m[2]) }));
assert.equal(subBarRects.length, rects200.length, '副图柱数量必须与蜡烛一致');
const misaligned = subBarRects.filter((r, i) => Math.abs(r.x - rects200[i].x) > 1e-6 || Math.abs(r.w - rects200[i].w) > 1e-6);
assert.equal(misaligned.length, 0, `副图柱必须与蜡烛逐根严格对齐且同宽（发现 ${misaligned.length} 根错位）`);
// 蜡烛必须以其槽位中心定位：中心 = 槽中心
assert(Math.abs((rects200[0].x + rects200[0].w / 2) - geoPanel200.xOf(0)) < 1e-6, '蜡烛必须以槽位中心定位');
assert(Math.abs((rects200[199].x + rects200[199].w / 2) - geoPanel200.xOf(199)) < 1e-6, '末根蜡烛同样必须以槽位中心定位');

// 估算口径必须可辨识：副图标题必须带「含估算」且给出计数提示
setPanelViewport(30, 30);
const derivedSvg = renderStock(mkBars(30).map(b => Object.assign({}, b, { amount_yi: null, volume: 1000 })), 'amt');
assert(/含估算：均价×成交量/.test(derivedSvg), '估算口径必须在副图标题上显式标注');
assert(/其中 30 根成交额为估算/.test(derivedSvg), '估算根数必须在图上提示');
vm.runInContext("appState.chartPanelSlot = null;", ctx);

// ================= REQ-024: 分时级别缠论叠加必须使用 time 基准 =================
const tlKlines = [];
for (let i = 0; i < 60; i++) {
  const hh = i < 30 ? '09' : '13';
  const mm = String(i % 30).padStart(2, '0');
  const price = 10 + Math.sin(i / 5) * 0.6;
  tlKlines.push({ time: `${hh}:${mm}`, date: `${hh}:${mm}`, open: price, close: price, high: price, low: price, price: price });
}
const tlAnalysis = {
  dates: tlKlines.map(k => k.date),
  pens: [{ start_time: '09:00', end_time: '09:20', start_price: 10, end_price: 10.5, status: 'confirmed' }],
  segments: [], pivots: [], divergences: [], ma_entanglements: []
};
// 需求REQ-040: 结构层由「缠论画线」总开关控制，分时图同样如此（买卖点可独立于该开关显示）。
// 注意：appState 在 vm 内是词法声明，必须用 runInContext 赋值，直接改 ctx.appState 不生效。
vm.runInContext("appState.chanlunLayers = {}; appState.showChanlunDraw = true;", ctx);
const tlSvg = ctx.generateChanlunOverlaySVG(tlKlines, i => 65 + i * 3, p => 200 - p * 5, tlAnalysis);
assert(/chanlun-pens/.test(tlSvg), '分时级别必须能渲染缠论笔图层');
assert(!/NaN|undefined/.test(tlSvg), '分时缠论叠加不得出现 NaN/undefined 坐标');
assert(/x1="65"/.test(tlSvg), '分时笔起点必须映射到分时 K 线自身的 x 槽位');

console.log('PASS: R04 指数视窗(200根/槽宽) + REQ-035 个股面板视窗(N∈[30,全部]/不足右侧留白) + 成交额兜底 + 交易面积剔除口径 + 分时缠论 time 基准 (REQ-022/023/024/025/026/035)');
