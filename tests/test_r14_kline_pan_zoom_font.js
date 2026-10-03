/**
 * tests/test_r14_kline_pan_zoom_font.js
 * R14 前端静态回归（REQ-099 K线左右滑动平移 / REQ-100 ± 按钮同源可逆 / REQ-101 副图底部信息条放大）
 *
 * 模型与 test_r13_effort_layer_feedback_and_font.js 完全一致：按页面顺序装载 util.js + app.js 到 vm 沙箱，
 * 只补 DOM 桩，断言对象永远是 web/ 下的真实实现；全部为构造数据，不触网、不碰产品库。
 *
 * 口径要点（需求方原话）：
 *   ① 「日线图、周线图、季线图可以对k线图进行左滑和右滑手势」；
 *   ② 「+ - 按钮每次都应该是同样水平的操作，例如 + 之前是 47 列、+ 之后是 40 列，那么再 - 也应该是 47 列；+ - 应该同源以及同数量级」；
 *   ③ 「红框内的文字也应该放大一倍」。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { loadWebSource } = require('./load_web_sources');

const src = loadWebSource();
const appSrc = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');

// ---------- DOM 桩（按 id 缓存；同时记录 addEventListener 次数，用于断言监听器不累积） ----------
const elements = new Map();
const listenerLog = [];   // { target: 'element'|'window', id, type, fn }
const svgNodes = new Map(); // 每个 slot 固定复用同一个 SVG 桩对象，模拟「同一面板同一图元」
const winListeners = [];

function stubEl(id) {
  return {
    id: id || null,
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    dataset: {}, children: [], value: '', textContent: '', innerHTML: '', hidden: false,
    title: '', className: '', disabled: false,
    _listeners: [],
    appendChild() {}, removeChild() {}, remove() {}, setAttribute() {}, getAttribute: () => null,
    addEventListener(type, fn) { this._listeners.push({ type, fn }); listenerLog.push({ target: 'element', id: this.id, type, fn }); },
    removeEventListener(type, fn) {
      const i = this._listeners.findIndex(l => l.type === type && l.fn === fn);
      if (i >= 0) this._listeners.splice(i, 1);
      else if (fn) throw new Error(`removeEventListener 摘除了一个从未 add 的监听器：${this.id}/${type}`);
    },
    listenersOf(type) { return this._listeners.filter(l => l.type === type); },
    querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, insertAdjacentHTML() {}, focus() {}, click() {}, contains: () => false
  };
}

const ctx = {
  console,
  window: {
    innerWidth: 1440, innerHeight: 900,
    addEventListener(type, fn) { winListeners.push({ type, fn }); listenerLog.push({ target: 'window', id: 'window', type, fn }); },
    removeEventListener(type, fn) {
      const i = winListeners.findIndex(l => l.type === type && l.fn === fn);
      if (i >= 0) winListeners.splice(i, 1);
      else if (fn) throw new Error(`window 摘除了一个从未 add 的监听器：${type}`);
    }
  },
  location: { href: 'http://127.0.0.1:0/', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  setTimeout, clearTimeout, setInterval, clearInterval,
  Math, Number, Object, Array, JSON, Map, Set, Date, isNaN, isFinite, parseFloat, parseInt,
  String, Boolean, Error, Promise, RegExp, Symbol, encodeURIComponent, decodeURIComponent
};
ctx.document = {
  getElementById: (id) => {
    if (!elements.has(id)) {
      if (/^stockInteractiveSvg_/.test(id)) {
        if (!svgNodes.has(id)) svgNodes.set(id, stubEl(id));
        return svgNodes.get(id);
      }
      elements.set(id, stubEl(id));
    }
    return elements.get(id);
  },
  querySelector: () => stubEl(),
  querySelectorAll: () => [],
  createElement: () => stubEl(), addEventListener() {}, removeEventListener() {},
  documentElement: stubEl(), body: stubEl(), title: 'test'
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'web/app.js' });
const run = (expr) => vm.runInContext(expr, ctx);
const get = (name) => run(name);

// ---------- 构造数据 ----------
/** 构造 n 根平稳日K（成交量/成交额都给真值，避免触发兜底估算分支） */
function dailyBars(n) {
  const out = [];
  const base = new Date('2024-01-02T00:00:00Z');
  for (let i = 0; i < n; i++) {
    const d = new Date(base.getTime() + i * 86400000);
    const close = 10 + Math.sin(i / 7) * 1.2;
    out.push({
      date: d.toISOString().slice(0, 10),
      open: Number((close - 0.05).toFixed(2)),
      close: Number(close.toFixed(2)),
      high: Number((close + 0.18).toFixed(2)),
      low: Number((close - 0.2).toFixed(2)),
      volume: 100000 + i * 1000,
      amount_yi: Number((1 + (i % 13) * 0.3).toFixed(2)),
      turnover_rate: Number((0.5 + (i % 7) * 0.1).toFixed(2))
    });
  }
  return out;
}

