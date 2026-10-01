# DSH股票 · 接手与对接总览（Handoff Onboarding）

> 适用对象：接手本工程的开发者／维护者／后续优化者
> 编写时间：2026-09-24（基于当日真实工作树与真机复验）
> 事实基准：**以代码、数据库与真机验证为准**；文末「文档漂移清单」列出所有与代码不一致的旧文档，不要采信旧文档的版本号。

---

## 一、这是什么产品

| 项 | 事实 |
| :--- | :--- |
| 产品名 | DSH股票（工程代号 `DSH-STOCK-QUANT`）；Web 端自称「A股多维量化筛选器 · DSH Stock Web」 |
| 形态 | **本地 Web 应用 + 标准化 CLI**，两者共用同一套 Python 引擎与同一份 SQLite 数据库 |
| 覆盖范围 | 沪深京 A 股全量标的（`stocks_master` 实测 **4601** 只）＋ 大盘/行业指数 ＋ 股东研究 ＋ 全球宏观 ＋ 缠论买卖点 |
| 数据口径 | **只用公开真实来源**（腾讯／东方财富／新浪／巨潮等），来源缺失一律**如实提示未获取**，产品链路**禁止任何 mock、合成或补齐数据**（REQ-012 红线） |
| 运行依赖 | Python 3 **标准库零依赖**；Node 仅在跑测试脚本时需要 |
| 当前版本 | `v5.5.0`（`config/version.json`；服务端 `/api/version` 实测同值 **且运行期即时生效**），交付批次 **R10 工程加固**（R09.1 = v5.4.1、R09 = v5.4.0、R08 = v5.3.0） |
| 入口 | Web `http://127.0.0.1:8888/` ｜ CLI `python3 scripts/dsh_stock_cli.py status` |

一句话：**一个跑在本机、只吃真实公开行情、把「选股 → 看图 → 缠论判点 → 持仓体检 → 告警」串成一条链的 A 股量化工作台。**

---

## 二、5 分钟上手（服务此刻是否在跑）

```sh
cd "/Users/linqiyu/Documents/DSH/DSH股票"

# 1) 幂等保活（已在跑就什么都不做；掉了会自动拉起服务端 + 看门狗）
bash scripts/ensure_server.sh

# 2) 确认服务端与看门狗都在
lsof -nP -iTCP:8888 -sTCP:LISTEN        # 期望：LISTEN
ps aux | grep -E "watchdog|stock_web_server" | grep -v grep

# 3) 打开产品 / 读版本
open http://127.0.0.1:8888/
curl -s http://127.0.0.1:8888/api/version | head -5

# 4) 停止（连看门狗一起停，否则会被自动拉起）
bash scripts/stop_server.sh
```

- 端口：默认 `8888`，可用 `DSH_STOCK_PORT=8899` 起第二实例（PID 文件按端口区分：`.server.pid` / `.server-8899.pid`）。
- 运维铁律：**不要 `kill` 服务端而留着看门狗** —— 1 秒内会被 `scripts/watchdog.py` 自动拉起。改端口请先停再起。

---

## 三、交付面清单（接手要认全的「产品」）

### 1. Web 端（`web/`：index.html 2558 行 + app.js 8574 行 + style.css 3722 行，无框架、无构建步骤）

顶级 9 个页面（`switchMainTab`）：

| 页面 | 干什么 |
| :--- | :--- |
| 📈 股票列表 | 全量标的筛选：流动性／市值／PE／ST／行业／换手率等多维过滤，服务端筛选（`/api/filter`） |
| 📊 仪表盘 | 市场概览、筹码双维度、商誉风险雷达、盈利时长等汇总视图 |
| 🌍 宏观环境 | 全球宏观指标看板（`/api/macro/world`） |
| 👥 股东研究 | 十大股东穿透、同时增减持筛选、宏观六维概览 |
| 📈 指数 | 上证／深证等指数详情：分时图、5/15/30 分 K 线、20/60/120/180 天 K 线、全部 K 线、仅成交额副图、自动画线 |
| 🗄️ 数据中心 | 抓取审计控制台：抓取指纹幂等校验、新鲜度、ID/日期/状态/指纹四列、多选删除、数据库基准 |
| ☯️ 缠论雷达 | 多周期六类买卖点扫描与信号雷达池（`/api/chanlun/radar`） |
| 🎯 策略选股 | 「底背驰 + 放量突破中枢」等策略扫描 + 飞书/钉钉告警 |
| 💼 持仓体检 | 持仓盈亏、静态 + 动态止盈止损规则（**需真实持仓后启用**，见第六节） |

