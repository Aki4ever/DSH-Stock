// R03 (REQ-014/015) 图层交互回归：全部为构造数据，只在隔离的 vm 上下文中执行，不触碰产品库与浏览器。
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const src = fs.readFileSync('web/app.js', 'utf8');

function firstIndex(list) {
  return list.map(s => src.indexOf(s)).filter(i => i >= 0).sort((a, b) => a - b)[0];
}

// 抽出图层模型相关代码段（从常量定义到"智能自动画线算法"之前）
const start = src.indexOf('const LINE_LAYER_ORDER');
const end = src.indexOf('/**\n * 需求1/2: 智能自动画线算法');
assert(start >= 0 && end > start, '未能定位图层模型代码段');
const layerCode = src.slice(start, end);

const ctx = {
  appState: { lineLayers: null, lineZCounter: 1000, topLineId: null, autoLinesCount: 0, chanlunLayers: {}, showChanlunDraw: false },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  setTimeout: () => 0,
  clearTimeout: () => {},
  console
};
ctx.globalThis = ctx;
// 渲染入口在真实页面中由 app.js 提供；测试只关心状态机，用桩函数记录调用
ctx.renderActiveStockChart = () => { ctx.__renders++; };
ctx.__renders = 0;
vm.createContext(ctx);
vm.runInContext(layerCode, ctx);

// 命中/置顶逻辑位于图表交互区，单独抽出执行
const clickStart = src.indexOf('function handleChartLineClick(');
const clickEnd = src.indexOf('\nfunction hideTooltip(', clickStart);
assert(clickStart >= 0 && clickEnd > clickStart, '未能定位 handleChartLineClick');
vm.runInContext(src.slice(clickStart, clickEnd), ctx);

const A = ctx.appState;

function reset() {
  A.lineLayers = {
    auto: { key: 'auto', lines: [], visible: true },
    manual_up: { key: 'manual_up', lines: [], visible: true },
    manual_down: { key: 'manual_down', lines: [], visible: true }
  };
  A.lineZCounter = 1000;
  A.topLineId = null;
}

// vm 沙箱内的数组与宿主 realm 的原型不同，统一用宿主数组比较
const ids = () => Array.from(ctx.getVisibleChartLines(), l => l.id);
const layers = () => Array.from(ctx.getVisibleChartLines(), l => l.layerKey);

const mk = (id, price, type) => ({ id, price, type, crossedDays: 3, crossedAmountYi: 12.5 });

// ---------------- REQ-014 多模型共存 ----------------
reset();
ctx.addChartLine('auto', mk('a1', 20, '最强压力'));
ctx.addChartLine('auto', mk('a2', 15, '最强支撑'));
ctx.addChartLine('manual_up', mk('m1', 22, '压力位'));
ctx.addChartLine('manual_down', mk('m2', 12, '支撑位'));

assert.equal(ctx.countLayerLines('auto'), 2, '自动线模型应有 2 根');
assert.equal(ctx.countLayerLines('manual_up'), 1, '压力线模型应有 1 根');
assert.equal(ctx.countLayerLines('manual_down'), 1, '支撑线模型应有 1 根');
assert.equal(ctx.getVisibleChartLines().length, 4, '三个模型必须同时存在，互不覆盖');

// 模型按 zIndex 升序绘制：末尾者位于最顶层
const ordered = layers();
assert.deepEqual(ordered, ['auto', 'auto', 'manual_up', 'manual_down'], '绘制顺序必须按 zIndex 升序');

// ---------------- REQ-014 分模型清除 ----------------
ctx.clearChartLayer('manual_up');
assert.equal(ctx.countLayerLines('manual_up'), 0, '压力线应被清空');
assert.equal(ctx.countLayerLines('manual_down'), 1, '清除压力线不得影响支撑线');
assert.equal(ctx.countLayerLines('auto'), 2, '清除压力线不得影响自动线');

ctx.clearChartLayer('auto');
assert.equal(ctx.countLayerLines('auto'), 0, '自动线应被清空');
assert.equal(ctx.countLayerLines('manual_down'), 1, '清除自动线不得影响支撑线');

// 分模型显隐
ctx.toggleChartLayerVisible('manual_down');
assert.equal(ctx.appState.lineLayers.manual_down.visible, false);
assert.equal(ctx.getVisibleChartLines().length, 0, '隐藏模型后不得出现在可见列表');
ctx.toggleChartLayerVisible('manual_down');
assert.equal(ctx.getVisibleChartLines().length, 1, '恢复显示应重新可见');

