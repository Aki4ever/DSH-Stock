/**
 * 前端静态回归共用的「源码装载器」（需求REQ-053）
 *
 * 背景：v5.5.0 起 web/app.js 不再是唯一前端源码 —— 纯函数工具已拆到 web/modules/util.js，
 * 页面按 util.js → app.js 的顺序加载（两者都是经典脚本，函数声明共享同一个全局作用域）。
 * 因此静态套件必须按**与页面完全相同的顺序**拼接源码，否则沙箱里会缺函数、出现假失败。
 *
 * 用法：
 *   const { loadWebSource, loadIndexHtml, WEB_SOURCES } = require('./load_web_sources');
 *   const src = loadWebSource();          // 等价于页面加载的 JS 全量源码（utf8 字符串拼接）
 *   const html = loadIndexHtml();         // web/index.html 全文
 *
 * 约定：新增前端文件时，只需把它按加载顺序加入 WEB_SOURCES，全部套件自动同步。
 */
const fs = require('node:fs');
const path = require('node:path');

const WEB_ROOT = path.join(__dirname, '..', 'web');

/** 与 web/index.html 中 <script> 出现顺序严格一致的源码清单 */
const WEB_SOURCES = [
  'modules/util.js',
  'app.js',
];

/** 读取单个前端源码文件（路径相对 web/） */
function readWebFile(relPath) {
  const full = path.join(WEB_ROOT, relPath);
  if (!fs.existsSync(full)) {
    throw new Error(`前端源码缺失：${full}（若刚做过模块拆分，请同步更新 tests/load_web_sources.js 的 WEB_SOURCES）`);
  }
  return fs.readFileSync(full, 'utf8');
}

/** 按页面加载顺序拼接全部前端 JS 源码 */
function loadWebSource() {
  return WEB_SOURCES.map(readWebFile).join('\n;\n');
}

/** 读取 web/index.html（用于断言脚本顺序、DOM 结构等） */
function loadIndexHtml() {
  return readWebFile('index.html');
}

module.exports = { WEB_SOURCES, WEB_ROOT, readWebFile, loadWebSource, loadIndexHtml };