个股详情页（`openStockDetail`）＝ **左右双图面板**（默认「当日分时 + 日线图」，零点击）＋ 7 个 F10 维度 Tab：
`⚡最新动态 / 🏢公司资料 / 👥股东研究 / 📊财务分析 / 💼大宗交易 / 🤝资本运作 / 💰分红融资`。

图表能力（接手后最容易碰到的部分）：

- 颗粒度：当日分时、5 分 K 线；K 线维度＝日线图／周线图／季线图（周/季由真实日 K **内存聚合**，不落库）。
- 缩放：视窗根数 **下限 30 根、上限＝该颗粒度全部可用根数**（纯根数缩放，非固定 200）。
- 副图：成交额／成交量／换手率三档，默认按维度取（K 线＝成交额、分时＝成交量）。
- 缠论：买 1/2/3 + 卖 1/2/3 **六类全开默认自动标记**，五类图各自标注级别与判定依据。
- 自动画线：1~4 根多阶筹码峰压力线、重合线点击置顶、按模型分层共存与分模型清除。

### 2. CLI（`scripts/dsh_stock_cli.py`，16 个子命令）

```sh
python3 scripts/dsh_stock_cli.py status                 # 环境基线
python3 scripts/dsh_stock_cli.py quote 600519 300750 sh000001
python3 scripts/dsh_stock_cli.py list
python3 scripts/dsh_stock_cli.py analyze 600519         # 100 分制多空体检
python3 scripts/dsh_stock_cli.py portfolio              # 持仓看板与预警
python3 scripts/dsh_stock_cli.py chart 600519           # 纯 SVG 矢量图
python3 scripts/dsh_stock_cli.py report                 # 全盘 Markdown 研报 + 全套图
# 真实数据专线（无数据就如实失败，不回退）
python3 scripts/dsh_stock_cli.py history sh600519
python3 scripts/dsh_stock_cli.py holder-actions --json
python3 scripts/dsh_stock_cli.py holders --json
python3 scripts/dsh_stock_cli.py chanlun sh600519 --json
python3 scripts/dsh_stock_cli.py data-audit
python3 scripts/dsh_stock_cli.py holder / dividend / notice / blocktrade
```

### 3. HTTP API（`scripts/stock_web_server.py`，**GET 32 + POST 12 = 44 个路由处理器**，约 38 种端点形态，纯 `http.server` 手写路由）

`/api/version`、`/api/status`、`/api/filter`(POST)、`/api/filter_schema`、`/api/dashboard/overview`、`/api/macro/world`、
`/api/index/list`、`/api/index/<code>`、`/api/index/<code>/minute-kline`、`/api/stock/<code>`、`/api/stock/<code>/finance|block|events|shareholders|intraday-chanlun|minute-kline`、
`/api/chanlun/radar`、`/api/chanlun/radar/scan`(POST)、`/api/chanlun/radar/scan-status`、`/api/chanlun/bars`(POST，纯计算)、
`/api/screener/results`、`/api/screener/scan`(POST)、`/api/screener/scan-status`、`/api/portfolio/checkup`、
`/api/notify/status|history`、`/api/crawler/status|audit-list|baseline|export|start|cancel|audit-delete`、`/api/calendar/check`、`/api/server/start|shutdown|kill`。

> 详细契约、字段口径与数据层表结构见 [`architecture-current.md`](architecture-current.md)。

---

## 四、当前真实健康度（2026-09-24 实测，非文档抄录）

