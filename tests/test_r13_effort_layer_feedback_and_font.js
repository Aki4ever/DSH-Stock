/**
 * tests/test_r13_effort_layer_feedback_and_font.js
 * R13 前端静态回归（REQ-097「努力与结果」图层零反馈修复 / REQ-098 副图信息条字号放大一倍）
 *
 * 模型与 test_r09_subplot_header.js 完全一致：按页面顺序装载 util.js + app.js 到 vm 沙箱，只补 DOM 桩，
 * 断言对象永远是 web/ 下的真实实现；全部为构造数据，不触网、不碰产品库。
 *
 * 口径要点（需求方原话：「点击/关闭按钮在K线图上没有显示任何反馈」「红框内文字加大一倍」）：
 *   1. 图层开关必须产生图上可见的 DOM 差异（状态徽标 effort-layer-badge 的 data-state 翻转）；
 *   2. 零命中时必须显式说明零命中，且阈值文案与算法常量同源（禁止手写复述阈值）；
 *   3. 副图表头字号必须是 20（原 10 的两倍），且放大后表头不得压住副图柱、刻度标签不得越出画布左缘。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { loadWebSource } = require('./load_web_sources');

const src = loadWebSource();

// ---------- DOM 桩（按 id 缓存；toast 宿主单独捕获文本） ----------
const elements = new Map();
function stubEl(id) {
  return {
    id: id || null,
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    dataset: {}, children: [], value: '', textContent: '', innerHTML: '', hidden: false,
    title: '', className: '', disabled: false,
    appendChild() {}, removeChild() {}, remove() {}, setAttribute() {}, getAttribute: () => null,
    addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, insertAdjacentHTML() {}, focus() {}, click() {}, contains: () => false
  };
}
const toastHosts = [{ textContent: '', classList: { add() {}, remove() {} } }];
const ctx = {
  console,
  window: { addEventListener() {}, removeEventListener() {}, innerWidth: 1440, innerHeight: 900 },
  location: { href: 'http://127.0.0.1:0/', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  setTimeout, clearTimeout, setInterval, clearInterval,
  Math, Number, Object, Array, JSON, Map, Set, Date, isNaN, isFinite, parseFloat, parseInt,
  String, Boolean, Error, Promise, RegExp, Symbol, encodeURIComponent, decodeURIComponent
};
ctx.document = {
  getElementById: (id) => { if (!elements.has(id)) elements.set(id, stubEl(id)); return elements.get(id); },
  querySelector: () => stubEl(),
  querySelectorAll: (sel) => (sel === '.chart-toast-host' ? toastHosts : []),
  createElement: () => stubEl(), addEventListener() {}, removeEventListener() {},
  documentElement: stubEl(), body: stubEl(), title: 'test'
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'web/app.js' });
const run = (expr) => vm.runInContext(expr, ctx);

// ---------- 构造数据 ----------
/** 构造 n 根平稳K线（量能与实体都很规矩 → 不触发努力与结果悖论） */
function quietBars(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const base = 10 + i * 0.02;
    out.push({
      date: `2026-08-${String((i % 27) + 1).padStart(2, '0')}`,
      open: base, close: base + 0.06, high: base + 0.18, low: base - 0.12,
      volume: 100000 + (i % 5) * 1200, amount_yi: 2 + i * 0.01, price: base + 0.06
    });
  }
  return out;
}
/** 在末 30 根视窗内注入一根「天量窄实体」异动柱（与真实算法口径一致） */
function barsWithEffortAnomaly() {
  const bars = quietBars(40);
  const avgVol = bars.slice(20, 38).reduce((a, b) => a + b.volume, 0) / 18;
  bars[38] = {
    date: '2026-09-18', open: 11.20, close: 11.22, high: 11.30, low: 11.10,
    volume: avgVol * 3.2, amount_yi: 8.8, price: 11.22
  };
  return bars;
}
/** 只出异动柱、不升级为买卖点：上行趋势 + 长下影（下影/上影条件不满足），用于验证提示与徽标不自相矛盾 */
function barsWithAnomalyButNoSignal() {
  const bars = quietBars(40);
  const avgVol = bars.slice(20, 38).reduce((a, b) => a + b.volume, 0) / 18;
  bars[38] = {
    date: '2026-09-18', open: 11.20, close: 11.21, high: 11.25, low: 11.00,
    volume: avgVol * 3.2, amount_yi: 8.8, price: 11.21
  };
  return bars;
}

