/**
 * tests/test_first_principles_signals.js
 * 针对第一性原理技术买卖点（方法1 AMT拍卖理论与方法8 威科夫努力与结果）的端到端自动化测试
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

// 1. 验证静态资源引用完整性
console.log('--- [Test 1] 验证静态文件结构与格式塔交互元素 ---');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const styleCss = fs.readFileSync(path.join(__dirname, '../web/style.css'), 'utf8');

assert(html.includes('btnAmtDraw_right'), 'K线图右上控制栏应包含 btnAmtDraw_right');
assert(html.includes('btnEffortDraw_right'), 'K线图右上控制栏应包含 btnEffortDraw_right');
assert(html.includes('firstPrinciplesModal'), 'HTML中应包含第一性原理说明弹窗');
assert(styleCss.includes('.first-principles-group'), 'CSS应包含第一性原理工具组样式');
assert(styleCss.includes('.btn-draw-tool.fp-btn'), 'CSS应包含格式塔原则设计的胶囊按钮样式');
assert(appJs.includes('calculateAuctionMarketProfile'), 'app.js 应包含拍卖市场理论算法');
assert(appJs.includes('calculateWyckoffEffortResult'), 'app.js 应包含威科夫努力与结果算法');
console.log('✅ 静态文件与格式塔 DOM 元素全部验证通过！');

// 2. 构造模拟算法沙盒环境测试第一性原理推算
console.log('\n--- [Test 2] 验证拍卖市场理论 (AMT) 价值区与拒绝买卖点推算 ---');

// 提取 app.js 中的核心算法函数进行沙盒测试
const sandbox = {
  Math: Math,
  Array: Array,
  Set: Set,
  Number: Number
};

// 构造测试用的 K 线序列 (模拟一段震荡筑底，并在下沿发生探底收复的走势)
const mockKlines = [];
let basePrice = 100.0;
for (let i = 0; i < 40; i++) {
  const vol = 10000 + Math.floor(Math.sin(i / 5) * 4000);
  const open = basePrice + Math.sin(i) * 2;
  const close = open + (i % 2 === 0 ? 0.8 : -0.7);
  const high = Math.max(open, close) + 0.6;
  const low = Math.min(open, close) - 0.6;
  mockKlines.push({ date: `2026-08-${String(i + 1).padStart(2, '0')}`, open, close, high, low, volume: vol });
}

// 在第 35 根 K 线注入极端下探但迅速收复（AMT 买点测试）
mockKlines[35] = {
  date: '2026-09-15',
  open: 98.5,
  low: 95.0, // 深度探底击穿 VAL
  high: 99.2,
  close: 99.0, // 收复长下影
  volume: 18000
};

// 在第 38 根注入放天量但窄幅十字星（努力与结果悖论测试）
mockKlines[38] = {
  date: '2026-09-18',
  open: 98.2,
  low: 97.9,
  high: 98.4,
  close: 98.15, // 仅 0.05 元极窄实体
  volume: 45000 // 巨大努力（均量的3倍+）
};

// 提取函数代码并在沙盒中执行
const fnAmtCode = appJs.match(/function calculateAuctionMarketProfile\([\s\S]*?\n\}/)[0];
const fnEffortCode = appJs.match(/function calculateWyckoffEffortResult\([\s\S]*?\n\}/)[0];

const evalEnv = new Function('mockKlines', `
  ${fnAmtCode}
  ${fnEffortCode}
  return {
    amt: calculateAuctionMarketProfile(mockKlines),
    effort: calculateWyckoffEffortResult(mockKlines)
  };
`);

const result = evalEnv(mockKlines);
assert(result.amt !== null, 'AMT 计算结果不应为空');
assert(Number.isFinite(result.amt.poc), 'POC 必须为有效有限数值');
assert(Number.isFinite(result.amt.vah), 'VAH 必须为有效有限数值');
assert(Number.isFinite(result.amt.val), 'VAL 必须为有效有限数值');
assert(result.amt.vah >= result.amt.val, 'VAH 必须大于等于 VAL');
console.log(`✅ AMT 价值区计算成功: VAH=¥${result.amt.vah.toFixed(2)}, POC=¥${result.amt.poc.toFixed(2)}, VAL=¥${result.amt.val.toFixed(2)}`);
console.log(`✅ AMT 识别到 ${result.amt.signals.length} 个价值区边缘拒绝信号`);

console.log('\n--- [Test 3] 验证威科夫努力与结果定律 (Effort vs Result) 异常识别 ---');
assert(result.effort !== null, 'Effort 计算结果不应为空');
assert(result.effort.anomalyIndices.size > 0, '应成功检测出努力与结果悖论异常柱');
assert(result.effort.signals.length > 0, '应成功生成吸收或滞涨买卖点');
const detected = result.effort.signals.find(s => s.idx === 38);
assert(detected, '第 38 根注入的异常 K 线应被精准识别为买卖点信号');
console.log(`✅ 成功捕捉到第 38 根天量窄实体异常: 标签=${detected.label}, 努力倍数=${detected.effortRatio.toFixed(1)}倍均量`);

console.log('\n🎉 所有第一性原理买卖点算法与格式塔交互接口全部测试通过！');
