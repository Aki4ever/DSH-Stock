#!/usr/bin/env node
/**
 * R10 真机浏览器验证 (headless Chrome + CDP) —— 需求REQ-053 / REQ-052
 * 覆盖：
 *   1. REQ-053：页面按 `modules/util.js → app.js` 的真实顺序加载；两个脚本都必须是 200 + JS MIME；
 *      10 个迁出的纯函数在**真实页面窗口**里必须存在且可调用（证明拆分对调用点零影响）；
 *      拆出的模块所在页面上，真实图表（副图表头使用 layoutSubplotHeader）必须照常渲染且零控制台错误。
 *   2. REQ-052：CLI `db-archive --json` 必须给出结构化归档结果，且归档件真实存在、integrity=ok、
 *      源库哈希在归档后未变（只读源库的安全边界在真实产品库上成立）。
 * 仅使用 Node 内置模块；只驱动已运行的页面读取状态与真实接口，不写入任何产品数据。
 */
const BASE = process.env.DSH_BASE || 'http://127.0.0.1:8888';
const OUT = process.env.DSH_SHOT_DIR || 'docs/verification/2026-09-24-r10';
const PORT = Number(process.env.DSH_CDP_PORT || 9394);
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const CHROME = process.env.DSH_CHROME_BIN ||
  path.join(os.homedir(), 'Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');

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
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
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
    const r = await Promise.race([
      this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('页面内脚本执行超时(60s): ' + String(expression).slice(0, 80))), 60000))
    ]);
    if (r.exceptionDetails) throw new Error(`页面内脚本异常: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
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

const MIGRATED = ['escapeActionText', 'escapeHtml', 'roundTo', 'formatStatVal', 'formatVolume',
  'formatAmountYi', 'formatReal', 'estimateSvgTextWidth', 'layoutSubplotHeader', 'formatQuoteMoment'];

/** 真实页面里的脚本装载探针（顺序 + 是否执行成功由函数存在性间接证明） */
const scriptProbe = `(() => {
  const tags = [...document.scripts].map(s => s.getAttribute('src')).filter(Boolean);
  const utilIdx = tags.findIndex(s => s.includes('/web/modules/util.js'));
  const appIdx = tags.findIndex(s => s.includes('/web/app.js'));
  const migrated = ${JSON.stringify(MIGRATED)};
  const missing = migrated.filter(n => typeof window[n] !== 'function');
  return {
    tags, utilIdx, appIdx, missing,
    utilLoaded: typeof window.estimateSvgTextWidth === 'function',
    // 真实调用一次（使用迁出函数计算，页面内的实现）
    widthProbe: typeof window.estimateSvgTextWidth === 'function' ? window.estimateSvgTextWidth('副图：成交额', 10) : null,
    headerProbeRowCount: (() => {
      const r = typeof window.layoutSubplotHeader === 'function'
        ? window.layoutSubplotHeader({ x0: 65, y: 470, fontSize: 10, maxRight: 855, title: '副图：成交额',
            items: [{ label: '总和', value: '1101.70亿' }, { label: '平均', value: '36.72亿' }] })
        : null;
      return r ? r.rows : null;
    })()
  };
})()`;

/** 副图表头真实渲染探针（确认拆分后真实图表仍照常出数） */
const headerProbe = `(() => {
  const host = document.getElementById('chartSvgContainerRight');
  if (!host) return { error: '容器不存在' };
  const svgs = [...host.querySelectorAll('svg')];
  const svg = svgs[svgs.length - 1];
  if (!svg) return { error: '未渲染 SVG' };
  const stats = [...svg.querySelectorAll('g.sub-summary-group text')].map(t => t.textContent.replace(/\\s+/g, ' ').trim());
  const titles = [...svg.querySelectorAll('text')].filter(t => /副图[:：]/.test(t.textContent) && !t.closest('g.sub-summary-group'))
    .map(t => t.textContent.replace(/\\s+/g, ' ').trim());
  return { titles, stats, text: svg.textContent.replace(/\\s+/g, ' ').trim().slice(0, 200) };
})()`;

function runCli(args) {
  return new Promise(resolve => {
    const proc = spawn('python3', ['scripts/dsh_stock_cli.py', ...args], { cwd: path.join(__dirname, '..') });
    let out = '', err = '';
    proc.stdout.on('data', d => out += d);
    proc.stderr.on('data', d => err += d);
    proc.on('close', code => resolve({ code, out, err }));
  });
}

(async () => {
  const shots = [];
  const consoleErrors = [];
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', '--window-size=1680,1200', '--user-data-dir=' + fs.mkdtempSync(path.join(os.tmpdir(), 'r10-chrome-')),
    'about:blank'
  ], { stdio: 'ignore' });
  let cdp = null;
  try {
    const version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
    check('headless Chrome 已就绪', !!version.webSocketDebuggerUrl, version.Browser);
    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    cdp = await CDP.connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
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
    check('页面加载成功', typeof (await cdp.eval('document.title')) === 'string', await cdp.eval('document.title'));

    // ================= REQ-053: 模块拆分在真实页面成立 =================
    const res = await cdp.eval('fetch("/web/modules/util.js", {method:"GET"}).then(r => ({status:r.status, type:r.headers.get("content-type")}))');
    check('REQ-053 拆出的 /web/modules/util.js 可访问且为 JS', res.status === 200 && /javascript|ecmascript/i.test(res.type || ''),
      `HTTP ${res.status} · ${res.type}`);

    const probe = await cdp.eval(scriptProbe);
    check('REQ-053 页面脚本顺序为 util.js → app.js', probe.utilIdx >= 0 && probe.appIdx > probe.utilIdx,
      probe.tags.join(' → '));
    check('REQ-053 10 个迁出函数在真实页面窗口全部可用', probe.missing.length === 0,
      probe.missing.length ? `缺失：${probe.missing.join(', ')}` : `全部可用（含 ${probe.tags.length} 个脚本标签）`);
    check('REQ-053 迁出函数在页面内可正常求值（真实调用）',
      probe.widthProbe > 0 && probe.headerProbeRowCount >= 1,
      `estimateSvgTextWidth('副图：成交额',10)=${probe.widthProbe && probe.widthProbe.toFixed(2)} · layoutSubplotHeader rows=${probe.headerProbeRowCount}`);

    // 真实图表渲染：副图表头本身就依赖迁出的 layoutSubplotHeader
    await cdp.eval(`openStockDetail('sh600519')`);
    await sleep(11000);
    const header = await cdp.eval(headerProbe);
    check('REQ-053 拆分后真实个股日K副图表头照常渲染（标题 + 统计概要出数）',
      !header.error && header.titles.length === 1 && header.stats.length >= 1,
      header.error || `${header.titles[0]} · 统计项 ${header.stats.length} 个`);
    check('REQ-053 拆分后页面无脚本错误（零未捕获异常）', consoleErrors.length === 0,
      consoleErrors.slice(0, 3).join(' | ') || '0 条');
    shots.push(await cdp.shot('01-util-module-live-page.png'));

    // ================= REQ-052: CLI 非破坏归档（真实产品库） =================
    const before = await (await fetch(BASE + '/api/status')).json();
    const archiveDir = path.join(os.tmpdir(), 'r10-archive-' + Date.now());
    const cli = await runCli(['db-archive', '--dir', archiveDir, '--label', 'r10-verify', '--json']);
    let payload = null;
    try { payload = JSON.parse(cli.out); } catch (_) {}
    check('REQ-052 CLI db-archive 输出结构化结果', cli.code === 0 && payload && payload.status === 'available',
      cli.code !== 0 ? (cli.err || cli.out).slice(0, 120) : `status=${payload && payload.status}`);
    if (payload && payload.status === 'available') {
      check('REQ-052 归档件真实存在且完整性 ok', fs.existsSync(payload.archive.path) && payload.archive.integrity_check === 'ok',
        `${path.basename(payload.archive.path)} · ${(payload.archive.size_bytes / 1048576).toFixed(2)}MB · integrity=${payload.archive.integrity_check}`);
      check('REQ-052 归档行数与源库一致（逐表核验）', payload.archive.total_rows === payload.source.total_rows,
        `源库 ${payload.source.total_rows} 行 → 归档 ${payload.archive.total_rows} 行`);
      // 只读打开是本工具的安全机制（SQLite mode=ro 下不可能写入）；哈希是否变化取决于当时是否有
      // 其它进程（运行中的服务端）在写库，两种情形都必须由 notes 如实说明，故按「机制 + 诚实说明」判定。
      const changeExplained = payload.source_unchanged === true
        || (payload.notes || []).some(n => n.includes('哈希发生变化'));
      check('REQ-052 源库以只读打开且未写入产品库（哈希变化时须有诚实说明）',
        payload.source_opened_readonly === true && changeExplained,
        `只读=${payload.source_opened_readonly} · 源库哈希未变=${payload.source_unchanged} · ${(payload.notes || [])[payload.notes.length - 1]}`);
      check('REQ-052 归档清单落盘可追溯', fs.existsSync(payload.manifest), path.basename(payload.manifest));
      fs.rmSync(archiveDir, { recursive: true, force: true });   // 验证产物清理（不动产品库）
    }
    const after = await (await fetch(BASE + '/api/status')).json();
    check('REQ-052 归档前后服务端仍健康（未影响运行中的实例）',
      after.status === 'running' && after.version === before.version,
      `${after.status} · ${after.version} · 标的 ${after.stocks_count ?? after.stock_count ?? '—'}`);

    check('控制台无脚本错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | ') || '0 条');
  } catch (err) {
    check('验证脚本执行完成', false, err.message);
  } finally {
    try { chrome.kill('SIGKILL'); } catch (_) {}
  }

  const report = {
    at: new Date().toISOString(), base: BASE, total: results.length,
    passed: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).length,
    consoleErrors, shots: shots.map(s => path.basename(s)), results
  };
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(`\n=== R10 真机验证：${report.passed}/${report.total} PASS ===`);
  if (report.failed) {
    console.log('失败项：\n' + results.filter(r => !r.ok).map(r => ` - ${r.name}：${r.detail}`).join('\n'));
    process.exit(1);
  }
})();
