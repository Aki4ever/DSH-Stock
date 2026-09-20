// Constructed fixtures stay inside this isolated Node test; no browser or DB writes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const s=fs.readFileSync('web/app.js','utf8');
const c={appState:{chanlunLayers:{},drawnHorizontalLines:[]}};vm.createContext(c);
for (const [start,end] of [['function generateChanlunOverlaySVG(', 'function renderChanlunLegend('],['function calculateAutoSupportResistanceLevels(', 'function setAutoLinesCount(']]) {
 const a=s.indexOf(start),b=s.indexOf(end,a);assert(a>=0&&b>a);vm.runInContext(s.slice(a,b),c);
}
const dates=['2026-01-01','2026-01-02','2026-01-03','2026-01-04'];
const line={start_time:dates[0],end_time:dates[3],start_price:10,end_price:13,status:'confirmed'};
const analysis={dates,pens:[line],segments:[line],pivots:[{...line,zg:12,zd:11}],divergences:[{time:dates[2],price:12,kind:'顶背离',status:'confirmed',previous_area:2,current_area:1}],ma_entanglements:[{...line,high:13,low:10}],parameters:{ma_periods:[2]},ma:{2:[null,10.5,11.5,12.5]}};
const window=dates.slice(2).map(date=>({date}));
let svg=c.generateChanlunOverlaySVG(window,i=>i*10,p=>100-p,analysis);
for(const key of ['pens','segments','pivots','divergences','ma_entanglements'])assert(svg.includes('chanlun-'+key));
assert(svg.includes('x1="-20"'));assert(svg.includes('width="10"'));assert(!/NaN|undefined/.test(svg));
c.appState.chanlunLayers.pens=false;svg=c.generateChanlunOverlaySVG(window,i=>i*10,p=>100-p,analysis);assert(!svg.includes('chanlun-pens'));assert(svg.includes('chanlun-segments'));
// 需求REQ-025 (v5.0.0 修订): 成交额缺失时按「均价×成交量」兜底，不再一律拒绝；
// 但「成交额与成交量同时缺失」仍必须严格拒绝生成自动多阶线（禁止以 0 参与排序）。
assert.equal(c.calculateAutoSupportResistanceLevels([{high:12,low:9,close:10,volume:100,amount_yi:null}],10,1).length,0,
 'amount=null 且 volume 未解析（未经兜底入口）时仍不得以 0 参与排序');
assert.equal(c.calculateAutoSupportResistanceLevels([{high:12,low:9,close:10,volume:null,amount_yi:null}],10,1).length,0,
 '成交额与成交量同时缺失时必须拒绝生成自动线');
assert(c.calculateAutoSupportResistanceLevels([{high:12,low:9,close:10,amount_yi:1}],10,1).length>0);
console.log('PASS: five SVG layers, independent toggle, off-window endpoints, clipped spans, no turnover without any source');