| 门禁 | 命令 | 实测结果 |
| :--- | :--- | :--- |
| Python 全量单测 | `python3 -m unittest discover -s tests -p "test_*.py"` | **266 PASS**（约 12~17 秒） |
| JS 静态套件（7 套） | `node tests/test_chart_integrity.js` 等 7 个（含 `test_r10_module_split.js`） | **7 / 7 PASS** |
| R10 真机验收（本批） | `node tests/browser_r10_verify.js` | **15 / 15 PASS**（模块装载顺序 / 迁出函数可用性 / 真实图表照常渲染 / CLI 归档只读安全） |
| R09 真机回归 | `node tests/browser_r09_verify.js` | **28 / 28 PASS**，控制台错误 0（REQ-046 徽标与接口逐字一致、REQ-047 三类副图 `getBBox()` 实测零重叠） |
| R08 真机验收 | `node tests/browser_r08_verify.js` | **40 / 40 PASS**，控制台错误 0 |
| R07 真机回归 | `node tests/browser_r07_verify.js` | **44 / 44 PASS**（R09 已按统一幅图控件口径修订探针） |
| R06 真机回归 | `node tests/browser_r06_verify.js` | **39 / 39 PASS**（R09 已把几何与缩放改为实测/真实入口） |
| R05 历史快照（已归档） | `node docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js` | 9 项通过 / 11 项过时失败 / 后续中断 —— **非回归**，其个股断言基于已被 REQ-034/035 取代的旧口径（已留痕） |
| 服务端健康 | `curl -s http://127.0.0.1:8888/api/status` | running，版本 **v5.5.0**；监听 **127.0.0.1:8888**（仅本机回环，`DSH_STOCK_HOST` 可放开） |
| 数据审计 | `python3 scripts/dsh_stock_cli.py data-audit` | `legacy-quarantined`：旧无来源缓存被隔离，不进入产品 |

真机验证脚本会用 headless Chrome + CDP 打开**真实页面、真实接口、真实数据**（不 mock），截图落在 `docs/verification/<批次>/`。
无 Chrome 时可用 `DSH_CHROME_BIN` 指定，本机默认走 `~/Library/Caches/ms-playwright/chromium-1223/...`。

---

## 五、R09 批次（v5.4.0）改了什么

| 需求 | 用户可见效果 | 落地位置 |
| :--- | :--- | :--- |
| REQ-046 | 顶栏「📅 行情日期: 2026年9月24日 13:18」——**精确到分**，取来源真实时间戳；只给到日就只显示日，拿不到显示「未获取」 | `scripts/stock_web_server.py`（`parse_quote_timestamp` / `current_quote_datetime`，随 `/api/status`、`/api/filter`、基准接口暴露）、`web/app.js`（`formatQuoteMoment` / `updateDataValidityDateBadge`） |
| REQ-047 | 副图标题与「总和/平均/地量/天量/中位数」**按实测宽度平铺**，任意标题长度不重叠；不够宽时换行并按行压缩柱高 | `web/app.js`（`estimateSvgTextWidth` / `layoutSubplotHeader`，应用于个股日K、当日分时、大盘指数三处副图） |
| 顺带修复 | 副图「总和」不再恒为 `--`；指数副图不再出现 `3943379.8亿` 这类量纲错误数字（改为如实「不可得」）；交易面积不再以 `0.00亿` 冒充「面积为 0」 | 见 [`docs/problem-log/BUG-005`](../problem-log/BUG-005-subplot-total-and-index-amount-caliber.md) |

---

## 六、R09.1 补丁（v5.4.1）改了什么

| 需求 | 用户可见效果 | 落地位置 |
| :--- | :--- | :--- |
| REQ-037 修订 | 首屏「当日分时」与「K线」两个副图**都是成交额**，与唯一「幅图联动」控件的高亮一致（此前左图显示成交量、控件却高亮成交额） | `web/app.js`（`panelDefaultSubplot` / `createPanelChartState`） |
| REQ-049 | 服务端默认**只监听 127.0.0.1**（此前 `0.0.0.0` 对局域网开放）；需要多设备访问时 `DSH_STOCK_HOST=0.0.0.0 bash scripts/ensure_server.sh` | `scripts/stock_web_server.py`（`resolve_bind_host`）、`scripts/ensure_server.sh`、`scripts/watchdog.py` |
| REQ-050 | `server.log` / `watchdog.log` 超过 5MB 自动切分为 `.1`（保留 3 份），不再无限增长 | `scripts/ensure_server.sh`（`rotate_log`，`DSH_STOCK_LOG_MAX_KB` 可调） |
| REQ-051 | R05 过时快照脚本已从 `tests/` 归档到 `docs/verification/2026-09-20-r05/`，不会再被误当回归门禁 | 文件移动 + 全部引用同步 |

