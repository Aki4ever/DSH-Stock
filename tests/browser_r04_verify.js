#!/usr/bin/env node
/**
 * R04 真机浏览器验证 (headless Chrome + CDP)
 * 覆盖 REQ-022/023/024/025/026：
 *   1. 首次切 Tab 固定标准 200 根；滚轮缩放只改根数、绘图区几何不变；缩放下限 5 / 上限 200
 *   2. 根数不足 200 时右侧留白，单根宽度仍取标准槽宽
 *   3. 分时图可生成自动画线与缠论画线（分时级别），且显式标注级别
 *   4. 成交额缺失时按「均价×成交量」兜底并标注估算来源。
 *      （旧断言「日线缺成交额即不生成自动线」已按 REQ-025 修订，此处验证新口径）
 *   5. 交易面积指标与「!」指标说明弹窗（含公式与三条口径铁律）
 * 仅使用 Node 内置模块；只驱动已运行的 127.0.0.1:8888 页面，不写入产品数据。
 */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const CHROME = process.env.DSH_CHROME_BIN ||
  path.join(os.homedir(), 'Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');
const PORT = 9334;
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-20-r04';

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function fetchJson(url, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch (_) {}
    await sleep(250);
  }
  throw new Error(`无法连接调试端点: ${url}`);
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('WebSocket 连接失败')); });
    const c = new CDP(ws);
    ws.onmessage = ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id && c.pending.has(msg.id)) {
        const { resolve, reject } = c.pending.get(msg.id);
        c.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) {
        c.events.push(msg);
      }
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) {
      throw new Error(`页面内脚本异常: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    }
    return r.result.value;
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.join(OUT, name);
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
    return file;
  }
}

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
}

// 页面内通用的 SVG 几何探测：从蜡烛矩形反推根数与占用宽度
const CANDLE_PROBE = `(() => {
  const svg = document.getElementById('stockInteractiveSvg');
  if (!svg) return { error: '未找到图表 SVG' };
  const rects = [...svg.querySelectorAll('rect')].filter(r => ['#ef4444', '#10b981'].includes(r.getAttribute('fill')));
  const body = rects.filter(r => r.getAttribute('opacity') === null);
  const bars = rects.filter(r => r.getAttribute('opacity') !== null);
  if (!body.length) return { error: '未找到蜡烛实体' };
  const xs = body.map(r => parseFloat(r.getAttribute('x')));
  const ws = body.map(r => parseFloat(r.getAttribute('width')));
  const grid = svg.querySelector('rect[fill="#0f172a"]');
  return {
    candles: body.length,
    subBars: bars.length,
    candleWidth: ws[0],
    firstLeft: Math.min(...xs),
    lastRight: Math.max(...xs) + ws[xs.indexOf(Math.max(...xs))],
    plotLeft: grid ? parseFloat(grid.getAttribute('x')) : null,
    plotWidth: grid ? parseFloat(grid.getAttribute('width')) : null
  };
})()`;

const CHIP_PROBE = `(() => {
  const btns = [...document.querySelectorAll('#autoLinesCountControl .seg-btn')];
  return btns.filter(b => b.classList.contains('active')).map(b => b.textContent.trim());
})()`;

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-r04-chrome-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1600,1200', '--hide-scrollbars', 'about:blank'
  ], { stdio: 'ignore' });

  let cdp;
  try {
    const version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
    check('headless Chrome 已就绪', !!version.webSocketDebuggerUrl, version.Browser);
    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    cdp = await CDP.connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');

    const consoleErrors = [];
    cdp.ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') consoleErrors.push(m.params.entry.text);
      if (m.method === 'Runtime.exceptionThrown') consoleErrors.push(m.params.exceptionDetails.text);
    });

    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(4000);
    check('页面加载成功', typeof (await cdp.eval('document.title')) === 'string', await cdp.eval('document.title'));

    // ---------- 打开一个真实标的详情 ----------
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(6000);
    const opened = await cdp.eval(`(() => {
      const s = appState.activeDetailStock;
      return s ? { code: s.code, name: s.name, bars: (s.daily_bars||[]).length } : null;
    })()`);
    check('个股详情已加载真实历史', !!opened && opened.bars > 0, opened ? `${opened.name} ${opened.code} · ${opened.bars} 根` : '未加载');

    // ---------- REQ-022：首次切 Tab 固定标准 200 根 ----------
    await cdp.eval(`switchChartPeriod('all')`);
    await sleep(1500);
    const p200 = await cdp.eval(CANDLE_PROBE);
    check('REQ-022 首次切「全部」Tab 恰好显示 200 根', p200.candles === 200, `实际 ${p200.candles} 根`);
    check('REQ-022/023 满 200 根铺满绘图区（无留白）',
      p200.lastRight > p200.plotLeft + p200.plotWidth * 0.95,
      `占用至 ${p200.lastRight.toFixed(1)} / 绘图区右缘 ${(p200.plotLeft + p200.plotWidth).toFixed(1)}`);
    const stdCandleWidth = p200.candleWidth;
    const fullRightEdge = p200.lastRight;
    const fullPlot = { left: p200.plotLeft, width: p200.plotWidth };
    const shot200 = await cdp.shot('01-standard-200-bars.png');

    // ---------- REQ-022：滚轮缩小 → 根数增多，但上限严格 200 ----------
    await cdp.eval(`(() => { const svg = document.getElementById('stockInteractiveSvg');
      for (let i = 0; i < 40; i++) svg.dispatchEvent(new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true }));
      return appState.chartCustomZoomCount; })()`);
    await sleep(1200);
    const afterZoomOut = await cdp.eval(`({ state: appState.chartCustomZoomCount, probe: ${CANDLE_PROBE} })`);
    check('REQ-022 缩小到上限后仍严格为 200 根，不得超出',
      afterZoomOut.probe.candles === 200 && afterZoomOut.state <= 200,
      `状态 ${afterZoomOut.state} / 实绘 ${afterZoomOut.probe.candles} 根`);

    // ---------- REQ-022：滚轮放大 → 根数减少，绘图区几何不变 ----------
    await cdp.eval(`(() => { const svg = document.getElementById('stockInteractiveSvg');
      for (let i = 0; i < 30; i++) svg.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true }));
      return appState.chartCustomZoomCount; })()`);
    await sleep(1200);
    const zoomedIn = await cdp.eval(`({ state: appState.chartCustomZoomCount, probe: ${CANDLE_PROBE} })`);
    check('REQ-022 放大只减少同一页面内的 K 线根数', zoomedIn.probe.candles < 200 && zoomedIn.probe.candles >= 5,
      `状态 ${zoomedIn.state} / 实绘 ${zoomedIn.probe.candles} 根`);
    check('REQ-022 缩放前后绘图区几何与 K 线宽度基准完全不变',
      zoomedIn.probe.plotLeft === fullPlot.left && zoomedIn.probe.plotWidth === fullPlot.width &&
      Math.abs(zoomedIn.probe.candleWidth - stdCandleWidth) < 1e-6,
      `绘图区 ${zoomedIn.probe.plotWidth} / 蜡烛宽 ${zoomedIn.probe.candleWidth}`);
    const shotZoom = await cdp.shot('02-zoom-same-page.png');

    // ---------- REQ-023：根数不足 200 时右侧留白 ----------
    await cdp.eval(`switchChartPeriod('kline60')`);
    await sleep(1200);
    const p60 = await cdp.eval(CANDLE_PROBE);
    const usedRatio = (p60.lastRight - p60.plotLeft) / p60.plotWidth;
    check('REQ-023 60 根时右侧必须留白（占用宽度远小于绘图区）', usedRatio < 0.45 && usedRatio > 0.2,
      `占用 ${(usedRatio * 100).toFixed(1)}% / 实绘 ${p60.candles} 根`);
    check('REQ-023 根数不足 200 时单根宽度仍取标准槽宽（不得拉伸拉宽）',
      Math.abs(p60.candleWidth - stdCandleWidth) < 1e-6,
      `60 根蜡烛宽 ${p60.candleWidth} vs 200 根蜡烛宽 ${stdCandleWidth}`);
    check('REQ-023 K 线必须自绘图区左缘起排（右侧留白，不得居中铺满）',
      Math.abs(p60.firstLeft - p60.plotLeft) < 3,
      `首根左缘 ${p60.firstLeft.toFixed(1)} / 绘图区左缘 ${p60.plotLeft}`);
    const shotPad = await cdp.shot('03-right-padding-60-bars.png');

    // ---------- REQ-025：日线缺成交额时按「均价×成交量」兜底生成自动线 ----------
    await cdp.eval(`switchChartPeriod('all')`);
    await sleep(800);
    const sourceAmountMissing = await cdp.eval(`(() => {
      const bars = appState.activeDetailStock.daily_bars.slice(-200);
      return { total: bars.length, missingAmount: bars.filter(b => b.amount_yi == null).length };
    })()`);
    await cdp.eval(`setAutoLinesCount(2)`);
    await sleep(2500);
    const autoProbe = await cdp.eval(`(() => {
      const lines = appState.lineLayers.auto.lines;
      return {
        count: lines.length,
        blocked: appState.autoLinesBlockedReason,
        labels: lines.map(l => l.price),
        derivedBars: appState.activeDetailStock.daily_bars.slice(-200)
          .filter(b => resolveKlineAmount(b).derived).length,
        totalBars: 200
      };
    })()`);
    check('REQ-025 日线来源未提供成交额（旧口径下无法画线）',
      sourceAmountMissing.missingAmount > 0,
      `${sourceAmountMissing.missingAmount}/${sourceAmountMissing.total} 根缺成交额`);
    check('REQ-025 兜底后自动多阶线可正常生成（旧断言按新口径修订）',
      autoProbe.count > 0 && !autoProbe.blocked,
      `已绘制 ${autoProbe.count} 根 / 阻断原因 ${autoProbe.blocked || '无'}`);
    check('REQ-025 兜底数据被标记为估算口径（不与真实值混淆）',
      autoProbe.derivedBars === autoProbe.totalBars,
      `估算 ${autoProbe.derivedBars}/${autoProbe.totalBars} 根`);
    const estNote = await cdp.eval(`(() => { const svg = document.getElementById('stockInteractiveSvg');
      const text = svg ? svg.textContent.replace(/\\s+/g, ' ') : '';
      return {
        subplot: appState.chartSubplot,
        title: text.includes('含估算：均价×成交量'),
        legendAmount: text.includes('根成交额为估算（均价 × 成交量）'),
        legendVolume: text.includes('根按（均价 × 成交量）估算'),
        hasAny: text.includes('估算')
      }; })()`);
    check('REQ-025 副图/主图必须显式标注估算口径与估算根数（副图切为成交量时同样可见）',
      estNote.hasAny === true && (estNote.legendAmount || estNote.legendVolume),
      `副图=${estNote.subplot} / 成交额副图标注=${estNote.legendAmount} / 成交量副图标注=${estNote.legendVolume}`);
    const shotAuto = await cdp.shot('04-auto-lines-with-derived-amount.png');

    // ---------- REQ-026：交易面积 = 首个交汇日至今剔除自身交汇日 ----------
    const areaProbe = await cdp.eval(`(() => {
      const lines = appState.lineLayers.auto.lines;
      const bars = appState.activeDetailStock.daily_bars.map(withResolvedAmount);
      return lines.map(l => {
        const anchor = findFirstCrossIndex(bars, l.price);
        const manual = computeTradeArea(bars, l.price, anchor);
        return {
          price: l.price,
          label: formatTradeArea({ tradeAreaYi: l.tradeAreaYi, countedDays: l.tradeAreaDays, excludedDays: l.tradeAreaExcludedDays, incomplete: l.tradeAreaIncomplete }),
          rendered: l.tradeAreaYi,
          manual: manual.tradeAreaYi,
          anchor: anchor,
          anchorDate: anchor >= 0 ? bars[anchor].date : null,
          excludedDays: l.tradeAreaExcludedDays,
          countedDays: l.tradeAreaDays,
          labelInSvg: (document.getElementById('stockInteractiveSvg')||{textContent:''}).textContent.includes('交易面积')
        };
      });
    })()`);
    const areaOk = areaProbe.length > 0 && areaProbe.every(a => Math.abs(a.rendered - a.manual) < 0.01);
    check('REQ-026 交易面积与「首个交汇日→今天剔除自身交汇日」手算一致', areaOk,
      areaProbe.map(a => `¥${a.price}: ${a.rendered}亿 (锚点 ${a.anchorDate}, 剔除 ${a.excludedDays} 天, 计入 ${a.countedDays} 天)`).join(' ｜ ').slice(0, 220));
    check('REQ-026 图内标签已呈现交易面积', areaProbe.length > 0 && areaProbe[0].labelInSvg === true, areaProbe[0] ? areaProbe[0].label : '无');

    // 缩放窗口不改变交易面积（累计口径铁律）
    const beforeZoom = areaProbe.map(a => a.rendered);
    await cdp.eval(`(() => { const svg = document.getElementById('stockInteractiveSvg');
      for (let i = 0; i < 60; i++) svg.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true })); })()`);
    await sleep(1500);
    const afterZoomArea = await cdp.eval(`appState.lineLayers.auto.lines.map(l => ({ price: l.price, area: l.tradeAreaYi }))`);
    const zoomStable = afterZoomArea.length === beforeZoom.length &&
      afterZoomArea.every((l, i) => Math.abs((l.area ?? -1) - (beforeZoom[i] ?? -2)) < 0.01);
    check('REQ-026 缩放窗口改变后交易面积数值保持不变（累计口径铁律）', zoomStable,
      `缩放后 ${JSON.stringify(afterZoomArea.map(l => l.area))} / 缩放前 ${JSON.stringify(beforeZoom)}`);

    // ---------- REQ-026：「!」指标说明按钮与弹窗内容 ----------
    const helpBtn = await cdp.eval(`(() => {
      const btn = document.getElementById('btnLineMetricHelp');
      if (!btn) return null;
      btn.click();
      const modal = document.getElementById('lineMetricHelpModal');
      const text = modal ? modal.textContent.replace(/\\s+/g, ' ') : '';
      const style = modal ? getComputedStyle(modal) : null;
      return {
        exists: true, text: text, display: style ? style.display : null,
        hasFormula: text.includes('S_area(P)') && text.includes('d_first'),
        hasRules: text.includes('不受当前缩放窗口影响') && text.includes('剔除该线自身交汇的交易日') && text.includes('覆盖不完整'),
        hasFallback: text.includes('当日均价 × 当日成交量') && text.includes('（估算：均价×成交量）'),
        hasNoDataRule: text.includes('不会显示 0 根、0 元或任何推测数值')
      };
    })()`);
    check('REQ-026 图层面板标题旁存在「!」指标说明按钮且可打开弹窗',
      !!helpBtn && helpBtn.exists && helpBtn.display === 'flex', helpBtn ? `display=${helpBtn.display}` : '未找到按钮');
    check('REQ-026 弹窗含交易面积公式与三条口径铁律', !!helpBtn && helpBtn.hasFormula && helpBtn.hasRules,
      `公式=${helpBtn?.hasFormula} / 铁律=${helpBtn?.hasRules}`);
    check('REQ-026 弹窗含成交额兜底口径与估算标记说明', !!helpBtn && helpBtn.hasFallback, `兜底=${helpBtn?.hasFallback}`);
    check('REQ-026 弹窗含数据不足时的展示规则', !!helpBtn && helpBtn.hasNoDataRule, `规则=${helpBtn?.hasNoDataRule}`);
    const shotHelp = await cdp.shot('05-metric-help-modal.png');
    await cdp.eval(`closeLineMetricHelp()`);

    // 图层面板上的交易面积摘要（与图内标签同源）
    const panelMetric = await cdp.eval(`(() => { const p = document.getElementById('chartLayerPanel');
      return p ? p.textContent.replace(/\\s+/g, ' ').trim() : ''; })()`);
    check('REQ-026 图层管理面板同步呈现交易面积（同源口径）',
      /交易面积:/.test(panelMetric) && /交汇/.test(panelMetric), panelMetric.slice(0, 200));

    // ---------- REQ-024：分时图自动画线与缠论画线 ----------
    await cdp.eval(`switchChartPeriod('timeline')`);
    await sleep(3000);
    const tlProbe = await cdp.eval(`(() => {
      const s = appState.activeDetailStock;
      const analysis = s.intraday_chanlun || null;
      const svg = document.getElementById('stockInteractiveSvg');
      return {
        items: ((s.timeline_data||{}).items||[]).length,
        chanlunStatus: analysis ? analysis.status : 'none',
        chanlunLevel: analysis ? analysis.level : null,
        chanlunCounts: analysis ? analysis.counts : null,
        levelNote: svg ? svg.textContent.includes('缠论（分时级别') : false
      };
    })()`);
    check('REQ-024 分时明细可用', tlProbe.items > 0, `${tlProbe.items} 个分钟点`);
    check('REQ-024 分时缠论由同一套算法产出且级别标注为分时级别',
      tlProbe.chanlunStatus === 'available' && tlProbe.chanlunLevel === 'intraday',
      `status=${tlProbe.chanlunStatus} / level=${tlProbe.chanlunLevel} / counts=${JSON.stringify(tlProbe.chanlunCounts)}`);

    await cdp.eval(`if (!appState.showChanlunDraw) toggleChanlunDraw(); setAutoLinesCount(2)`);
    await sleep(2500);
    const tlDraw = await cdp.eval(`(() => {
      const svg = document.getElementById('stockInteractiveSvg');
      const text = svg ? svg.textContent : '';
      // 笔本身即以 <line class="chanlun-pens"> 渲染，中枢为 <g class="chanlun-pivots">
      const pens = svg ? svg.querySelectorAll('.chanlun-pens').length : 0;
      const pivots = svg ? svg.querySelectorAll('.chanlun-pivots').length : 0;
      const lines = appState.lineLayers.auto.lines;
      const analysis = appState.activeDetailStock.intraday_chanlun || {};
      const first = ((analysis.dates||[])[0]) || null;
      const last = ((analysis.dates||[]).slice(-1)[0]) || null;
      return {
        pens: pens, pivots: pivots,
        pensTotal: (analysis.pens||[]).length,
        pivotsTotal: (analysis.pivots||[]).length,
        firstDate: first, lastDate: last,
        firstPen: (analysis.pens||[])[0] || null,
        overlayPresent: !!svg.querySelector('.chanlun-overlay-layer'),
        drawOn: appState.showChanlunDraw,
        layers: JSON.stringify(appState.chanlunLayers),
        autoLines: lines.length,
        blocked: appState.autoLinesBlockedReason,
        autoWithArea: lines.filter(l => l.tradeAreaYi !== undefined && l.tradeAreaYi !== null).length,
        levelLabel: text.includes('缠论（分时级别')
      };
    })()`);
    check('REQ-024 分时图可绘制缠论笔与笔中枢图层', tlDraw.pens > 0 && tlDraw.pivots > 0,
      `笔 ${tlDraw.pens}/${tlDraw.pensTotal} / 笔中枢 ${tlDraw.pivots}/${tlDraw.pivotsTotal}` +
      ` [窗口 ${tlDraw.firstDate}→${tlDraw.lastDate} / overlay=${tlDraw.overlayPresent} / draw=${tlDraw.drawOn} / ${tlDraw.layers}` +
      ` / 首笔 ${JSON.stringify(tlDraw.firstPen)}]`);
    check('REQ-024 分时图可生成自动画压力/支撑线', tlDraw.autoLines > 0 && !tlDraw.blocked,
      `自动线 ${tlDraw.autoLines} 根 / 阻断 ${tlDraw.blocked || '无'}`);
    check('REQ-024 分时缠论级别标签在图内显式呈现', tlDraw.levelLabel === true, `标签存在=${tlDraw.levelLabel}`);
    check('REQ-026 分时自动线同样带交易面积指标', tlDraw.autoWithArea === tlDraw.autoLines,
      `${tlDraw.autoWithArea}/${tlDraw.autoLines} 根带交易面积`);
    const shotTimeline = await cdp.shot('06-timeline-chanlun-and-autolines.png');

    // ---------- 控制台错误 ----------
    check('页面控制台无未预期错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));

    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify({
      base: BASE, generated_at: new Date().toISOString(), checks: results,
      screenshots: [shot200, shotZoom, shotPad, shotAuto, shotHelp, shotTimeline].map(f => path.basename(f)),
      console_errors: consoleErrors
    }, null, 2), 'utf8');

    const failed = results.filter(r => !r.ok);
    console.log(`\n${failed.length === 0 ? 'ALL PASS' : 'FAILED: ' + failed.length} — 共 ${results.length} 项浏览器验证`);
    process.exitCode = failed.length === 0 ? 0 : 1;
  } catch (err) {
    console.error('浏览器验证异常:', err.message);
    process.exitCode = 1;
  } finally {
    try { cdp?.ws.close(); } catch (_) {}
    chrome.kill('SIGKILL');
  }
})();