const AVAILABLE = 300;
const BARS = dailyBars(AVAILABLE);
run(`appState.activeDetailStock = { code: 'sh601939', daily_bars: ${JSON.stringify(BARS)} };
     chartPanels.right.st.availableCount = ${AVAILABLE};
     chartPanels.right.availableCount = ${AVAILABLE};`);

// ==================================================================
// REQ-100：± 按钮 同源 + 同数量级 + 严格可逆
// ==================================================================
console.log('--- [REQ-100] 步长函数必须锚定常量（不挂当前值），且 +/− 严格互逆 ---');
const klineZoomStep = get('klineZoomStep');

// 1) 同源：步长只由锚点决定，且全域恒为正整数（分数步长会让回程丢根）
const stepAtFull = klineZoomStep(get('STANDARD_KLINE_VIEW_COUNT'));
assert(Number.isInteger(stepAtFull) && stepAtFull > 0,
  `步长必须是正整数，实际 ${stepAtFull} —— 非整数步长会让 N-step+step !== N`);
assert.equal(klineZoomStep(30), klineZoomStep(60), '同锚点区间内步长必须唯一（同源）');
assert.equal(klineZoomStep(150), klineZoomStep(200), '大窗区间的步长同样必须唯一（同源）');
// 2) 同数量级：锚点法不随当前值浮动 —— 把「当前值」当锚点传进来，结果必须与锚点一致（反证旧实现 round(cur*0.15)）
assert.equal(klineZoomStep(47), klineZoomStep(40),
  '同一次 +/− 的正反步长必须相等：47 与 40 得到的步长不得不同（旧 round(cur*0.15) 正是 47→40→46 的根因）');
// 3) 语义方向：同一个 step 必须同时服务「+＝减少根数（放大）」与「−＝增加根数（缩小）」
const stepMin = Math.min(Math.abs(get('MIN_PANEL_BARS') - get('STANDARD_KLINE_VIEW_COUNT')), stepAtFull);
assert(stepAtFull <= get('STANDARD_KLINE_VIEW_COUNT') - get('MIN_PANEL_BARS'),
  `步长 ${stepAtFull} 不得大于可视范围 ${get('STANDARD_KLINE_VIEW_COUNT') - get('MIN_PANEL_BARS')}（否则放大一档即触底，等于没有中间档）`);
assert(stepAtFull <= 44, `步长 ${stepAtFull} 不得大到「一档跳掉半个视窗」（上限 44 = 200 的 22%）`);

// 4) 严格可逆：真实调用 zoomKlineChart（+ 放大减少根数 / − 缩小增加根数），未触界时必须回到原值
const zoomKlineChart = get('zoomKlineChart');
function resetView(count) {
  run(`chartPanels.right.st.dimension = 'kline';
       chartPanels.right.st.klineGroup = 'daily';
       chartPanels.right.st.klineCount = ${count};
       chartPanels.right.st.panOffset = 0;
       chartPanels.right.st.availableCount = ${AVAILABLE};
       chartPanels.right.availableCount = ${AVAILABLE};`);
}
function currentCount() { return run('chartPanels.right.st.klineCount'); }

resetView(103);
assert.equal(currentCount(), 103, '初始视窗根数必须为 103（构造值）');
zoomKlineChart('in', 'right');
const afterIn = currentCount();
assert.equal(afterIn, 103 - stepAtFull, `+ 必须减少 ${stepAtFull} 根：103 → ${103 - stepAtFull}，实际 ${afterIn}`);
zoomKlineChart('out', 'right');
assert.equal(currentCount(), 103, `+ 后立即 − 必须严格回到 103（需求方原话口径），实际 ${currentCount()}`);

// 反向同样成立：− 后立即 +
resetView(103);
zoomKlineChart('out', 'right');
assert.equal(currentCount(), 103 + stepAtFull, `− 必须增加 ${stepAtFull} 根`);
zoomKlineChart('in', 'right');
assert.equal(currentCount(), 103, `− 后立即 + 必须严格回到 103，实际 ${currentCount()}`);