const M13 = { top: 20, right: 65, bottom: 25, left: 112 };   // REQ-098: 左边距 65→112（容纳 20px 刻度标签）
const W = 920, H = 656, MH = 350, SH = 190;                  // REQ-098: 540→620；REQ-101: 620→656（底部信息条放大后需 36px 余量）
const appSrc = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');

// ================= REQ-097-①②：阈值口径单一事实来源 =================
console.log('--- [REQ-097] 阈值口径必须由算法自身输出，供图上文案复用 ---');
const anomalyBars = barsWithEffortAnomaly();
const res = run('calculateWyckoffEffortResult')(anomalyBars);
assert(res && res.threshold, '算法必须返回 threshold（图上空状态/徽标文案的唯一来源）');
assert.deepEqual(
  JSON.parse(JSON.stringify(res.threshold)),
  { avgBars: 20, volRatioMin: 1.65, resultRatioMax: 0.65, bodyRangeMax: 0.35 },
  '阈值常量必须显式可见（20 根均量基准 / 1.65 倍量 / 0.65 倍实体 / 35% 实体占比）'
);
assert(res.signals.length >= 1, '构造的天量窄实体柱必须被识别为努力与结果悖论');

const thresholdText = run('effortThresholdText')(res.threshold);
assert.match(thresholdText, /1\.65×20日均量/, '阈值文案必须由 threshold 生成（量口径）');
assert.match(thresholdText, /0\.65×均实体/, '阈值文案必须由 threshold 生成（实体口径）');
assert.match(thresholdText, /35%/, '阈值文案必须由 threshold 生成（实体/振幅口径）');
// 单一事实来源反证：把常量改成别的值，文案必须跟着变（说明不是手写复刻）
assert.match(run('effortThresholdText')({ avgBars: 33, volRatioMin: 2.5, resultRatioMax: 0.4, bodyRangeMax: 0.2 }), /2\.5×33日均量/,
  '文案必须直接读常量：换一组常量后文案必须随之变化');
// 算法自身 reason 文案的「N日均量」必须与 threshold.avgBars 同源
res.signals.forEach(s => {
  assert.match(s.reason, new RegExp(`${res.threshold.avgBars}日均量`), `买卖点 reason 的均量口径必须与 threshold 一致：${s.reason}`);
});

// ================= REQ-097-③：开关必有图上可见反馈 =================
console.log('--- [REQ-097] 图层状态徽标：开/关必须在图上产生 DOM 差异 ---');
const renderOverlay = run('generateFirstPrinciplesOverlaySVG');
const getX = (i) => 112 + i * 10;
const getY = (p) => 100 + (12 - p) * 20;

run('appState.showEffortDraw = true; appState.showAmtDraw = false;');
const onSvg = renderOverlay(quietBars(30), getX, getY, 743, MH, M13, 'right');
const onBars = barsWithEffortAnomaly().slice(-30);
const onHitSvg = renderOverlay(onBars, getX, getY, 743, MH, M13, 'right');
run('appState.showEffortDraw = false; appState.showAmtDraw = true;');
const offSvg = renderOverlay(quietBars(30), getX, getY, 743, MH, M13, 'right');

assert.match(onSvg, /class="effort-layer-badge"[^>]*data-state="on"/, '图层开启时主图必须输出状态徽标 data-state="on"');
assert.match(offSvg, /class="effort-layer-badge"[^>]*data-state="off"/, '图层关闭时主图必须输出状态徽标 data-state="off"');
assert.notEqual(onSvg, offSvg, '开→关（AMT 保持开启）时叠加层 DOM 必须不同 —— 这是「点了有反馈」的硬判据');

// 零命中：必须显式说明零命中，且带上与算法同源的阈值口径
assert.match(onSvg, /class="effort-empty-note"/, '零命中时必须输出空状态文案（不得静默无反应）');
assert.ok(onSvg.includes(thresholdText), '空状态文案必须原样带出 threshold 生成的阈值口径');
// 有命中：不得再显示空状态，徽标必须报出真实命中数
assert.doesNotMatch(onHitSvg, /class="effort-empty-note"/, '有命中时不得再输出「零命中」空状态');
assert.match(onHitSvg, /data-signals="[1-9]\d*"/, '徽标必须报出本视窗真实命中数');
assert.match(onHitSvg, /class="effort-bs-marker"/, '有买卖点时必须真的把 ⚡ 标记画到图上（不得只计数不绘制）');
assert.match(onHitSvg, /data-anomalies="[1-9]\d*"/, '徽标必须报出本视窗异动柱根数');

