# DSH股票 · 二次开发与优化指南（How-to）

> 面向：拿到工程后要继续加功能、改口径、修 bug 的人。
> 前置阅读：[`README.md`](README.md)（接手总览）、[`architecture-current.md`](architecture-current.md)（架构与契约）。
> 本工程的核心工作纪律只有两条：**数据必须真实可追溯**、**需求编号与测试断言双向同步**。

---

## 一、开工前的 60 秒自检

```sh
cd "/Users/linqiyu/Documents/DSH/DSH股票"
bash scripts/ensure_server.sh                       # 服务保活（幂等）
python3 -m unittest discover -s tests -p "test_*.py" | tail -3   # 期望 OK (228)
for f in tests/test_chart_integrity.js tests/test_detail_requests.js \
         tests/test_layer_interaction.js tests/test_r04_chart_viewport.js \
         tests/test_r08_chart.js; do node "$f" >/dev/null && echo "OK $f" || echo "FAIL $f"; done
node tests/browser_r08_verify.js | tail -5          # 真机（需服务在跑）
```

> 若 R06/R07 真机脚本报几何类失败，先看[第五节](#五旧批次真机探针的修复配方)：那是**探针硬编码**问题，不是画错了。

---

## 二、加一个新功能的标准流程

| 步 | 动作 | 产物 |
| :--- | :--- | :--- |
| 1 | 在 `docs/requirements.md` **先登记需求编号**（当前最大 REQ-045，下一个用 REQ-046） | 需求条目 + 原始需求原文 |
| 2 | 后端实现（引擎模块优先新增独立小文件，接入层改 `stock_web_server.py`） | 代码 + 接口 |
| 3 | 前端实现（`web/index.html` 结构 + `web/app.js` 逻辑 + `web/style.css` 样式） | 页面 |
| 4 | 写测试：Python 单测映射 REQ；前端加 JS 静态套件；交互/几何加真机脚本 | `tests/test_*.py`、`tests/test_*.js`、`tests/browser_*.js` |
| 5 | 跑全量门禁（Python + JS + 相关真机），截图/报告落 `docs/verification/<日期>-<批次>/` | 验证记录 + README |
| 6 | 升 `config/version.json`（版本号 + 交付说明），同步 `docs/requirements.md` 状态 | 版本记录 |
| 7 | 提交 Git（**建议一批一提交**，避免再次出现「工作树里躺着未登记的改动」） | commit |

---

## 三、配方：加一个 HTTP 接口

1. 在 `scripts/stock_web_server.py` 的 `do_GET`（或 `do_POST`）里加分支。现有风格是**长 if 链 + 前缀匹配**：

```python
if url_path == "/api/stock/<code>/my-feature":   # 或 url_path.endswith("/my-feature")
    ...
    self._send_json({"data": data, "status": "available"})   # 缺失时用 unavailable + error
    return
```

2. **缺失口径三选一，禁止用 0/空数组冒充有数据**：
   - `status: "available"`：来源已披露，字段齐全；
   - `status: "partial"`：部分覆盖，必须带 `coverage_start/coverage_end/count`；
   - `status: "unavailable"`：明确 `error` 文案（例如「来源未披露」）。
3. 前端在 `web/app.js` 里 `fetch('/api/...', {cache: 'no-store'})`，**详情类请求要带序号保护**（参考 `appState.detailRequestId`），返回代码与请求不一致必须拒绝渲染。
4. 补一条 Python 单测（用 `unittest` + 隔离临时库）与一条 JS/真机断言。

---

## 四、配方：加一个数据源或字段

1. 在 `scripts/data_sources/` 新建或扩展现有适配器，统一走 `safe_session.py` 的会话（UA、超时、节流）。
2. 结果写入 `verified_source_cache`（`verified_sources.cache_put(key, payload)`），**必须带来源名与抓取时间**。
3. 落库走 `scripts/stock_db.py`，不要自己 `sqlite3.connect`。
4. 加"新鲜度"判断：旧数据要能识别为 `stale`，并如实显示（参考 `docs/requirements.md` 的「数据新鲜度口径补充」）。
5. 测试里禁止真连外网：用 `unittest.mock` 打桩 transport（参考 `tests/test_verified_market_data.py`）。

---

## 五、旧批次真机探针的修复配方（**已于 2026-09-24 实施完毕**）

> **状态**：本节配方已全部落地 —— `browser_r06_verify.js` **39/39 PASS**、`browser_r07_verify.js` **44/44 PASS**、`browser_r08_verify.js` 仍 **40/40 PASS**。以下保留为「为什么要这样改」的记录与后续同类问题的处理模板。

**背景**：未提交的 WIP 把 K 线画布从 860 宽改成 920（绘图区 65~855），并把左右副图控件合并为 `#chartSubPlotControlUnified`，同时按产品需求**移除了滚轮缩放**（改为浮动 ➕/➖ 按钮）。R06/R07 脚本把旧几何、旧控件 id、旧交互入口写在探针里，因此报红。**修法是把探针从"硬编码"改成"实测"、把交互换成"真实入口"，而不是把断言删掉**。

### 1. R06：绘图区几何（影响 10 项）

`tests/browser_r06_verify.js` 的 `panelProbe(slot)` 里：

```js
// 旧：靠固定宽度找网格矩形
const grid = rects.find(r => r.getAttribute('width') === '730');
...
plotLeft: grid ? parseFloat(grid.getAttribute('x')) : null,
plotWidth: grid ? parseFloat(grid.getAttribute('width')) : null,
```

改为**先量画布与边距、再算绘图区**（同时修掉"把网格矩形当成第 31 根蜡烛"的计数污染）：

```js
const vb = (svg.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);  // [0,0,W,H]
const MARGIN = { left: 65, right: 65 };                                      // 与 app.js 保持一致
const plotLeft = MARGIN.left;
const plotWidth = (vb[2] || 0) - MARGIN.left - MARGIN.right;
// 蜡烛计数必须排除网格矩形本身
const bodies = rects.filter(r => r.getAttribute('opacity') === null
  && r.getAttribute('fill') !== 'none' && r.getAttribute('fill') !== '#0f172a'
  && !r.getAttribute('stroke')
  && Math.abs(parseFloat(r.getAttribute('width')) - plotWidth) > 0.5);
```

REQ-036 的重合图断言同理：把 `plotRight: 65 + 730` 换成 `plotLeft + plotWidth`（实测折线 65~855 正好铺满新绘图区，行为本身是对的）。

### 2. R07：副图控件 id（影响 6 项）

`tests/browser_r07_verify.js` 的 `subplotProbe(slot, ctrlId)` 现在查 `#chartSubPlotControlRight` / `#chartSubPlotControlLeft`（已不存在），返回 `active: null`。

改为查询统一控件里当前生效的档位：

```js
const ctrl = document.getElementById('chartSubPlotControlUnified');
const active = ctrl && ctrl.querySelector('.seg-btn.active');
// 若将来恢复"按面板独立档位"，则改为读取该面板对应的控件容器
```

> 判定依据：同页面 `副图：成交额（含估算：均价×成交量）`、`副图：成交量` 文案已证明档位切换正确，仅探针取不到按钮。

### 3. 修完的自检（本轮实测结果）

```sh
node tests/browser_r06_verify.js | tail -3   # 39/39 PASS
node tests/browser_r07_verify.js | tail -3   # 44/44 PASS
node tests/browser_r08_verify.js | tail -3   # 40/40 PASS（未受影响）
node tests/browser_r09_verify.js | tail -3   # 28/28 PASS
```

**本轮实际改动**（可对照 diff）：R06 的 `panelProbe` 改为「viewBox 量画布 + 取最宽背景矩形量绘图区」，蜡烛计数排除所有与绘图区同宽的背景矩形（此前一块无 `fill/stroke` 的背景矩形被算成第 31 根）；缩放断言改为点击真实浮动 ➕/➖ 按钮，并新增「滚轮事件不再改变视窗根数」；R07 的 `subplotProbe` 改查唯一控件 `#chartSubPlotControlUnified`，并把「按图独立档位」的断言改写为「联动一致性 + 手选不被改写 + 首屏沿用本维度默认（如实登记不一致）」。

**注意**：修探针前先确认新几何/新控件是「要保留的设计」；若其实是想回退，请回退代码而不是改断言。**另有一条纪律**：探针里出现的字面量（730/795/200/65）必须能追溯到「当前 app.js 的常量」，否则一律改成实测或与首测状态比对 —— 本轮 39/44 全绿靠的正是这条。

---

## 六、配方：改图表口径（最容易连带炸测试的地方）

改以下任一内容，都会影响真机/静态断言，请**同时**更新对应测试：

| 改动 | 连带影响 |
| :--- | :--- |
| 画布宽（现 920）、边距（现 65/65） | `browser_r06_verify.js` 的几何探针、`test_r04_chart_viewport.js` 的 `W/M` 常量 |
| 缩放下限（现 30 根） | REQ-035 系列断言、`MIN_PANEL_BARS` |
| 副图默认档位（K 线＝成交额、分时＝成交量） | REQ-037 断言、`panelDefaultSubplot` / `applyDefaultSubplot` |
| 成交额兜底口径与标注 | REQ-025 断言要求标题含 `（含估算：均价×成交量）`、图上含「其中 N 根成交额为估算」 |
| 缠论买卖点默认等级（现 3＝六类全开） | REQ-041 断言、`DEFAULT_BS_LEVEL` |
| 周/季聚合口径 | REQ-042/043 要求与日线逐日相加口径**逐根一致**，且标注含估算根数 |

**硬规则**：成交额三级口径 `真实 amount_yi → 来源 amount/1e8 → (开+收+高+低)/4 × 成交量（标注估算）`；三者皆不可得＝`null`，**绝不以 0 充当成交额**。

---

## 七、测试与验证怎么跑（含装填陷阱）

### 三层门禁

| 层 | 命令 | 特点 |
| :--- | :--- | :--- |
| Python 单测（18 文件 / 266 用例） | `python3 -m unittest discover -s tests -p "test_*.py" -v` | 不触网、不碰产品库（隔离临时库） |
| JS 静态套件（6 套） | `node tests/test_chart_integrity.js`、`test_detail_requests.js`、`test_layer_interaction.js`、`test_r04_chart_viewport.js`、`test_r08_chart.js`、`test_r09_subplot_header.js` | 在 Node `vm` 沙箱里**整源求值** `web/app.js`，只补 DOM 桩 |
| 真机套件（6 套） | `node tests/browser_r03..r08_verify.js` | headless Chrome + CDP 打真实页面与真实接口 |

### JS 静态套件的两个装载方式（坑）

- **整源求值**（`test_r04` / `test_r08` / `test_layer_interaction` / `test_chart_integrity`）：把整个 `app.js` 丢进 `vm`，健壮，推荐。
- **按标记切片**（`test_detail_requests.js`）：只求值 `openStockDetail` 片段 —— **函数一旦引用切片外的 helper 就会报 `xxx is not defined`**（本工程 9/24 就踩过一次）。遇到这种报错，正确做法是**在沙箱内注入该 helper 的真实定义**，而不是改写被测函数：

```js
const turnBegin = source.indexOf('function getStockCirculatingShares(');
const turnEnd = source.indexOf('\n}', source.indexOf('function resolveItemTurnoverRate(')) + 2;
vm.runInContext(source.slice(turnBegin, turnEnd), context);
```

### 真机套件的环境变量

```sh
DSH_BASE=http://127.0.0.1:8888          # 目标地址
DSH_CDP_PORT=9372                        # CDP 调试端口（多套件并行时务必错开）
DSH_SHOT_DIR=docs/verification/<批次>    # 截图与报告目录
DSH_CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"   # 无 Chromium 缓存时指定
```

---

## 八、踩坑清单（都是本工程真实发生过的）

1. **TDZ 陷阱（9/24 的真实事故）**：在函数中后置声明 `const`，却在更早的分支里使用 → `ReferenceError: Cannot access 'x' before initialization` → **整张 SVG 不渲染、详情页"未加载"**。改图表函数时，先确认所有 `const` 都在使用点之前。
2. **切片式测试装载**（第七节）：新增 helper 会让老套件报「未定义」。
3. **硬编码几何**：不要把画布宽/绘图区坐标写进测试或文档，改成实测。
4. **版本号三处不同步**：`config/version.json`（权威）、`web/index.html` 的 `app.js?v=` 查询串、`docs/operations/product-entry.json`。发版时三处都要动。
5. **改 `index.html` 里的控件 id**：前端按 id 取元素（`chartSubPlotControlUnified`、`stockInteractiveSvg_left/right`、`chartSvgContainerLeft/Right`…），改名会静默让旧脚本与部分逻辑取空。
6. **看门狗会把你 kill 掉的进程拉回来**：停服务请用 `scripts/stop_server.sh`。
7. **空持仓不是 0 元**：`portfolio: []` 或 `portfolio_verified: false` 时，体检/预警必须"拒答"，不要为了"界面好看"补 0。
8. **不要把测试数据写进产品库**：测试必须 `patch.object(stock_db, "DB_PATH", 临时路径)`。
9. **缠论只有一套算法**：不要为周/季/分钟再写第二套判定；提交真实 K 线给 `POST /api/chanlun/bars` 复用 `analyze_bars`。
10. **`data/stock_database.db` 在 git 里常驻"已修改"是正常的**（运行期行情缓存写入），不要因此重建库。
11. **聚合函数的返回字段名要对着 `return` 看**（9/24 真实缺陷）：副图「总和」读的是不存在的 `windowAmount.totalYi`，而 `computeWindowTotalAmount()` 实际返回 `totalAmountYi` —— `undefined` 让 `Number.isFinite` 静默走兜底分支，于是**成交额明明可得却长期显示 `--`**。改口径时先确认"是否出数"的判定条件，别只判字段有限。
12. **指数成交额严禁用「点位 × 成交量」兜底**：`resolveKlineAmount()` 的估算兜底对指数是量纲错误（实测得 `3,943,379.8亿`）。指数相关的统计/刻度/交易面积一律走 `indexDisclosedAmountSamples()` 或 `computeTradeArea(..., {disclosedOnly:true})`。
13. **缺失与 0 必须在类型层面分开**：整段区间没有可用成交额时返回 `null`（显示「未交汇 / 不可得」），不要返回 `0.00亿`。
14. **SVG 文字排版不要用固定起点**：本工程副图表头已统一用 `estimateSvgTextWidth()` + `layoutSubplotHeader()` 按实测宽度逐项定位；新增/改动表头请复用它，不要再写 `x="m.left + 92"` 这类硬编码起点（9/24 前的叠字根因），也不要在模板里另画一次标题（会出现双标题）。

---

## 九、优化路线建议（按收益/成本排序）

| 优先级 | 事项 | 为什么 | 建议做法 |
| :--- | :--- | :--- | :--- |
| P0 | ~~修 R06/R07 真机探针~~ **已完成（2026-09-24）** | 六套真机回归已全绿（R06 39/39、R07 44/44、R08 40/40、R09 28/28） | 见第五节实测记录 |
| P0 | 收口未提交 WIP：R05~R09 五个批次分批提交 | 当前工作树与 HEAD 差 9 个批次，任何回退都不可控 | 门禁已全绿，按批次 `git add` 指定文件后提交（勿提交 `data/stock_database.db`） |
| P1 | 拆 `web/app.js`（8574 行） | 单文件全局命名空间是最大维护风险 | 按「图表引擎 / 详情页 / 数据中心 / 缠论图层 / 筛选器」切文件，保持全局挂载顺序；或引入原生 ESM（无构建） |
| P1 | 拆 `scripts/stock_web_server.py`（1753 行） | 44 个路由挤在长 if 链里 | 抽 router 注册表 + 各主题 handler 模块 |
| P1 | ~~台账补齐 REQ-027~032、启用 REQ-033~~ **已完成（2026-09-24）** | 已按「代码引用点 + 测试断言 + 现行实测」三处交叉实证回填；REQ-033 明确作废 | 见 `docs/requirements.md`「R05 台账」 |
| P2 | ~~同步 `product-entry.json`~~ **已完成（2026-09-24 → v5.4.0）**；`docs/architecture.md` 保持作废标注 | 入口证据已含变更摘要、门禁快照、源指纹与 live-entry | 以 `architecture-current.md` 为准；旧文档只留作废说明 |
| P2 | 日志轮转与库归档 | `server.log` 近 1 MB 无轮转、DB 58 MB | 加 `logging.handlers.RotatingFileHandler` 或按日切分；库定期 `VACUUM` + 归档快照 |
| P2 | 性能：全历史 6000+ 根 K 线全量重绘 | 缩放/切图有可感延迟 | 增量渲染、缓存已聚合的周/季序列、避免每次重建整段 SVG 字符串 |
| P3 | 前端可视化增强 | 体验 | 指标对比、图表导出、亮色主题（现为 dark） |
| P3 | 持仓与告警真实化 | 功能闭环 | 填真实持仓 + `portfolio_verified: true`；配置 `config/notify_config.json` |

---

## 十、提交前检查单（Copy 用）

```text
[ ] 需求已在 docs/requirements.md 登记编号，状态标为 [ACTIVE] 或对应流转态
[ ] 数据只来自真实来源；缺失处显示"未获取/不可得"，没有 0 或推测值兜底充数
[ ] 成交额兜底处带「含估算：均价×成交量」与估算根数标注
[ ] python3 -m unittest discover -s tests -p "test_*.py"        → OK
[ ] node tests/test_chart_integrity.js / test_detail_requests.js /
     test_layer_interaction.js / test_r04_chart_viewport.js / test_r08_chart.js  → 全 PASS
[ ] node tests/browser_r08_verify.js（及相关批次）→ 全 PASS，控制台 0 错误
[ ] 证据落到 docs/verification/<日期>-<批次>/（截图 + browser-report.json + README）
[ ] config/version.json 版本与交付说明已更新；index.html 的 ?v= 查询串同步
[ ] 未对 data/stock_database.db 做迁移/重建；测试库已隔离
```

---

## 15. 「唯一权威」文件必须在**运行期**即时生效（BUG-006 的教训）

本项目把 `config/version.json` 定为版本唯一权威。v5.5.0 发版时发现服务端在**模块导入时**读一次就缓存成常量，
于是权威文件已是 `v5.5.0`，而 `/api/version` 与页面标题仍是 `v5.4.1` —— 必须手工重启才恢复。

**更危险的是它骗过了验收**：真机脚本如果同时读页面和接口做「一致性比对」，两边都是旧值时会互相印证而**通过**。

**规矩**：

1. 任何被声明为「唯一权威」的配置（版本号尤其如此），都要问一句「改了它，运行中的进程多久生效？」
   —— 默认答案应当是「下一个请求」而不是「下次重启」。
2. 实现上用「文件 mtime + size 作为失效判据」做轻量缓存：既不必每请求读盘，也不会把旧值钉死。
3. 文件缺失或 JSON 损坏时必须**回退到上一次已知值**，绝不让「查版本」把服务搞挂。
4. 发版验收固定做**三方交叉核对**：权威文件 / 接口 / 真实页面，三者必须同值（`docs/problem-log/BUG-006-*.md` 有完整复现）。