---

## 七、R10 批次（v5.5.0）改了什么 —— 工程加固，无行情口径变更

| 需求 | 用户/维护者可见效果 | 落地位置 |
| :--- | :--- | :--- |
| REQ-052 | 新增 CLI 子命令 **`db-archive`**：一键为产品库生成**只读**一致性快照（含完整性校验、逐表行数核对、可选紧凑副本、可追溯 manifest），默认只增不删 | `scripts/db_maintenance.py`（新）、`scripts/dsh_stock_cli.py`（子命令 16 → 17） |
| REQ-053 | 前端不再是单个 8756 行大文件：10 个纯函数外置到 `web/modules/util.js`，页面按 `util.js → app.js` 顺序加载，**调用点零改动、行为逐字一致** | `web/modules/util.js`（新）、`web/app.js`（减 144 行）、`web/index.html`、`tests/load_web_sources.js`（新） |
| REQ-054 | **发版不再需要重启服务端**：`config/version.json` 改动后接口/页面立即反映（修复 BUG-006：此前升版后接口与页面仍显示旧版本，且验收会把「两边都旧」误判为一致） | `scripts/stock_web_server.py`（`current_version()` / `current_version_info()`） |

> **验收时的实测数字**：Python 266 PASS · JS 7 套 PASS · 真机 R10 15/15 · R09 28/28 · R08 40/40 · R07 44/44 · R06 39/39 · 控制台错误 0（证据 `docs/verification/2026-09-24-r10/`）。

---

## 八、接手当日已处理的阻塞问题（必须知道）

工作树里存在**一批 R08 验收（2026-09-23 15:58）之后、未提交也没登记的改动**（`web/app.js` 9/24 11:48、`web/index.html` 9/23 21:32、`web/style.css` 9/23 22:00）。这批改动把**个股详情图整体打挂**了：

| # | 症状（真机可复现） | 根因 | 处理 |
| :--- | :--- | :--- | :--- |
| 1 | 打开个股详情「未加载」，日线/周线/季线图全不出来；R08 真机**只跑到第 20 项就中断、仅 15 项通过**（修复前实测） | `generateDailyKlineSVG` 中 `const windowAmount` / `const totalTurnover` 被挪到使用点**之后**，换手率与成交额两个分支触发 **TDZ**（`Cannot access before initialization`），异常中断整张 SVG 渲染 | 已把两个常量声明**移到「四维分布概要」之前**（单一职责、无语义变化） |
| 2 | 副图标题退化为「副图：成交额（含估算）」，丢了口径说明 | 改动把 R04 验收口径 `（含估算：均价×成交量）` 简写 | 已按 REQ-025 恢复全称 |
| 3 | `node tests/test_detail_requests.js` 报 `resolveItemTurnoverRate is not defined` | 该套件用**源码切片**装载 `openStockDetail`，新引入的换手率 helper 不在切片内 | 已在沙箱内注入 helper 的**同一份真实实现**（断言意图不变） |

**证据**：修复前 `browser_r08_verify.js` = 15/20（详情未加载、买卖点 0 个）；修复后 = **40/40 PASS、控制台 0 错误**，六个买卖点图层、周/季成交额逐日相加标注全部恢复；`test_r08_chart.js`、`test_r04_chart_viewport.js` 由 FAIL 转 PASS。

### 仍未处理：3 套旧批次真机脚本的「探针漂移」（不是产品缺陷）

这批未提交改动同时把 **K 线画布宽度 860 → 920**（绘图区 65~855，原 65~795），并把左右两个副图控件**合并为一个 `chartSubPlotControlUnified`**。R06/R07 脚本把旧几何与旧控件 id **写死在探针里**，因此报红：

