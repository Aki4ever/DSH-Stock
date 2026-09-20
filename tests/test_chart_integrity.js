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
assert.equal(c.calculateAutoSupportResistanceLevels([{high:12,low:9,close:10,volume:100,amount_yi:null}],10,1).length,0);
assert(c.calculateAutoSupportResistanceLevels([{high:12,low:9,close:10,amount_yi:1}],10,1).length>0);
console.log('PASS: five SVG layers, independent toggle, off-window endpoints, clipped spans, no inferred turnover');