// ---------------- REQ-015 重合置顶 ----------------
reset();
ctx.addChartLine('auto', mk('a1', 20, '最强压力'));
ctx.addChartLine('manual_up', mk('m1', 20, '压力位'));
ctx.addChartLine('manual_down', mk('m2', 20, '支撑位'));
assert.equal(ctx.getVisibleChartLines().length, 3, '三条重合线必须同时存在');

const before = ids();
assert.deepEqual(before, ['a1', 'm1', 'm2'], '初始层级应为 auto < manual_up < manual_down');

// 模拟 render：写入 _svgY / _tagX / _tagW 供命中检测
const align = () => ctx.getVisibleChartLines().forEach(l => { l._svgY = 100; l._tagX = 700; l._tagW = 200; });

// 点击重合线本体 → 轮换置顶：最低层级者被提到最顶层
align();
ctx.handleChartLineClick(300, 100, 860, 440, { top: 20, left: 65, right: 65 }, 270);
assert.deepEqual(ids(), ['m1', 'm2', 'a1'], '第一次点击应把 a1 置顶');

align();
ctx.handleChartLineClick(300, 100, 860, 440, { top: 20, left: 65, right: 65 }, 270);
assert.deepEqual(ids(), ['m2', 'a1', 'm1'], '第二次点击应把 m1 置顶');

align();
ctx.handleChartLineClick(300, 100, 860, 440, { top: 20, left: 65, right: 65 }, 270);
assert.deepEqual(ids(), ['a1', 'm1', 'm2'], '第三次点击应把 m2 置顶，完成一轮巡览');

// 点击标签徽章 → 精准置顶指定的一条重合线
align();
ctx.handleChartLineClick(720, 100, 860, 440, { top: 20, left: 65, right: 65 }, 270);
const tagTop = Array.from(ctx.getVisibleChartLines()).slice(-1)[0];
assert.ok(['a1', 'm1', 'm2'].includes(tagTop.id), '标签命中必须置顶其中一条具体辅助线');

// 唯一命中 → 直接置顶
reset();
ctx.addChartLine('auto', mk('solo', 30, '最强压力'));
const solo = ctx.appState.lineLayers.auto.lines[0];
solo._svgY = 60; solo._tagX = 700; solo._tagW = 200;
ctx.handleChartLineClick(300, 60, 860, 440, { top: 20, left: 65, right: 65 }, 270);
assert.equal(ctx.appState.topLineId, 'solo', '唯一命中应被置顶并高亮');

// 未命中任何线 → 不改变任何状态
reset();
ctx.addChartLine('auto', mk('far', 30, '最强压力'));
ctx.appState.lineLayers.auto.lines[0]._svgY = 60;
const zBefore = ctx.appState.lineLayers.auto.lines[0].zIndex;
ctx.handleChartLineClick(300, 400, 860, 440, { top: 20, left: 65, right: 65 }, 270);
assert.equal(ctx.appState.lineLayers.auto.lines[0].zIndex, zBefore, '未命中不得改变层级');
assert.equal(ctx.appState.topLineId, null, '未命中不得改变置顶高亮');

// ---------------- REQ-015 统一渲染器 ----------------
reset();
ctx.addChartLine('auto', mk('a1', 20, '最强压力'));
ctx.addChartLine('manual_up', mk('m1', 20.02, '压力位'));
A.topLineId = 'a1';
const svg = ctx.buildHorizontalLinesSVG({ m: { left: 65, top: 20 }, innerW: 700, priceToY: p => 200 - p, refPrice: 18 });
assert.ok(svg.includes('data-line-id="a1"'), '渲染必须带上线标识');
assert.ok(svg.includes('layer-auto') && svg.includes('layer-manual_up'), '两个模型都必须被渲染');
assert.ok(svg.includes('重合2'), '重合线必须标注重合条数');
assert.ok(svg.includes('⭐'), '置顶线必须有置顶标记');
assert.ok(!/NaN|undefined/.test(svg), '渲染结果不得出现 NaN/undefined');
const a1 = ctx.appState.lineLayers.auto.lines[0];
assert.equal(a1._svgY, 180, '渲染必须回写 SVG 坐标供命中检测');

const emptySvg = (() => { reset(); return ctx.buildHorizontalLinesSVG({ m: { left: 65, top: 20 }, innerW: 700, priceToY: p => 200 - p, refPrice: 18 }); })();
assert.equal(emptySvg, '', '无任何辅助线时应返回空字符串，不产生占位图形');

