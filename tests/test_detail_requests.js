const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const elements = new Map();
const el = () => ({value:'', style:{}, classList:{add(){},remove(){},toggle(){}},textContent:'',innerHTML:''});
const dom = new Proxy({}, {get(_, key){if(!elements.has(key))elements.set(key,el());return elements.get(key)}});
const pending = new Map();
const context = {AbortController, console, dom, appState:{detailRequestId:0,shareholderDays:365}, document:{getElementById:()=>null}, window:{scrollTo(){}},
 switchDetailDimension(){},hideTooltip(){},roundTo:x=>x,renderFinancialTables(){},renderActiveStockChart(){context.rendered=context.appState.activeDetailStock.code},
 fetch: url => url.includes('/finance?') ? Promise.resolve({ok:true,json:async()=>({data:{}})}) : new Promise(resolve=>pending.set(url.match(/stock\/([^?]+)/)[1],resolve))};
vm.createContext(context);
const begin=source.indexOf('async function openStockDetail(');
const end=source.indexOf('/**\n * 切换财务分析',begin);
vm.runInContext(source.slice(begin,end),context);
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