// 连续多档往返（旧实现按当前值取整 15% 会在此处漂移）
resetView(150);
for (let i = 0; i < 4; i++) zoomKlineChart('in', 'right');
const deepCount = currentCount();
for (let i = 0; i < 4; i++) zoomKlineChart('out', 'right');
assert.equal(currentCount(), 150, `连续 4 档 +/− 往返必须严格回到 150，实际 ${currentCount()}（深度 ${deepCount}）`);
assert.equal(deepCount, Math.max(get('MIN_PANEL_BARS'), 150 - 4 * stepAtFull), '连续放大必须每档等步长');

// 5) 上下限钳制 —— 触界不得越界，也不得把状态写成 NaN
resetView(200);
for (let i = 0; i < 30; i++) zoomKlineChart('in', 'right');
assert.equal(currentCount(), get('MIN_PANEL_BARS'),
  `连续放大必须钳制在下限 ${get('MIN_PANEL_BARS')} 根，实际 ${currentCount()}`);
for (let i = 0; i < 40; i++) zoomKlineChart('out', 'right');
assert.equal(currentCount(), AVAILABLE, `连续缩小必须钳制在可用根数 ${AVAILABLE}，实际 ${currentCount()}`);

// 6) 分时图不得参与根数缩放（既有铁律，回归防回退）
run(`chartPanels.left.st.dimension = 'minute'; chartPanels.left.st.minuteSub = 'timeline'; chartPanels.left.st.klineCount = 30;`);
zoomKlineChart('in', 'left');
assert.equal(run('chartPanels.left.st.klineCount'), 30, '当日分时图不参与根数缩放（固定全天）');