// 边界口径（真机验证暴露的矛盾）：有异动柱但未升级为买卖点时，提示必须与徽标一致，不得说「未识别到异动」
run('appState.showEffortDraw = true; appState.showAmtDraw = false;');   // 复核前必须把图层切回开启态
const onlyAnomalySvg = renderOverlay(barsWithAnomalyButNoSignal().slice(-30), getX, getY, 743, MH, M13, 'right');
assert.match(onlyAnomalySvg, /data-anomalies="[1-9]\d*"/, '该构造必须真有异动柱');
assert.match(onlyAnomalySvg, /data-signals="0"/, '该构造不得有买卖点');
assert.match(onlyAnomalySvg, /class="effort-empty-note"/, '有异动柱但无买卖点时仍须给出说明（不得静默）');
assert.doesNotMatch(onlyAnomalySvg, /未识别到「天量窄实体」异动/, '已有异动柱时不得再说「未识别到异动」（会与徽标「异动 N 根」自相矛盾）');
assert.match(onlyAnomalySvg, /检出 1 根天量窄实体异动柱/, '必须如实说明「检出异动柱但未构成买卖点」');

// ================= REQ-097-④：toast 与图上同源同数 =================
console.log('--- [REQ-097] toast 必须报出本视窗命中数（与徽标同源同窗口） ---');
run(`appState.activeDetailStock = { code: 'sh601939', daily_bars: ${JSON.stringify(anomalyBars)} };
     chartPanels.right.st.dimension = 'kline'; chartPanels.right.st.klineGroup = 'daily';
     chartPanels.right.st.klineCount = 30; chartPanels.right.st.availableCount = ${anomalyBars.length};
     appState.showEffortDraw = false;`);
ctx.toggleEffortDraw('right');
assert.match(toastHosts[0].textContent, /本视窗命中 1 个/, `toast 必须报出本视窗命中数，实际：${toastHosts[0].textContent}`);
assert.match(toastHosts[0].textContent, /已开启/, 'toast 必须说明图层已开启');
toastHosts[0].textContent = '';
ctx.toggleEffortDraw('right');
assert.match(toastHosts[0].textContent, /已隐藏/, '再次点击必须说明图层已隐藏');
assert.doesNotMatch(toastHosts[0].textContent, /本视窗命中/, '隐藏图层时不得再报命中数（避免误导）');

// ================= REQ-098：字号放大一倍且不压柱/不裁切 =================
console.log('--- [REQ-098] 副图信息条字号 = 2 倍（10→20），且不压柱、不越界 ---');
run(`appState.showEffortDraw = false; appState.showAmtDraw = true;
     appState.chartPanelSlot = 'right'; chartPanels.right.st.klineCount = 30; chartPanels.right.st.availableCount = 30;`);
const bars30 = quietBars(30);
const svg = run('generateDailyKlineSVG')(bars30, 'amt', W, H, MH, SH, M13, null, 'right', null, 'klinedaily');

// 1) 表头（标题 + 5 个统计项）与副图刻度标签的字号都必须翻倍
const headerGroup = svg.match(/<g class="sub-summary-group">[\s\S]*?<\/g>/g) || [];
assert(headerGroup.length >= 1, '副图统计行必须输出');
const headerFontSizes = [...headerGroup.join('').matchAll(/font-size="([\d.]+)"/g)].map(m => Number(m[1]));
assert(headerFontSizes.length >= 5, '统计行必须逐项输出（标题 + 5 项）');
headerFontSizes.forEach(s => assert.equal(s, 20, `副图统计项字号必须为 20（原 10 的两倍），实际 ${s}`));
const subTitleTag = svg.match(/<text x="120(?:\.\d+)?" y="[^"]+" fill="#94a3b8" font-size="(\d+)" font-weight="600">副图：成交额<\/text>/);
assert(subTitleTag, '副图标题必须原样输出（含 REQ-025 口径后缀时同源）');
assert.equal(Number(subTitleTag[1]), 20, '副图标题字号必须为 20');
const scaleTag = svg.match(/<text x="104" y="[^"]+" fill="#64748b" font-size="(\d+)" text-anchor="end" font-family="monospace">([^<]+)<\/text>/);
assert(scaleTag, '副图 Y 轴刻度标签必须输出（红框内同行的量纲标签）');
assert.equal(Number(scaleTag[1]), 20, '副图刻度标签字号必须与表头同为 20（红框内文字整体放大一倍）');
// 2) 刻度标签必须放得下：20px 下的估算宽度不得越过画布左缘
const scaleWidth = run('estimateSvgTextWidth')(scaleTag[2], 20);
assert(scaleWidth <= M13.left - 8 + 0.01, `刻度标签在 20px 下宽 ${scaleWidth.toFixed(1)} 超出左边距 ${M13.left - 8}（会被画布左缘裁掉）`);