| 套件 | 失败表现 | 判定 | 修法（确认新几何是要保留的前提下） |
| :--- | :--- | :--- | :--- |
| R06（10 项） | `实绘 31 根`（把 790 宽的网格矩形也当成蜡烛）、`绘图区 nullpx (x=null)`、`折线 X 65~855（绘图区 65~795）` | 探针里 `width === '730'` 与 `65 + 730` 是旧画布常量；实测折线 65~855 **正好铺满新绘图区**，行为正确 | 把探针的 730/795 改为**从 SVG 实测**（找到网格矩形后取 `x`/`width`），不再硬编码 |
| R07（6 项） | `active=null`（`#chartSubPlotControlRight/Left` 已不存在） | 控件已统一为 `chartSubPlotControlUnified`；同页面文案 `副图：成交额（含估算：均价×成交量）` 证明档位正确 | 探针改为查询统一控件（或按面板读取 `.seg-btn.active`），断言意图不变 |

修法建议已落到 [`optimization-guide.md`](optimization-guide.md#五旧批次真机探针的修复配方)，避免下次又踩。

### 另有两个运行事实，请一并知悉

1. **服务默认监听 `0.0.0.0:8888` 且 API 无鉴权**（`lsof` 实测 `TCP *:8888 (LISTEN)`）——同网段设备可直接调用 `/api/server/kill`、`/api/crawler/*` 等有副作用的端点。若只在本机使用，建议 `--host 127.0.0.1` 启动（并同步改 `watchdog.py` / `ensure_server.sh` 的探活地址）。
2. **`server.log` / `watchdog.log` 无日志轮转**（`server.log` 已近 1 MB），长期运行需自行加轮转或定期清理。

---

## 九、接手就要知道的「按设计如此」（别当成 bug 去修）

1. **持仓体检/预警不产出结论**：`config/stock_config.json` 的 `portfolio: []` 且 `portfolio_verified: false`。**空底册一律拒绝输出**，不会显示 0 元 —— 这是 R03 的刻意设计。要用，请填本人真实持仓并把 `portfolio_verified` 置 `true`。
2. **数据缺失≠0**：来源没披露就写「未获取／不可得」，图上不画、表里不填 0；成交额兜底必须标注「含估算：均价×成交量」及其根数。
3. **成交额三级口径**：真实 `amount_yi` → 来源 `amount/1e8` → `(开+收+高+低)/4 × 成交量` 估算（并标注）；三者都不可得＝`null`。
4. **周/季 K 线是内存聚合**：由真实日 K 按自然周/自然季度分桶，**不落库、不插值、不补足**；成交额＝区间内日线成交额逐日相加。
5. **缠论只有一套算法**：后端 `analyze_bars` / `build_buy_sell_points`；前端把周/季/5 分真实 K 线序列提交给 `POST /api/chanlun/bars` **现场判定**，不落库、不另起第二套。识别不到就如实显示 0。
6. **旧库不删、只隔离**：`data-audit` 的 `legacy-quarantined` 表示无来源的历史缓存不参与产品计算，但**不删除历史库**。
7. **告警默认关闭**：`config/notify_config.json` 不在版本控制内（`.gitignore`），需要自己从 `notify_config.example.json` 复制并填真实 Webhook。

---

## 十、文档漂移清单（接手第一件该修的事）

| 位置 | 现在写的是 | 实际情况 |
| :--- | :--- | :--- |
| `README.md` 顶部 | v5.5.0 / 2026-09-24 | **已同步**（R10） |
| `docs/operations/product-entry.json` | 指向 `docs/verification/2026-09-24-r10/`（含 v5.5.0/v5.4.1/v5.4.0/v5.3.0 变更摘要、门禁快照、指纹与 live-entry 证据） | **已同步**（R10 重登记） |
| `docs/architecture.md` | v1.0.0 / 2026-09-16，且写着「离线 Mock 双模降级」「拟真连续 K 线序列」 | **已作废**：v4.3.0 起剔除全部 mock（REQ-012），该文档与红线直接冲突 → 请改用 [`architecture-current.md`](architecture-current.md) |
| `config/stock_config.json` → `system.version` | `v1.0.0` | 与产品版本无关的历史字段，容易误读（未改，属配置历史遗留） |
| `docs/requirements.md` | R05 台账（REQ-027~032）已于 2026-09-24 依代码与测试**实证回填**，REQ-033 明确作废 | **已补齐**；回填口径与引用点见台账「R05 台账」小节 |
| Git | `HEAD = 239cced`（v5.0.0，2026-09-20） | **R05~R10 全部未提交**（工作树 = v5.5.0 实际交付内容）；`data/stock_database.db` 常驻「已修改」属运行期常态 |
| ~~`tests/browser_r05_verify.js`~~ | —— | **已归档（2026-09-24）**：移至 `docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js`；实测留痕 9 通过 / 11 项过时失败 / 后续 `TypeError` 中断（`docs/verification/2026-09-24-r09/r05-snapshot/README.md`），**不得作为回归判据** |
| `docs/verification/2026-09-20-r05/` | 只有 1 张 PNG，无 README、无 report | 该批次原始记录不完整（已登记进台账，不补造） |

---

## 十一、后续优化切入点（按性价比排序，详见优化指南）

1. **收口未提交 WIP**：R05~R10 六个批次已在同一工作树交付且门禁全绿（Python 266 · JS 7 套 · 真机 5 套），建议按批次提交；提交时保持 `config/version.json` 为唯一版本权威，**发版后务必三方核对「权威文件 / 接口 / 真实页面」同值**（BUG-006 的教训）。
2. **继续拆巨型单文件（第一步已完成）**：`web/app.js` 已从 8756 → **8612 行**（纯函数外置 `web/modules/util.js`）；下一步按「图表引擎／详情页／数据中心／缠论图层」继续切，`scripts/stock_web_server.py`（1826 行）同理。**每切一块都必须过 R06~R10 五套真机回归**，并同步 `tests/load_web_sources.js`。
3. **决定首屏副图档位语义**（REQ-037 遗留观察项）：统一「幅图联动」控件高亮成交额，而当日分时未点选前渲染成交量 —— 二选一：统一首屏默认档位（一行改动）或让高亮同时反映两图；**属产品语义决策，不要自行改**。
4. ~~处置 `tests/browser_r05_verify.js`~~ **已完成**：已归档到 `docs/verification/2026-09-20-r05/`；如仍需要 R05 的指数页回归，另行按现行口径重写。
5. **服务暴露面**：`scripts/ensure_server.sh` 默认 `0.0.0.0` 且无鉴权，本机自用可接受；若要改为 `127.0.0.1` 需确认真机验证脚本与本机入口不受影响（它们都走 `127.0.0.1`，可改）。
6. **能力增强**：持仓真实化后启用体检与告警；分钟级 `m1` 后端能力仍在（前端入口已按指令移除），如需彻底下线需确认。
7. **性能与运维**：单只标的全历史 6000+ 根 K 线在内存中全量计算／重绘，可评估增量渲染与虚拟化；`server.log` 未轮转、产品库 58 MB 未定期归档。

---

## 十二、红线与约定（改代码前请先读）

- **禁止任何形式的虚构数据**：不得 mock 回退、不得合成 K 线、不得用 0 或推测值补缺（REQ-012）。
- **来源必须可追溯**：新增数据一律走 `scripts/data_sources/` 适配器 + `verified_source_cache`，失败要明确 `status/error`。
- **需求编号双向同步**：新功能先登记 `docs/requirements.md`（当前最大编号 REQ-045），再动代码；测试断言必须映射 REQ 编号。
- **交付前必须全绿**：Python 全量 + 6 套 JS 静态 + 相关真机套件 + 更新 `config/version.json` 与验证记录目录。
- **不写产品库**：验证／测试涉及数据库时必须指向隔离临时库（`patch.object(stock_db, "DB_PATH", ...)`），不得对 `data/stock_database.db` 做迁移或重建。

---

## 十三、延伸阅读

| 文档 | 用途 |
| :--- | :--- |
| [`architecture-current.md`](architecture-current.md) | 当前真实架构、模块地图、API 契约、数据层表结构 |
| [`optimization-guide.md`](optimization-guide.md) | 二次开发配方：加页面/接口/数据源/指标，测试与交付流程，踩坑清单 |
| [`product-copy.md`](product-copy.md) | 产品文案包（一句话、短/长介绍、卖点、免责声明、版本文案） |
| `../requirements.md` | 需求台账（REQ-001 ~ REQ-045，含各批原始需求与验收证据） |
| `../problem-log/index.md` | 历史缺陷台账（BUG-001~003：历史污染、覆盖截断、合成数据） |
| `../knowledge/index.md` | 知识库（缠论教程、技术分析买卖点指南） |
| `../baselines/2026-09-20/README.md` | 基线与回退口径 |
