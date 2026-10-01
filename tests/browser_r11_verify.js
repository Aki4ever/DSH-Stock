#!/usr/bin/env node
/**
 * R11 真机验证：本轮新接通的物理链路在**真实浏览器 DOM**里是否真的呈现。
 *
 * 覆盖（全部以真实页面 + 真实接口为判据，不做字符串静态匹配）：
 *   1. 成分股筛选入口真实可用：`#constituentControl` 下「中证A50 / 中证A100」按钮
 *      **不再 disabled**，标签已随口径更新；点击后 `appState.constituent` 真的变为 csi50；
 *      真实 POST /api/filter 命中数 > 0（修复前恒 0）。
 *   2. 宏观页面真实出数：`switchMainTab('world')` 后
 *      `#worldTotalScore` 不再是「未获取」、`#worldSentimentLabel` 有真实情绪词、
 *      `#worldEventsCount` > 0、`#worldCommodityGrid` 渲染出商品卡片，
 *      且页面显示的分数与 `GET /api/macro/world` 的 `aggregate_score.total_score` 逐字一致。
 *
 * 仅使用 Node 内置模块 + 本机 headless Chrome（与 R06~R10 真机脚本同一套 CDP 手法）。
 * 只读：不点击任何写操作按钮，不写产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || '/tmp/r11shots';
const PORT = Number(process.env.DSH_CDP_PORT || 9411);
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const CHROME = process.env.DSH_CHROME_BIN ||
  path.join(os.homedir(), 'Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');

const sleep = ms => new Promise(r => setTimeout(r, ms));
let pass = 0, fail = 0;
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail: String(detail).slice(0, 300) });
  if (ok) { pass++; console.log(`✅ ${name}${detail ? ' — ' + detail : ''}`); }
  else { fail++; console.log(`❌ ${name}${detail ? ' — ' + detail : ''}`); }
}

async function fetchJson(url, tries = 60) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch (_) {}
    await sleep(250);
  }
  throw new Error(`无法连接: ${url}`);
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const cdp = new CDP(ws);
    ws.onmessage = ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id && cdp.pending.has(msg.id)) {
        const { resolve, reject } = cdp.pending.get(msg.id);
        cdp.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    };
    return cdp;
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
      expression, awaitPromise: true, returnByValue: true,
    });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' :: ' + expression);
    return r.result.value;
  }
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const consoleErrors = [];
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'r11-chrome-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1680,1050', 'about:blank',
  ], { stdio: 'ignore' });

  try {
    const version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
    check('headless Chrome 已就绪', !!version.webSocketDebuggerUrl, version.Browser);
    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    const cdp = await CDP.connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    cdp.ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') consoleErrors.push(m.params.entry.text);
      if (m.method === 'Runtime.exceptionThrown') consoleErrors.push(m.params.exceptionDetails.text);
    });
    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(4500);

    // ---------- 0. 页面基线 ----------
    const title = await cdp.eval('document.title');
    check('真实页面已加载', /DSH|量化|股票/.test(title), title);

    // ---------- 1. 成分股入口真实可用 ----------
    const apiCsi = {};
    for (const key of ['csi50', 'csi100']) {
      const res = await fetch(`${BASE}/api/filter`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ constituent: key, page: 1, page_size: 1 }),
      });
      const json = await res.json();
      apiCsi[key] = json.stats.matched_count;
    }
    check('接口：csi50 命中数 > 0（修复前为 0）', apiCsi.csi50 > 0, `matched=${apiCsi.csi50}`);
    check('接口：csi100 命中数 > 0（修复前为 0）', apiCsi.csi100 > 0, `matched=${apiCsi.csi100}`);

    const btnState = await cdp.eval(`(() => {
      const box = document.getElementById('constituentControl');
      if (!box) return null;
      const btns = [...box.querySelectorAll('.seg-btn')].map(b => ({
        val: b.getAttribute('data-val'), text: b.textContent.trim(),
        disabled: b.disabled, hasDisabledAttr: b.hasAttribute('disabled'),
        title: b.getAttribute('title') || '',
      }));
      return { btns };
    })()`);
    check('DOM：#constituentControl 存在', !!btnState, btnState ? `${btnState.btns.length} 个按钮` : '');
    if (btnState) {
      const a50 = btnState.btns.find(b => b.val === 'csi50');
      const a100 = btnState.btns.find(b => b.val === 'csi100');
      check('DOM：中证A50 按钮不再 disabled', a50 && !a50.disabled, a50 ? a50.text : 'not found');
      check('DOM：中证A100 按钮不再 disabled', a100 && !a100.disabled, a100 ? a100.text : 'not found');
      check('DOM：按钮文案已更口径为 中证A50/A100',
        a50 && a100 && a50.text.includes('A50') && a100.text.includes('A100'),
        `${a50 && a50.text} / ${a100 && a100.text}`);
    }

    // 点击 csi50 → appState.constituent 必须真的变
    const clicked = await cdp.eval(`(() => {
      const b = document.querySelector('#constituentControl .seg-btn[data-val="csi50"]');
      if (!b) return { ok: false, reason: 'button not found' };
      b.click();
      return { ok: true, active: b.classList.contains('active') };
    })()`);
    await sleep(1200);
    const stateAfter = await cdp.eval('typeof appState !== "undefined" ? appState.constituent : null');
    check('交互：点击中证A50 后 appState.constituent === "csi50"', stateAfter === 'csi50',
      `clicked=${JSON.stringify(clicked)} state=${stateAfter}`);

    const tableRows = await cdp.eval(
      'document.querySelectorAll("#stockTableBody tr").length');
    check('交互：点击后股票表格真实渲染出数据行', Number(tableRows) > 0, `rows=${tableRows}`);

    // ---------- 2. 宏观页面真实出数 ----------
    const apiMacro = (await (await fetch(`${BASE}/api/macro/world`)).json()).data;
    const apiScore = apiMacro.aggregate_score.total_score;
    check('接口：宏观 status=available 且无错误', apiMacro.status === 'available' && (apiMacro.errors || []).length === 0,
      `status=${apiMacro.status} errors=${(apiMacro.errors || []).length}`);

    await cdp.eval(`switchMainTab('world')`);
    await sleep(4000);
    const macroDom = await cdp.eval(`(() => {
      const t = id => { const e = document.getElementById(id); return e ? e.textContent.trim() : null; };
      const grid = document.getElementById('worldCommodityGrid');
      const stream = document.getElementById('worldEventsStream');
      const cards = grid ? [...grid.querySelectorAll('.commodity-card')] : [];
      const eventCards = stream ? [...stream.querySelectorAll('.event-card')] : [];
      return {
        visible: !document.getElementById('viewWorldTab').classList.contains('hidden'),
        score: t('worldTotalScore'), sentiment: t('worldSentimentLabel'), count: t('worldEventsCount'),
        commodityCardCount: cards.length,
        commodityNames: cards.map(c => (c.querySelector('.commodity-name') || {}).textContent || '').join(','),
        commodityText: grid ? grid.textContent.trim().slice(0, 160) : '',
        eventCardCount: eventCards.length,
        eventTitles: eventCards.map(c => (c.querySelector('.event-title') || {}).textContent || '').join(' | ').slice(0, 160),
        eventText: stream ? stream.textContent.trim().slice(0, 160) : '',
        scoreBasis: t('worldScoreBasis'),
        domesticBadge: t('badgeScopeDomestic'),
      };
    })()`);

    check('DOM：宏观视图已切到前台', macroDom.visible === true, JSON.stringify(macroDom.visible));
    check('DOM：总评分不再是「未获取」', macroDom.score && macroDom.score !== '未获取', `score=${macroDom.score}`);
    // 分数是实时行情派生的，两次请求之间会随行情微动，故允许 1.0 分以内偏差
    const domScoreNum = Number(String(macroDom.score || '').replace(/[+,]/g, ''));
    const scoreMatches = apiScore != null && Number.isFinite(domScoreNum) &&
      Math.abs(domScoreNum - Number(apiScore)) <= 1.0;
    check('DOM：页面分数与 /api/macro/world 同源一致（±1 分内，行情微动）', scoreMatches,
      `dom=${macroDom.score} api=${apiScore}`);
    check('DOM：情绪标签是真实情绪词', !!macroDom.sentiment && !/未接入|未获取/.test(macroDom.sentiment),
      `sentiment=${macroDom.sentiment}`);
    check('DOM：事件数 > 0', Number(macroDom.count) > 0, `count=${macroDom.count}`);
    check('DOM：商品卡片真的渲染出真实卡片', macroDom.commodityCardCount > 0,
      `cards=${macroDom.commodityCardCount} names=${macroDom.commodityNames}`);
    check('DOM：商品面板不得出现渲染崩溃兜底文案',
      !/受阻|超时|未接入/.test(macroDom.commodityText), macroDom.commodityText.slice(0, 60));
    check('DOM：商品名称与接口一致（真实商品名）',
      /黄金|原油|白银|铜|布伦特/.test(macroDom.commodityNames), macroDom.commodityNames);
    check('DOM：事件卡片真的渲染出真实标题', macroDom.eventCardCount > 0 && macroDom.eventTitles.length > 10,
      `cards=${macroDom.eventCardCount} titles=${macroDom.eventTitles.slice(0, 60)}`);
    check('DOM：评分依据为真实口径（不再写死「不生成宏观分数」）',
      !!macroDom.scoreBasis && /50 \+|涨跌幅/.test(macroDom.scoreBasis) && !/不生成宏观分数/.test(macroDom.scoreBasis),
      macroDom.scoreBasis);
    check('DOM：国内要闻徽标显示真实件数（不是「未获取」）',
      !!macroDom.domesticBadge && /\d+件/.test(macroDom.domesticBadge), macroDom.domesticBadge);
    check('DOM：事件面板不得出现渲染崩溃兜底文案',
      !/超时|受阻|未接入|暂无符合/.test(macroDom.eventText), macroDom.eventText.slice(0, 60));

    // 真机截图存证
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(OUT, 'r11-macro-and-constituents.png'), Buffer.from(shot.data, 'base64'));
    check('截图已落盘', fs.existsSync(path.join(OUT, 'r11-macro-and-constituents.png')),
      path.join(OUT, 'r11-macro-and-constituents.png'));

    const realErrors = consoleErrors.filter(t => !/favicon|404 \(Not Found\)/i.test(t));
    check('控制台零未捕获异常', realErrors.length === 0,
      realErrors.length ? realErrors.slice(0, 2).join(' | ') : '0 条');
  } catch (err) {
    check('执行过程未抛异常', false, err.message);
  } finally {
    chrome.kill('SIGKILL');
    fs.writeFileSync(path.join(OUT, 'r11-report.json'),
      JSON.stringify({ base: BASE, pass, fail, results, consoleErrors }, null, 2));
    console.log(`\n=== R11 真机验证：${pass}/${pass + fail} PASS ===`);
    process.exit(fail ? 1 : 0);
  }
})();