// 3) 表头不得压住副图柱：所有副图柱顶 y 必须晚于最后一行表头的基线
const subTopY = M13.top + MH + 25;
const headerYs = [...headerGroup.join('').matchAll(/<text x="[\d.]+" y="([\d.]+)"/g)].map(m => Number(m[1]))
  .concat([Number(svg.match(/<text x="120(?:\.\d+)?" y="([\d.]+)" fill="#94a3b8" font-size="20"/)[1])]);
const lastHeaderY = Math.max(...headerYs);
const barTops = [...svg.matchAll(/<rect x="[\d.-]+" y="([\d.]+)" width="[\d.]+" height="[\d.]+" fill="#(?:ef4444|10b981)" opacity="0\.(?:85|95)"/g)]
  .map(m => Number(m[1]))
  .filter(y => y >= subTopY - 1);
assert(barTops.length >= 5, `必须能在副图区间内解析到柱子（实际 ${barTops.length} 根）`);
assert(Math.min(...barTops) >= lastHeaderY + 4,
  `副图柱顶 ${Math.min(...barTops).toFixed(1)} 不得压住最后一行表头基线 ${lastHeaderY.toFixed(1)}`);

// 4) 画布必须留得下放大后的副图（表头 + 柱子 + 底部注释）
assert(H >= subTopY + SH + 20, `画布高 ${H} 必须容纳副图底部的「总成交额 / 含估算」注释（需 ≥ ${subTopY + SH + 20}）`);

// 4b) 需求REQ-101: 底部信息条（总成交额 / 含估算提示）必须与表头同为 20px，且文字下缘不得越出 viewBox 被裁切。
//     判据用「真实渲染出的 y + 字号下伸部 ≤ 画布高」，而不是靠人工目测 —— 画布高取源码里的生产值。
const prodHeight = Number((appSrc.match(/const height = (\d+);/) || [])[1] || 0);
assert(prodHeight > 0, '必须能从源码读出生产画布高 const height');
const bottomTexts = [...svg.matchAll(/<text x="[\d.]+" y="([\d.]+)" fill="#(?:f59e0b|c084fc|fbbf24)" font-size="([\d.]+)"[^>]*class="(?:sub-total-amount|sub-total-amount-note)"[^>]*>/g)];
assert(bottomTexts.length >= 1, '副图底部「总成交额 / 累计换手率」必须输出为独立 text（本轮放大的对象）');
bottomTexts.forEach(m => {
  const y = Number(m[1]), fs = Number(m[2]);
  assert.equal(fs, 20, `底部信息条字号必须为 20（原 10 的两倍），实际 ${fs}`);
  assert(y + fs * 1.25 <= prodHeight + 0.01,
    `底部信息条基线 ${y} + 下伸部 ${(fs * 1.25).toFixed(1)} 超出画布高 ${prodHeight}（会被 viewBox 下缘裁掉）`);
});
// 生产「含估算」提示（右对齐那条）同样必须 20px 且不越界 —— 用带兜底日线的构造逼出该分支
const derivedSvg = run('generateDailyKlineSVG')(
  bars30.map(b => Object.assign({}, b, { amount_yi: null, amount: null })), 'amt', W, H, MH, SH, M13, null, 'right', null, 'klinedaily');
const derivedNote = derivedSvg.match(/<text x="[\d.]+" y="([\d.]+)" fill="#fbbf24" font-size="([\d.]+)" text-anchor="end">\s*⚠️ 其中/);
assert(derivedNote, '存在兜底估算日线时必须输出「⚠️ 其中 N 根成交额为估算」提示');
assert.equal(Number(derivedNote[2]), 20, '「含估算」提示字号必须同为 20');
assert(Number(derivedNote[1]) + 20 * 1.25 <= prodHeight + 0.01,
  `「含估算」提示基线 ${derivedNote[1]} 超出画布高 ${prodHeight}`);

