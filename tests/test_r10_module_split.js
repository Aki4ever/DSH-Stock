/**
 * R10 批次前端静态回归（需求REQ-053）：web/app.js 模块化拆分第一步的契约与行为等价性。
 *
 * 断言策略：不复制产品代码，全部断言真实的 web/modules/util.js、web/app.js、web/index.html 与
 * tests/load_web_sources.js。既验证"拆得干净"（无重复声明、无残留、纯函数、顺序正确），
 * 也验证"行为没变"（迁出函数在沙箱里的输出与拆分前的黄金值逐字一致）。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { WEB_SOURCES, loadWebSource, loadIndexHtml, readWebFile } = require('./load_web_sources');

const MIGRATED = [
  'escapeActionText', 'escapeHtml', 'roundTo', 'formatStatVal', 'formatVolume',
  'formatAmountYi', 'formatReal', 'estimateSvgTextWidth', 'layoutSubplotHeader', 'formatQuoteMoment',
];

const utilSrc = readWebFile('modules/util.js');
const appSrc = readWebFile('app.js');
const html = loadIndexHtml();

const declaredIn = (src) => MIGRATED.filter(n => new RegExp(`^function ${n}\\(`, 'm').test(src));

// ---------- 1. 拆分完整性：迁出函数只存在于 util.js，app.js 不再声明 ----------
assert.deepEqual(declaredIn(utilSrc).sort(), [...MIGRATED].sort(),
  'util.js 必须声明全部且仅有这 10 个迁出函数');
assert.deepEqual(declaredIn(appSrc), [],
  `app.js 不得再声明已迁出的函数（残留：${declaredIn(appSrc).join(', ')}）`);

// ---------- 2. 纯函数契约：不碰 DOM / 全局状态 / 无顶层副作用 ----------
// 注意：断言对象是**去掉注释后的代码**（模块头部说明本身会提到 appState 等词，属文档而非依赖）
const utilCode = utilSrc
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter(l => !l.trim().startsWith('//')).join('\n');
assert.ok(!/\bdocument\s*\./.test(utilCode), 'util.js 不得访问 document');
assert.ok(!/\bwindow\s*\./.test(utilCode), 'util.js 不得访问 window');
assert.ok(!/\bappState\b|\bchartPanels\b|\bdom\b\s*\./.test(utilCode), 'util.js 不得引用应用状态');
// 用大括号配对求真实顶层行（函数体内的 const/let 不算顶层）
let depth = 0;
const topLevelStatements = [];
for (const rawLine of utilCode.split('\n')) {
  const line = rawLine.trim();
  if (depth === 0 && line) topLevelStatements.push(line);
  for (const ch of rawLine) {
    if (ch === '{') depth += 1;
    else if (ch === '}') depth -= 1;
  }
}
assert.equal(depth, 0, 'util.js 大括号必须配平（源码不得被截断）');
assert.deepEqual(topLevelStatements.filter(l => /^(const|let|var|class)\s/.test(l)), [],
  'util.js 顶层不得有影响加载时序的 const/let/var/class 声明');
assert.deepEqual(topLevelStatements.filter(l => !/^function\s|^\}$/.test(l)), [],
  'util.js 顶层只允许函数声明（不得有可执行语句）');

// ---------- 3. 页面加载顺序：util.js 必须早于 app.js，且清单一致 ----------
const scriptTags = [...html.matchAll(/<script\s+src="([^"]+)"/g)].map(m => m[1]);
const utilIdx = scriptTags.findIndex(s => s.includes('/web/modules/util.js'));
const appIdx = scriptTags.findIndex(s => s.includes('/web/app.js'));
assert.ok(utilIdx >= 0 && appIdx >= 0, 'index.html 必须同时加载 util.js 与 app.js');
assert.ok(utilIdx < appIdx, `util.js 必须先于 app.js 加载（实际顺序：${scriptTags.join(' → ')}）`);
assert.deepEqual(
  WEB_SOURCES,
  scriptTags.filter(s => s.startsWith('/web/')).map(s => s.replace('/web/', '').replace(/\?.*$/, '')),
  'tests/load_web_sources.js 的清单必须与 index.html 的脚本顺序一致（静态套件才能与页面同构）'
);

// ---------- 4. 行为等价：迁移后的函数输出必须与拆分前逐字一致 ----------
function loadUtilSandbox() {
  const sandbox = {};
  vm.createContext(sandbox);
  new vm.Script(utilSrc).runInContext(sandbox);
  return sandbox;
}
const util = loadUtilSandbox();

assert.equal(util.escapeHtml('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
assert.equal(util.escapeActionText('无特殊字符'), '无特殊字符');
assert.equal(util.roundTo(1.23456, 3), 1.235);
assert.equal(util.formatStatVal(null, '亿元'), '--');
assert.equal(util.formatStatVal(12345, '亿元'), '1.23万亿');
assert.equal(util.formatVolume(0), '0手');
assert.equal(util.formatVolume(123456), '12.35万');
assert.equal(util.formatAmountYi(null), '未提供');
assert.equal(util.formatAmountYi(1701.234), '1701.23亿');
assert.equal(util.formatReal(null), '未获取');
assert.equal(util.formatReal(1234.567), (1234.567).toLocaleString(undefined, { maximumFractionDigits: 2 }));

// REQ-046：用户给的样例必须仍解析为「2026年9月23日 15:34」
// 注意：沙箱内创建的对象与宿主不是同一 realm，跨 realm 的深层比较需先摊平成宿主对象
assert.deepStrictEqual({ ...util.formatQuoteMoment('20260923153400') }, {
  display: '2026年9月23日 15:34', precision: 'minute', raw: '20260923153400', date: '2026-09-23', time: '15:34',
});
assert.equal(util.formatQuoteMoment({ date: '2026-09-23', precision: 'day' }).display, '2026年9月23日');
assert.equal(util.formatQuoteMoment(null), null);

// REQ-047：表头平铺在窄区间内必须换行而不是叠画；宽度随字号单调递增
const wide = util.estimateSvgTextWidth('副图：成交额', 10);
const narrow = util.estimateSvgTextWidth('副图：成交额', 6);
assert.ok(wide > narrow && narrow > 0, `宽度必须随字号单调递增（${narrow} → ${wide}）`);
const laid = util.layoutSubplotHeader({
  x0: 65, y: 470, fontSize: 10, maxRight: 855, title: '副图：成交额',
  items: [{ label: '总和', value: '1101.70亿（含估算）' }, { label: '平均', value: '36.72亿' },
          { label: '地量(最小)', value: '17.58亿' }, { label: '天量(最大)', value: '101.36亿' },
          { label: '中位数', value: '32.50亿' }],
});
assert.equal(laid.dropped, 0, '正常宽度下不得丢弃任何统计项');
assert.match(laid.svg, /class="sub-summary-group"/);
assert.match(laid.svg, /副图：成交额/);
assert.ok(laid.rows >= 1 && laid.rows <= 3, `行数必须在 1~3 之间（实际 ${laid.rows}）`);
const cramped = util.layoutSubplotHeader({
  x0: 65, y: 470, fontSize: 10, maxRight: 240, maxRows: 2, title: '副图：成交额',
  items: [{ label: '总和', value: '1101.70亿（含估算）' }, { label: '平均', value: '36.72亿' },
          { label: '地量(最小)', value: '17.58亿' }, { label: '天量(最大)', value: '101.36亿' },
          { label: '中位数', value: '32.50亿' }],
});
assert.ok(Number.isInteger(cramped.dropped) && cramped.dropped >= 0, 'dropped 必须是非负整数');
assert.ok(cramped.rows <= 2, 'maxRows 必须被尊重（不得无限换行）');
assert.ok(cramped.dropped > 0, '窄区间 + 2 行上限时必须有被如实丢弃的统计项（而不是叠画）');

// ---------- 5. 真拆离：合并源码里每个迁出函数只能出现一次（证明不是复制粘贴） ----------
const combined = loadWebSource();
for (const name of MIGRATED) {
  const hits = (combined.match(new RegExp(`^function ${name}\\(`, 'gm')) || []).length;
  assert.equal(hits, 1, `${name} 在「页面装载的全部源码」中必须恰好声明一次（实际 ${hits} 次）`);
}

console.log(`PASS: REQ-053 模块拆分契约（${MIGRATED.length} 个纯函数迁出 · 顺序 ${WEB_SOURCES.join(' → ')} · 行为黄金值逐字一致）`);