// ---------------- REQ-026 图层面板指标摘要与「!」说明入口 ----------------
// 面板渲染依赖 formatTradeArea（REQ-026 的展示口径），一并注入
const faStart = src.indexOf('function formatTradeArea(');
assert(faStart >= 0, '未能定位 formatTradeArea');
vm.runInContext(src.slice(faStart, src.indexOf('function amountCoverageFlags(', faStart)), ctx);

const panelEl = { innerHTML: '' };
const prevGetById = ctx.document.getElementById;
ctx.document.getElementById = (id) => (id === 'chartLayerPanel' ? panelEl : null);

reset();
A.autoLinesCount = 0;
A.autoLinesBlockedReason = null;
ctx.addChartLine('manual_up', {
  id: 'up1', price: 22, type: '压力位', crossedDays: 4, crossedAmountYi: 12.5,
  tradeAreaYi: 88.5, tradeAreaDays: 120, tradeAreaExcludedDays: 4, tradeAreaIncomplete: false
});
ctx.addChartLine('manual_down', {
  id: 'dn1', price: 12, type: '支撑位', crossedDays: 0, crossedAmountYi: 0,
  tradeAreaYi: null, tradeAreaDays: 0, tradeAreaExcludedDays: 0, tradeAreaIncomplete: false
});
ctx.renderLineLayerPanel(null);
assert(/id="btnLineMetricHelp"/.test(panelEl.innerHTML), '图层面板标题旁必须存在「!」指标说明按钮');
assert(/! 指标说明/.test(panelEl.innerHTML), '按钮文案必须可辨识为指标说明');
assert(/openLineMetricHelp\(\)/.test(panelEl.innerHTML), '「!」按钮必须绑定指标说明弹窗入口');
assert(/交易面积: 88\.50亿 \(未交汇: 120天\)/.test(panelEl.innerHTML), '面板必须呈现交易面积（与图内标签同源口径）');
assert(/交易面积: 未交汇/.test(panelEl.innerHTML), '未交汇的辅助线必须显示「未交汇」而不是 0');

// 图内标签同样必须追加交易面积
const labelSvg = ctx.buildHorizontalLinesSVG({ m: { left: 65, top: 20 }, innerW: 700, priceToY: p => 200 - p, refPrice: 18 });
assert(/交易面积: 88\.50亿/.test(labelSvg), '图内辅助线标签必须追加交易面积');

ctx.document.getElementById = prevGetById;

// ---------------- REQ-026 「!」弹窗内容：交易面积公式必须可见 ----------------
const html = fs.readFileSync('web/index.html', 'utf8');
const modalStart = html.indexOf('id="lineMetricHelpModal"');
assert(modalStart >= 0, '页面必须包含「!」指标说明弹窗容器');
const modal = html.slice(modalStart, html.indexOf('</div>\n  </div>\n\n  <script', modalStart)).replace(/\u00a0/g, ' ');
for (const [needle, why] of [
  ['S_area(P)', '交易面积公式必须写入弹窗'],
  ['d_first', '首个交汇交易日的锚定必须写明'],
  ['T \\ D', '必须写明剔除自身交汇交易日'],
  ['不受当前缩放窗口影响', '必须写明累计口径不受缩放影响'],
  ['剔除该线自身交汇的交易日', '必须写明剔除规则'],
  ['覆盖不完整', '必须写明覆盖不完整不得以 0 补齐'],
  ['当日均价 × 当日成交量', '必须写明成交额兜底口径'],
  ['（估算：均价×成交量）', '必须写明估算口径的显式标记'],
  ['交汇交易日集合不得与已选线完全重复', '必须写明自动线排序约束'],
  ['不会显示 0 根、0 元或任何推测数值', '必须写明数据不足时的展示规则']
]) {
  assert(modal.includes(needle), `弹窗缺少必要内容：${why}`);
}
assert(html.includes('onclick="closeLineMetricHelp()"'), '弹窗必须可关闭');
assert(html.includes('id="lineMetricHelpModal"'), '弹窗容器 id 必须与 openLineMetricHelp 一致');

console.log('PASS: 多模型共存 / 分模型清除互不影响 / 分模型显隐 / 重合轮换置顶 / 标签精准置顶 / 未命中不改状态 / 统一渲染器 / 交易面积与「!」入口与公式可见');