// 5) 分时图副图表头同样必须是 20（两图同源）
const tlItems = quietBars(60).map((b, i) => Object.assign({}, b, { time: `09:${String(i % 60).padStart(2, '0')}` }));
const tlSvg = run('generateTimelineSVG')(tlItems, tlItems[0].price, 'vol', W, H, MH, SH, M13, null, 'left');
const tlFonts = [...(tlSvg.match(/<g class="sub-summary-group">[\s\S]*?<\/g>/g) || []).join('').matchAll(/font-size="([\d.]+)"/g)].map(m => Number(m[1]));
assert(tlFonts.length >= 5 && tlFonts.every(s => s === 20), `分时副图表头字号必须同为 20，实际 ${JSON.stringify(tlFonts)}`);

// ================= 源码级防回退：常量必须是唯一入口 =================
console.log('--- [R13] 源码级防回退 ---');
assert.match(appSrc, /const SUBPLOT_HEADER_FONT_SIZE = 20;/, '副图表头字号必须收敛到常量 SUBPLOT_HEADER_FONT_SIZE=20');
const headerConstCalls = (appSrc.match(/fontSize: SUBPLOT_HEADER_FONT_SIZE/g) || []).length;
assert.equal(headerConstCalls, 4, `个股 4 处副图表头调用（分时×2 + K线×2）必须全部走常量，实际 ${headerConstCalls}`);
// 需求REQ-101: 底部信息条也走同一常量 —— 个股 4 处底部信息条 + 副图 Y 轴刻度 2 处 + 指数页底部信息条 2 处，共 8 处
const bottomFontConst = (appSrc.match(/font-size="\$\{SUBPLOT_HEADER_FONT_SIZE\}"/g) || []).length;
assert.equal(bottomFontConst, 8, `副图底部信息条（个股 6 处 + 指数 2 处）必须同为 SUBPLOT_HEADER_FONT_SIZE，实际 ${bottomFontConst}`);
assert.match(appSrc, /const SUBPLOT_BOTTOM_TEXT_BASELINE_OFFSET = 20;/, '底部信息条基线偏移必须收敛到常量（放大后不许再留 11）');
assert.doesNotMatch(appSrc, /subTopY \+ sh \+ 11\}/, '副图底部不得残留只适配 10px 的 +11 基线');
const literalTenCalls = (appSrc.match(/fontSize: 10\b/g) || []).length;
assert.equal(literalTenCalls, 1, `个股图表不得再残留 fontSize: 10；仅指数页（本轮范围外）保留 1 处，实际 ${literalTenCalls}`);
assert.match(appSrc, /effortThresholdText\(/, '阈值文案必须走 effortThresholdText（禁止手写复述）');
assert.match(appSrc, /const height = 656;/, '画布高必须为 656（REQ-098 的 620 + REQ-101 底部信息条预留 36）');
assert.match(appSrc, /const subHeight = 190;/, '副图高必须为 190（REQ-098 同步放大）');

// 需求REQ-101: 指数详情页同源文案（全域同权）—— 该页K线分支画布高 480→500，
//   底部信息条两处 font-size 必须同为 20；因指数页在 headless 下切颗粒度会卡住主线程（既有缺陷，
//   见需求台账），本项以源码级断言兜底真机读数。
assert.match(appSrc, /const height = 500;/, '指数K线画布高必须为 500（REQ-101 为第二条底部信息条留出 48px 行距）');
// 指数页K线分支的定位锚：`indexWindowAmount.note` 只在该分支出现（唯一）
const indexBranchAt = appSrc.indexOf('indexWindowAmount.note');
assert(indexBranchAt > 0, '必须能定位指数页K线分支（indexWindowAmount.note）');
const indexFontNear = appSrc.slice(Math.max(0, indexBranchAt - 900), indexBranchAt + 900);
const indexBottomFonts = (indexFontNear.match(/class="sub-total-amount(?:-note)?"/g) || []).length;
assert.equal(indexBottomFonts, 2, `指数页底部信息条必须 2 处（总成交额 + 含估算说明），实际 ${indexBottomFonts}`);
assert.equal((indexFontNear.match(/font-size="\$\{SUBPLOT_HEADER_FONT_SIZE\}"/g) || []).length, 2,
  '指数页底部信息条 2 处字号必须同为 SUBPLOT_HEADER_FONT_SIZE（20）');
assert.doesNotMatch(indexFontNear, /class="sub-total-amount(?:-note)?"[\s\S]{0,90}font-size="10"/,
  '指数页底部信息条不得残留 10px（放大一倍口径与个股同源）');

console.log('PASS: REQ-097 阈值同源 + 开关必有图上反馈（徽标/空状态/toast 命中数）；REQ-098 副图表头与刻度标签字号 2 倍（20px）且不压柱、不越界、画布同步放大');