// 7) 源码级防回退：不得再有第二套按当前值浮动的缩放公式
assert.match(appSrc, /const KLINE_ZOOM_STEP_SMALL = \d+;/, '步长档位必须收敛为具名常量');
assert.match(appSrc, /const KLINE_ZOOM_STEP_LARGE = \d+;/, '步长档位必须收敛为具名常量');
assert.doesNotMatch(appSrc, /Math\.max\(5, Math\.Round\(cur \* 0\.15\)\)/i, '旧的 round(cur*0.15) 口径必须删除');
assert.doesNotMatch(appSrc, /Math\.round\(curCount \* 0\.05\)/, '指数页不得再另立 round(cur*0.05) 公式（不同源）');
const stepFnCalls = (appSrc.match(/klineZoomStep\(/g) || []).length;
assert.equal(stepFnCalls, 3, `步长函数必须只有「定义 1 处 + 调用 2 处（个股 ± / 指数滚轮）」，实际 ${stepFnCalls}`);

// ==================================================================
// REQ-099：日线 / 周线 / 季线 三颗粒度左右滑动平移
// ==================================================================
console.log('--- [REQ-099] 左右滑动平移：三颗粒度均生效、到界钳制、分时图不参与 ---');
const panKlineChart = get('panKlineChart');
const GROUPS = ['daily', 'weekly', 'quarterly'];

// 需求REQ-099: 颗粒度覆盖必须用**真实聚合管线的可用根数**（日线直接取；周/季由真实日K聚合），
//   不得把可用根数硬塞成 300 —— 真实链路会在重绘时用聚合结果覆写 st.availableCount。
//   installBars 在沙箱内生成K线，避免把上千根K线序列化进 vm 表达式。
const installBars = (n, group, count) => run(`(function(){
  var out = [], base = Date.parse('2015-01-05T00:00:00Z');
  for (var i = 0; i < ${n}; i++) {
    var d = new Date(base + i * 86400000);
    var close = 10 + Math.sin(i / 7) * 1.2;
    out.push({
      date: d.toISOString().slice(0, 10),
      open: Number((close - 0.05).toFixed(2)), close: Number(close.toFixed(2)),
      high: Number((close + 0.18).toFixed(2)), low: Number((close - 0.2).toFixed(2)),
      volume: 100000 + i * 1000, amount_yi: Number((1 + (i % 13) * 0.3).toFixed(2)),
      turnover_rate: Number((0.5 + (i % 7) * 0.1).toFixed(2))
    });
  }
  appState.activeDetailStock = { code: 'sh601939', daily_bars: out };
  chartPanels.right.st.dimension = 'kline';
  chartPanels.right.st.klineGroup = '${group}';
  chartPanels.right.st.klineCount = ${count};
  chartPanels.right.st.panOffset = 0;
  renderChartPanel('right');
  return { available: chartPanels.right.st.availableCount, count: chartPanels.right.st.klineCount, offset: chartPanels.right.st.panOffset };
})()`);

// 三种颗粒度各自喂足真实日K：日线 300 根 / 周线 1080 根（约 216 周）/ 季线 3600 根（约 40 季）
const GROUP_FIXTURE = {
  daily:     { raw: 300,  count: 60 },
  weekly:    { raw: 1080, count: 60 },
  quarterly: { raw: 3600, count: 30 }
};
const groupOffset = {};

GROUPS.forEach(group => {
  const fx = GROUP_FIXTURE[group];
  const seed = installBars(fx.raw, group, fx.count);
  const avail = seed.available;
  assert(avail > fx.count,
    `${group}：真实聚合可用根数必须大于视窗 ${fx.count}（实际 ${avail}），否则左右滑动无空间可平移`);
  const maxOffset = avail - seed.count;
  assert(maxOffset > 0, `${group}：maxOffset 必须为正`);
  // 右滑（正 delta）＝ 看左边更早K线 → panOffset 增加
  panKlineChart(10, 'right');
  assert.equal(run('chartPanels.right.st.panOffset'), 10,
    `${group} 日/周/季颗粒度：右滑 10 根必须把 panOffset 推到 10，实际 ${run('chartPanels.right.st.panOffset')}`);
  // 左滑（负 delta）＝ 看右边更新K线 → panOffset 减少
  panKlineChart(-4, 'right');
  assert.equal(run('chartPanels.right.st.panOffset'), 6, `${group}：左滑必须回退平移量`);
  // 到界钳制：不得越界
  panKlineChart(99999, 'right');
  assert.equal(run('chartPanels.right.st.panOffset'), maxOffset,
    `${group}：右滑到最早历史必须钳制在 ${maxOffset}（可用 ${avail} − 视窗 ${seed.count}）`);
  panKlineChart(-99999, 'right');
  assert.equal(run('chartPanels.right.st.panOffset'), 0, `${group}：左滑到最新必须钳制在 0`);
  // 平移量必须取整
  panKlineChart(3.7, 'right');
  assert.equal(run('chartPanels.right.st.panOffset'), 4, `${group}：平移量必须取整：3.7 → 4`);
  panKlineChart(-4, 'right');
  assert.equal(run('chartPanels.right.st.panOffset'), 0, `${group}：往返后必须回到最新端`);
  // 切颗粒度必须有数据可绘（防「切了没反应」）
  assert(avail >= 30, `${group}：可用根数 ${avail} 必须支撑最小视窗 30`);
  groupOffset[group] = maxOffset;
});
assert(Object.keys(groupOffset).length === 3, '日线 / 周线 / 季线 三种颗粒度必须全部覆盖到左右滑动');

// 分时图：固定全天全景，横向手势不得改变任何平移状态
run(`chartPanels.left.st.dimension = 'minute'; chartPanels.left.st.minuteSub = 'timeline'; chartPanels.left.st.panOffset = 0;`);
panKlineChart(20, 'left');
assert.equal(run('chartPanels.left.st.panOffset'), 0, '当日分时图不参与左右平移（固定全天走势）');

// 手势灵敏度必须唯一权威源（鼠标 /10 与触摸 /12 的两套手感已合并）
assert.match(appSrc, /const KLINE_PAN_PX_PER_BAR = \d+;/, '手势灵敏度必须收敛为 KLINE_PAN_PX_PER_BAR 常量');
assert.doesNotMatch(appSrc, /Math\.round\(deltaX \/ 12\)/, '触摸侧不得再残留 /12 的第二套灵敏度');
assert.doesNotMatch(appSrc, /Math\.round\(deltaX \/ 10\)/, '鼠标侧必须走常量而非硬编码 /10');

// 触摸增量必须累积：慢速滑动（每帧位移 < 1 根）多帧后仍要产生平移
assert.match(appSrc, /touchPanBars \+= deltaX \/ KLINE_PAN_PX_PER_BAR;/,
  '触摸平移必须累积像素余量（原每帧重置基准会让慢滑恒为 0 根）');
assert.match(appSrc, /touchPanBars -= bars;/, '只允许消费已推进的整根K线，余量必须留到下一帧');

// ==================================================================
// REQ-099：拖拽监听器不得随重绘累积（同一图元只许一份）
// ==================================================================
console.log('--- [REQ-099] window 监听器去重：重绘 N 次后同一手势只能平移一次 ---');
const svgRight = svgNodes.get('stockInteractiveSvg_right');
assert(svgRight, '右面板 SVG 必须已渲染（bindChartZoomAndDrawing 已执行）');
const dragFns = (type) => winListeners.filter(l => l.type === type);
const beforeMove = dragFns('mousemove').length;
assert(beforeMove >= 1, '拖拽后必须存在 window mousemove 监听器（左右滑动的手势载体）');
// 再重绘若干次：mousemove/mouseup 数量不得增长（旧实现每渲染一次就多挂一份 → 越滑越快）
const RERENDER = 5;
for (let i = 0; i < RERENDER; i++) {
  run(`chartPanels.right.st.klineCount = ${40 + i}; renderChartPanel('right');`);
}
assert.equal(dragFns('mousemove').length, beforeMove,
  `重绘 ${RERENDER} 次后 window mousemove 必须仍为 ${beforeMove} 份，实际 ${dragFns('mousemove').length}（旧实现会累加到 ${beforeMove + RERENDER} 份）`);
assert.equal(dragFns('mouseup').length, 1, `window mouseup 必须唯一，实际 ${dragFns('mouseup').length}`);
assert.equal(svgRight.listenersOf('mousedown').length, 1, `SVG mousedown 必须唯一，实际 ${svgRight.listenersOf('mousedown').length}`);
assert.equal(svgRight.listenersOf('touchstart').length, 1, `SVG touchstart 必须唯一，实际 ${svgRight.listenersOf('touchstart').length}`);

// 真实派发一次拖拽：window mousemove 只允许把视窗平移一次（N 份监听器会平移 N 次）
const dragSeed = installBars(GROUP_FIXTURE.daily.raw, 'daily', 60);
assert(dragSeed.available > 60, `拖拽用例需要真实日K（实际可用 ${dragSeed.available}）`);
assert.equal(dragSeed.offset, 0, '拖拽起点必须是最新端（panOffset=0）');
svgRight.listenersOf('mousedown')[0].fn({ button: 0, clientX: 500 });
dragFns('mousemove').forEach(l => l.fn({ clientX: 560 }));   // 单帧位移 60px → 6 根
const panAfterDrag = run('chartPanels.right.st.panOffset');
assert.equal(panAfterDrag, 6,
  `一次 60px 拖拽必须只平移 6 根，实际 ${panAfterDrag} —— 大于 6 说明监听器重复挂载（越滑越快）`);
dragFns('mouseup').forEach(l => l.fn({}));

// 触摸慢滑必须累积：单帧位移不足 1 根（10px）时，多帧后必须累计出真实平移
const touchSeed = installBars(GROUP_FIXTURE.daily.raw, 'daily', 60);
assert.equal(touchSeed.offset, 0, '触摸用例起点必须是最新端');
// 直接调用渲染期绑定的触摸处理器（与真实手势同一份闭包）
const touchStart = svgRight.listenersOf('touchstart')[0].fn;
const touchMove = svgRight.listenersOf('touchmove')[0].fn;
assert(touchStart && touchMove, '必须绑定 touchstart / touchmove 处理函数（移动端左滑右滑载体）');
touchStart({ touches: [{ clientX: 300, clientY: 100 }] });
for (let i = 0; i < 8; i++) {
  // 每帧右滑 6px：单帧不足 1 根，8 帧累计 48px → 必须平移 4 根（旧实现每帧重置基准 → 恒 0 根）
  touchMove({ touches: [{ clientX: 300 + (i + 1) * 6, clientY: 100 }] });
}
const panAfterTouch = run('chartPanels.right.st.panOffset');
assert.equal(panAfterTouch, 4,
  `触摸慢滑 8 帧 × 6px（累计 48px）必须平移 4 根，实际 ${panAfterTouch} —— 为 0 说明像素余量没累积`);

// 横向手势不得被纵向滚动误触发：纵向位移占优时不许平移
installBars(GROUP_FIXTURE.daily.raw, 'daily', 60);
touchStart({ touches: [{ clientX: 300, clientY: 100 }] });
for (let i = 0; i < 10; i++) {
  touchMove({ touches: [{ clientX: 304, clientY: 100 + (i + 1) * 20 }] });
}
assert.equal(run('chartPanels.right.st.panOffset'), 0, '纵向为主的滑屏不得平移K线（避免与页面滚动互相打架）');

console.log('PASS: REQ-099 日/周/季三颗粒度左右滑动平移（到界钳制、分时图排除、手势灵敏度量纲统一、监听器不累积）；'
  + 'REQ-100 ± 步长同源同量级且严格可逆（103→103、150→150）；REQ-101 字样收敛见 test_r13。');
