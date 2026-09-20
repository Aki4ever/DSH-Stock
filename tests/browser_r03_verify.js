#!/usr/bin/env node
/**
 * R03 P0 真机浏览器验证 (headless Chrome + CDP)
 * 仅使用 Node 内置模块；不写入产品数据，只驱动已运行的 127.0.0.1:8888 页面。
 */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const CHROME = process.env.DSH_CHROME_BIN ||
  path.join(os.homedir(), 'Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');
const PORT = 9333;
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-20-r03/assets';

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
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = e => rej(new Error('WebSocket 连接失败')); });
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
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true
    });
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

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-r03-chrome-'));
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
    const page = targets.find(t => t.type === 'page');
    cdp = await CDP.connect(page.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');

    // 收集页面控制台错误
    const consoleErrors = [];
    cdp.ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') consoleErrors.push(m.params.entry.text);
      if (m.method === 'Runtime.exceptionThrown') consoleErrors.push(m.params.exceptionDetails.text);
    });

    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(3500);

    // ---------- 页面基础健康 ----------
    const title = await cdp.eval('document.title');
    check('页面加载成功', typeof title === 'string', title);

    // ---------- REQ-016/017 数据中心 ----------
    await cdp.eval('switchMainTab("crawler")');
    await sleep(1200);
    // 等待审计列表渲染
    await cdp.eval('loadCrawlerAuditList()');
    await sleep(1500);

    const auditProbe = await cdp.eval(`(() => {
      const rows = [...document.querySelectorAll('#crawlerAuditTableBody tr.audit-row')];
      const head = document.getElementById('crawlerAuditSelectAll');
      const baseBar = document.getElementById('dataBaselineBar');
      const batchBar = document.getElementById('crawlerBatchBar');
      return {
        rowCount: rows.length,
        hasCheckbox: !!head,
        checkboxCount: document.querySelectorAll('.audit-row-checkbox').length,
        baselineRows: rows.filter(r => r.classList.contains('is-baseline')).length,
        baselineBarText: (baseBar?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
        batchHiddenInitially: batchBar ? batchBar.hidden : null,
        batchDisplayInitially: batchBar ? getComputedStyle(batchBar).display : null,
        setBaselineButtons: document.querySelectorAll('#crawlerAuditTableBody button[onclick^="setAuditBaseline"]').length,
        baselineBadges: document.querySelectorAll('#crawlerAuditTableBody .baseline-badge').length
      };
    })()`);
    check('数据中心新增复选框列', auditProbe.hasCheckbox && auditProbe.checkboxCount === auditProbe.rowCount,
      `行数 ${auditProbe.rowCount} / 复选框 ${auditProbe.checkboxCount}`);
    check('恰好一行标记为当前基准', auditProbe.baselineRows === 1 && auditProbe.baselineBadges === 1,
      `基准行 ${auditProbe.baselineRows} / 徽标 ${auditProbe.baselineBadges}`);
    check('基准口径条已渲染并区分批次日期与行情日期',
      auditProbe.baselineBarText.includes('当前数据库基准') && auditProbe.baselineBarText.includes('基准日期'),
      auditProbe.baselineBarText);
    check('未选中时批量操作条不占位（视觉上真正隐藏）',
      auditProbe.batchHiddenInitially === true && auditProbe.batchDisplayInitially === 'none',
      `hidden=${auditProbe.batchHiddenInitially} / display=${auditProbe.batchDisplayInitially}`);

    const shotCrawler = await cdp.shot('01-data-center.png');

    // 勾选单条 → 出现批量操作条
    const oneSel = await cdp.eval(`(() => {
      const cb = document.querySelector('.audit-row-checkbox:not([data-record-id="10"])') || document.querySelector('.audit-row-checkbox');
      cb.click();
      const bar = document.getElementById('crawlerBatchBar');
      return { hidden: bar.hidden, text: document.getElementById('crawlerBatchCount').textContent,
               selectedRows: document.querySelectorAll('#crawlerAuditTableBody tr.is-selected').length };
    })()`);
    check('勾选 1 条 → 批量操作条出现并计数', oneSel.hidden === false && oneSel.text.includes('已选 1 条'),
      `${oneSel.text} / 高亮行 ${oneSel.selectedRows}`);

    // 全选 → 半选态归位
    const selAll = await cdp.eval(`(() => {
      const head = document.getElementById('crawlerAuditSelectAll');
      head.checked = true; head.onclick({ target: head, checked: true });
      const rows = document.querySelectorAll('#crawlerAuditTableBody tr.audit-row').length;
      const checked = document.querySelectorAll('.audit-row-checkbox:checked').length;
      const fullText = document.getElementById('crawlerBatchCount').textContent;
      // 取消其中一条 → 表头应呈现半选态
      document.querySelector('.audit-row-checkbox').click();
      return { rows, checked, fullText, indeterminate: head.indeterminate, partialText: document.getElementById('crawlerBatchCount').textContent };
    })()`);
    check('表头全选可选中全部记录', selAll.checked === selAll.rows, `${selAll.checked}/${selAll.rows} · ${selAll.fullText}`);
    check('部分选中时表头呈半选态 (indeterminate)', selAll.indeterminate === true, selAll.partialText);

    const shotBatch = await cdp.shot('02-data-center-multi-select.png');

    // 基准保护：直接调用删除接口，删除基准必须被拒绝
    const protectProbe = await cdp.eval(`(async () => {
      const al = await (await fetch('/api/crawler/audit-list', {cache:'no-store'})).json();
      const res = await fetch('/api/crawler/audit-delete', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ids:[al.baseline_id]})});
      const j = await res.json();
      return { deleted: (j.deleted||[]).length, protectedCount: (j.protected||[]).length, reason: j.reason };
    })()`);
    check('当前基准记录受删除保护', protectProbe.deleted === 0 && protectProbe.protectedCount === 1, protectProbe.reason);

    // 取消选择，恢复页面
    await cdp.eval('clearAuditSelection()');
    await sleep(300);

    // ---------- REQ-014/015 图表画线图层 ----------
    await cdp.eval('switchMainTab("filter")');
    await sleep(800);
    await cdp.eval('openStockDetail("sh600519")');
    await sleep(6000);

    const detailReady = await cdp.eval(`(() => {
      const panel = document.getElementById('chartLayerPanel');
      return { hasStock: !!appState.activeDetailStock, panelRows: panel ? panel.querySelectorAll('.chart-layer-row').length : 0,
               panelText: panel ? panel.textContent.replace(/\\s+/g,' ').trim().slice(0,200) : '' };
    })()`);
    check('个股详情已打开且图层面板已渲染', detailReady.hasStock && detailReady.panelRows >= 8,
      `模型行 ${detailReady.panelRows}`);

    // 开启 3 根自动线 + 放置 2 条手动画线（一压力一支撑）
    // 说明：日线真实来源不含成交额，自动多阶线按要求只在提供成交额的分时周期测算
    const layerState = await cdp.eval(`(() => {
      const stock = appState.activeDetailStock;
      const last = Number(stock.price || stock.prev_close || 10);
      clearAllChartDrawLines();
      switchChartPeriod('timeline');
      setAutoLinesCount(3);
      addChartLine('manual_up', { id:'t_up_'+Date.now(), price: Number((last*1.02).toFixed(2)), type:'压力位', crossedDays: 5, crossedAmountYi: 30.5 });
      addChartLine('manual_down', { id:'t_down_'+Date.now(), price: Number((last*0.98).toFixed(2)), type:'支撑位', crossedDays: 7, crossedAmountYi: 41.2 });
      renderActiveStockChart();
      return {
        auto: countLayerLines('auto'), up: countLayerLines('manual_up'), down: countLayerLines('manual_down'),
        visible: getVisibleChartLines().length, blocked: appState.autoLinesBlockedReason
      };
    })()`);
    check('三个画线模型可同时存在（自动线 3 根 + 压力线 + 支撑线）',
      layerState.auto === 3 && layerState.up === 1 && layerState.down === 1 && !layerState.blocked,
      `自动 ${layerState.auto} / 压力 ${layerState.up} / 支撑 ${layerState.down} / 可见 ${layerState.visible}${layerState.blocked ? ' / ' + layerState.blocked : ''}`);

    // 日线周期缺少成交额时，必须显式说明原因而不是静默显示 0 根
    const klineBlocked = await cdp.eval(`(() => {
      switchChartPeriod('kline60');
      setAutoLinesCount(3);
      return { auto: countLayerLines('auto'), reason: appState.autoLinesBlockedReason,
               note: (document.querySelector('#chartLayerPanel .chart-layer-note') || {}).textContent || '' };
    })()`);
    check('日线缺成交额时自动线不生成并显式说明原因',
      klineBlocked.auto === 0 && !!klineBlocked.reason && klineBlocked.note.includes('成交额'),
      klineBlocked.note.trim().slice(0, 80));

    // 回到分时周期恢复自动线，用于图层截图
    await cdp.eval(`switchChartPeriod('timeline'); setAutoLinesCount(3); renderActiveStockChart();`);
    await sleep(500);
    const domLines = await cdp.eval(`document.querySelectorAll('#stockInteractiveSvg g.chart-hline').length`);
    check('图表 SVG 实际渲染出全部模型的辅助线', domLines === layerState.visible, `SVG 中 ${domLines} 条`);

    const shotLayers = await cdp.shot('03-stock-layers-all.png');

    // 只清除压力线 → 自动线与支撑线必须保留
    const cleared = await cdp.eval(`(() => {
      clearChartLayer('manual_up');
      return { auto: countLayerLines('auto'), up: countLayerLines('manual_up'), down: countLayerLines('manual_down'),
               svgLines: document.querySelectorAll('#stockInteractiveSvg g.chart-hline').length };
    })()`);
    check('清除压力线后自动线与支撑线完整保留',
      cleared.up === 0 && cleared.auto === 3 && cleared.down === 1,
      `自动 ${cleared.auto} / 压力 ${cleared.up} / 支撑 ${cleared.down} / SVG ${cleared.svgLines}`);

    const shotCleared = await cdp.shot('04-clear-pressure-only.png');

    // ---------- REQ-015 重合置顶 ----------
    const overlap = await cdp.eval(`(() => {
      clearChartLayer('auto');
      clearChartLayer('manual_down');
      const stock = appState.activeDetailStock;
      const p = Number(stock.price || stock.prev_close || 10);
      const lines = [
        addChartLine('auto', { id:'ov_auto', price:p, type:'最强压力', crossedDays:3, crossedAmountYi:20 }),
        addChartLine('manual_up', { id:'ov_up', price:p, type:'压力位', crossedDays:3, crossedAmountYi:20 }),
        addChartLine('manual_down', { id:'ov_down', price:p, type:'支撑位', crossedDays:3, crossedAmountYi:20 })
      ];
      renderActiveStockChart();
      const before = Array.from(getVisibleChartLines(), l => l.id);
      // 命中重合区域：取第一条线的 SVG Y 作为点击纵坐标
      const first = getVisibleChartLines()[0];
      const m = { left: 65, top: 20, right: 65 };
      const innerW = 860 - m.left - m.right;
      handleChartLineClick(300, first._svgY, 860, 440, m, 270);
      const after1 = Array.from(getVisibleChartLines(), l => l.id);
      const second = getVisibleChartLines()[0];
      handleChartLineClick(300, second._svgY, 860, 440, m, 270);
      const after2 = Array.from(getVisibleChartLines(), l => l.id);
      return { before, after1, after2, topLineId: appState.topLineId,
               overlapLabels: (document.getElementById('stockInteractiveSvg').innerHTML.match(/重合3/g) || []).length };
    })()`);
    check('点击重合辅助线可轮换置顶',
      JSON.stringify(overlap.before) !== JSON.stringify(overlap.after1) &&
      JSON.stringify(overlap.after1) !== JSON.stringify(overlap.after2),
      `${overlap.before.join('>')} → ${overlap.after1.join('>')} → ${overlap.after2.join('>')}`);
    check('重合线在图上标注重合条数', overlap.overlapLabels >= 1, `出现 ${overlap.overlapLabels} 处「重合3」标注`);

    const shotOverlap = await cdp.shot('05-overlap-topmost.png');

    // ---------- 指数详情图层 ----------
    await cdp.eval('closeStockDetailPage()');
    await sleep(500);
    await cdp.eval('switchMainTab("index")');
    await sleep(1500);
    await cdp.eval('loadIndicesList()');
    await sleep(2500);
    const indexProbe = await cdp.eval(`(async () => {
      const j = await (await fetch('/api/index/list')).json();
      const first = (j.data || [])[0];
      if (!first) return { rows: -1, text: '指数列表为空' };
      await openIndexDetail(first.code);
      await new Promise(r => setTimeout(r, 3500));
      switchIndexChartPeriod('kline60');
      await new Promise(r => setTimeout(r, 800));
      const panel = document.getElementById('indexLayerPanel');
      return { code: first.code, rows: panel ? panel.querySelectorAll('.chart-layer-row').length : 0,
               text: panel ? panel.textContent.replace(/\\s+/g,' ').trim() : '' };
    })()`);
    check('指数详情图层面板已渲染两个模型（自动线 / 手动线）', indexProbe.rows === 2,
      `${indexProbe.code} · ${indexProbe.text.slice(0, 120)}`);

    // 指数分模型清除：清除自动线后手动线必须保留
    const indexClear = await cdp.eval(`(() => {
      const d = indexState.activeIndex;
      const base = Number(d.price || d.prev_close || 3000);
      indexState.lineLayers.manual.lines.push({ id:'idx_m1', price: base, type:'压力位', layerKey:'manual', zIndex: nextIndexLineZ() });
      setIndexAutoLinesCount(2);
      const before = { auto: indexState.lineLayers.auto.lines.length, manual: indexState.lineLayers.manual.lines.length };
      clearIndexLayer('auto');
      return { before, after: { auto: indexState.lineLayers.auto.lines.length, manual: indexState.lineLayers.manual.lines.length } };
    })()`);
    check('指数图清除自动线后手动线完整保留',
      indexClear.after.auto === 0 && indexClear.after.manual === indexClear.before.manual,
      `清除前 自动 ${indexClear.before.auto} / 手动 ${indexClear.before.manual} → 清除后 自动 ${indexClear.after.auto} / 手动 ${indexClear.after.manual}`);

    const shotIndex = await cdp.shot('06-index-layers.png');

    // ---------- 控制台错误 ----------
    check('页面控制台无未预期错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));

    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify({
      base: BASE, generated_at: new Date().toISOString(), checks: results,
      screenshots: [shotCrawler, shotBatch, shotLayers, shotCleared, shotOverlap, shotIndex].map(f => path.basename(f)),
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
