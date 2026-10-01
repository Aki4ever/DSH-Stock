const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { loadWebSource } = require('./load_web_sources');
const source = loadWebSource();  // 需求REQ-053: 按页面顺序装载 util.js + app.js
const elements = new Map();
const el = () => ({value:'', style:{}, classList:{add(){},remove(){},toggle(){}},textContent:'',innerHTML:''});
const dom = new Proxy({}, {get(_, key){if(!elements.has(key))elements.set(key,el());return elements.get(key)}});
const pending = new Map();
const context = {AbortController, console, dom, appState:{detailRequestId:0,shareholderDays:365}, document:{getElementById:()=>null}, window:{scrollTo(){}},
 formatReal:v=>v==null?"未获取":String(v),escapeHtml:v=>String(v),switchDetailDimension(){},hideTooltip(){},roundTo:x=>x,renderFinancialTables(){},renderActiveStockChart(){context.rendered=context.appState.activeDetailStock.code},
 fetch: url => url.includes('/finance?') ? Promise.resolve({ok:true,json:async()=>({data:{}})}) : new Promise(resolve=>pending.set(url.match(/stock\/([^?]+)/)[1],resolve))};
vm.createContext(context);
// 需求REQ-014: openStockDetail 会复位图表图层模型，因此需要一并注入图层模型代码
const layerBegin = source.indexOf('const LINE_LAYER_ORDER');
const layerEnd = source.indexOf('/**\n * 需求1/2: 智能自动画线算法', layerBegin);
vm.runInContext(source.slice(layerBegin, layerEnd), context);
const resetBegin = source.indexOf('function resetAllChartLayers(');
vm.runInContext(source.slice(resetBegin, source.indexOf('\n}', resetBegin) + 2), context);
// 需求REQ-031「换手率统一权威计算」：openStockDetail 载入详情后会用它逐根补齐 turnover_rate，
// 该函数定义在 openStockDetail 切片之外，必须在沙箱内注入同一份真实实现（断言意图不变，只补依赖）。
const turnBegin = source.indexOf('function getStockCirculatingShares(');
const turnEnd = source.indexOf('\n}', source.indexOf('function resolveItemTurnoverRate(')) + 2;
vm.runInContext(source.slice(turnBegin, turnEnd), context);
const begin=source.indexOf('async function openStockDetail(');
const end=source.indexOf('/**\n * 切换财务分析',begin);
vm.runInContext(source.slice(begin,end),context);
// 需求REQ-034: 详情加载态改为按「双图面板」逐个刷写，沙箱注入与页面同名的面板表（DOM 取不到时各自静默跳过）
context.PANEL_SLOTS = ['left', 'right'];
const panelStub = (slot) => ({
  slot: slot, containerId: 'chartSvgContainer' + (slot === 'left' ? 'Left' : 'Right'),
  autoCountControlId: 'autoLinesCountControl_' + slot, hlineBtnId: 'btnToggleHLine_' + slot,
  st: context.appState
});
context.chartPanels = { left: panelStub('left'), right: panelStub('right') };
context.panelBySlot = (slot) => context.chartPanels[slot] || context.chartPanels.right;
context.withChartPanel = (slot, fn) => fn(context.panelBySlot(slot));
context.syncPanelToAppState = () => {};
context.persistPanelFromAppState = () => {};
context.renderChartPanel = () => {};
context.MIN_PANEL_BARS = 30;
// 需求REQ-041: resetAllChartLayers 复位买卖点等级时会取默认等级常量，沙箱内注入同值常量
context.DEFAULT_BS_LEVEL = 3;
// 需求REQ-037: resetAllChartLayers 复位副图时会取本颗粒度的默认档位，沙箱内注入同语义实现
context.panelDefaultSubplot = () => 'vol';
function stock(code) {return {code,name:code,market:'上证',market_code:'sh',board:'主板',price:10,prev_close:9,open:9,high:11,low:8,market_cap:1,circulating_cap:1,pe:1,history_meta:{code},daily_bars:[{date:'2026-09-18'}]};}
const reply = (code, data=stock(code)) => pending.get(code)({ok:true,json:async()=>({data})});
(async()=>{
 const first=context.openStockDetail('sh600519');
 const second=context.openStockDetail('sz000001');
 reply('sz000001');await second;
 reply('sh600519');await first;
 assert.equal(context.appState.activeDetailStock.code,'sz000001');
 assert.equal(context.rendered,'sz000001');
 const mismatch=context.openStockDetail('sh601288');
 reply('sh601288',stock('sh600519'));await mismatch;
 assert.equal(context.appState.activeDetailStock,null);
 assert.match(dom.chartSvgContainer.innerHTML,/代码与请求不一致/);
 const missing=context.openStockDetail('sh601398');const untrusted=stock('sh601398');delete untrusted.history_meta;reply('sh601398',untrusted);await missing;
 assert.equal(context.appState.activeDetailStock.daily_bars.length,0);
 console.log('PASS: response race, symbol mismatch, unverified history rejection');
})().catch(e=>{console.error(e);process.exit(1)});
