# DSH股票 · 当前真实架构（Architecture as-is）

> 事实基准：`v5.5.0` 工作树（R09），2026-09-24 实测。
> **替代关系**：本文取代已作废的 `docs/architecture.md`（v1.0.0，其中「离线 Mock 双模降级」与现行 REQ-012 红线直接冲突）。
> 若代码与本文不一致，**以代码为准**，并顺手修正本文。

---

## 一、分层总览

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 表现层                                                                        │
│  web/index.html (2558) + web/app.js (8574) + web/style.css (3722)             │
│   · 无框架、无构建、无 npm 依赖；index.html 直接 <script src="/web/app.js">    │
│   · 9 个顶级页面 + 个股详情双图面板 + 7 个 F10 维度 Tab                        │
│  CLI: scripts/dsh_stock_cli.py (493) —— 16 个子命令，ANSI 彩色终端             │
└───────────────▲──────────────────────────────────────────┬───────────────────┘
                │ fetch('/api/...') 同源                    │ stdout / SVG / Markdown
┌───────────────┴──────────────────────────────────────────▼───────────────────┐
│ 接入层  scripts/stock_web_server.py (1753)                                    │
│  · 基于标准库 http.server，手写路由（GET 32 + POST 12 = 44 个处理器）           │
│  · 静态资源：/ → index.html，/web/* → web/                                    │
│  · 生命周期：/api/server/start|shutdown|kill；PID + 看门狗另有独立脚本         │
└───────────────▲──────────────────────────────────────────────────────────────┘
                │ Python 函数调用
┌───────────────┴──────────────────────────────────────────────────────────────┐
│ 引擎层（全部零三方依赖）                                                       │
│  行情/历史   stock_data_engine.py · real_chart_engine.py · market_history.py   │
│              history_service.py · trading_calendar.py                          │
│  指标/评分   stock_indicators.py（MA/MACD/RSI/BOLL/KDJ + 100 分制）             │
│  缠论        chanlun_core.py(554) · chanlun_signals.py(671) · chanlun_analysis │
│              chanlun_strategy_engine.py · chanlun_chart_svg.py                 │
│  组合/预警   stock_portfolio.py · portfolio_checkup.py · alert_channels.py     │
│  选股/看板   strategy_screener.py · dashboard_engine.py · index_engine.py       │
│  股东/事件   shareholder_engine.py · shareholder_actions.py · stock_events_engine│
│              company_finance_engine.py · official_block_trade_engine.py        │
│  宏观/日历   world_macro_engine.py · trading_calendar.py                        │
│  研报/图表   stock_reporter.py · stock_chart_svg.py（纯 SVG，零依赖）           │
│  运维        ensure_server.sh · start_server.sh · stop_server.sh · watchdog.py │
│              daemon_launch.py · cleanup.sh · anti_crawler.py · manual_crawler.py│
└───────────────▲──────────────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────────────┐
│ 数据层                                                                        │
│  scripts/stock_db.py (1004)  → SQLite  data/stock_database.db（实测 ~58 MB）    │
│  scripts/verified_sources.py → 可追溯来源缓存与请求封装                         │
│  scripts/data_sources/*      → 分主题适配器（K线/股东/公告/分红/大宗/安全会话） │
│  data/all_a_shares.json · data/shareholders_cache.json                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、模块地图（按规模排序，接手优先级最高的在上）

| 模块 | 行数 | 职责 | 接手提示 |
| :--- | ---: | :--- | :--- |
| `scripts/stock_web_server.py` | 1753 | 全部 HTTP 路由与页面数据装配 | 单文件承载 44 个路由处理器；**拆分首选** |
| `web/app.js` | 8574 | 前端全部逻辑（状态、渲染、图表、图层） | 单文件无模块化；全局函数名即事实 API |
| `scripts/stock_db.py` | 1004 | SQLite 建表、写入、查询、指纹与新鲜度 | 所有落库必须经此模块 |
| `scripts/chanlun_signals.py` | 671 | 多周期买卖点、区间套、雷达池、可执行性判定 | 缠论口径的**唯一权威实现** |
| `scripts/chanlun_core.py` | 554 | 分型/笔/线段/中枢/背驰/均线缠绕 | 与上面同一套几何定义，勿另起 |
| `scripts/dsh_stock_cli.py` | 493 | 16 个子命令与彩色输出 | CLI 与 Web 共用引擎 |
| `scripts/portfolio_checkup.py` | 425 | 持仓风险体检、静态 + 动态止盈止损 | 依赖 `portfolio_verified` 门禁 |
| `scripts/strategy_screener.py` | 384 | 「底背驰 + 放量突破中枢」等策略扫描 | 结果写 `strategy_screen_results` |
| `scripts/dashboard_engine.py` | 384 | 仪表盘汇总与筹码/商誉维度 | |
| `scripts/stock_indicators.py` | 372 | 技术指标与 100 分制评分模型 | 权重可配（`scoring_weights`） |
| `scripts/alert_channels.py` | 357 | 飞书/钉钉告警、冷却去重、下发流水 | 需 `config/notify_config.json` |
| `scripts/chanlun_analysis.py` | 251 | `analyze_bars` 现场判定入口（`/api/chanlun/bars`） | 周/季/5 分缠论走这里 |
| `scripts/stock_reporter.py` | 235 | 每日 Markdown 研报 + SVG 索引 | 产物落 `reports/` |
| `scripts/stock_portfolio.py` | 235 | 持仓盈亏计算 | 空底册拒答 |
| 其余（`real_chart_engine` `shareholder_engine` `populate_db` `manual_crawler` `anti_crawler` `trading_calendar` `watchdog` 等） | 各 <200 | 单一职责小模块 | 新增能力优先按此粒度落新文件 |

---

## 三、前端结构（`web/app.js` 的真实组织方式）

无模块系统，靠**全局函数 + 全局状态对象**协作：

| 全局对象 | 作用 |
| :--- | :--- |
| `appState` | 主状态：当前 Tab、筛选条件、列表数据、`activeDetailStock`、`windowAmountSummary`、`detailRequestId`（竞态防护） |
| `indexState` | 指数页独立状态（含 `windowAmountSummary`） |
| `chartPanels = { left, right }` | **双图面板模型**：每个面板自带 `visible` / `st`（颗粒度、副图档位、图层、缩放视窗） |
| `panelBySlot(slot)` / `withChartPanel(slot, fn)` | 面板寻址与作用域封装（新代码必须走这两个入口，不要直接摸 `chartPanels`） |
| `PANEL_SLOTS = ['left','right']` | 面板枚举 |

图表渲染主链路：

```text
openStockDetail(code)
  → fetch /api/stock/<code>（带 detailRequestId 序号保护；返回 code 不一致即拒绝渲染）
  → 逐根补齐 turnover_rate（resolveItemTurnoverRate → 成交量 / 流通股本）
  → renderChartPanel(slot)
      → 取颗粒度数据（日线原生；周/季按自然周/季度内存聚合；分时/5分走分钟接口）
      → generateDailyKlineSVG(klines, subplotType, w=920, ...)    ← 画布宽 920，绘图区 65~855
      → generateChanlunOverlaySVG(...)（缠论六类买卖点，级别 + 判定依据）
      → 自动画线图层（1~4 根筹码峰压力线，分层共存）
```

关键常量（改动会连带影响旧验证脚本，见优化指南）：

| 常量 | 当前值 | 影响 |
| :--- | :--- | :--- |
| K 线画布宽 | `920`（`web/app.js` 中个股图表处，原 v5.0.0 为 860） | 绘图区 x=65、宽 790（65~855） |
| 指数画布宽 | `dom.indexChartSvgContainer.clientWidth \|\| 920` | 指数页自适应 |
| 图表边距 | `{ top:20, right:65, bottom:25, left:65 }` | 与画布宽共同决定绘图区 |
| 缩放视窗 | 下限 30 根，上限＝该颗粒度全部可用根数 | 纯根数缩放 |
| 副图控件 | **统一控件** `#chartSubPlotControlUnified` | 左右面板共用一个按钮组 |
| 副图默认档位 | K 线维度＝`amt`；当日分时＝`vol` | 用户手动选过后不再自动改写 |

---

## 四、API 契约（全部同源、**无鉴权**，默认监听 `0.0.0.0`）

> ⚠️ **安全提示**：`run_server(host="0.0.0.0", port=8888)` 为默认值，`lsof` 实测为 `TCP *:8888 (LISTEN)` —— **同网段设备可访问且无任何鉴权**。`--host` 可改；单机使用建议改为 `--host 127.0.0.1`（并同步调整 `watchdog.py` / `ensure_server.sh` 的探活地址），或确保只在可信网络下运行。

### 只读端点（GET）

| 路径 | 说明 |
| :--- | :--- |
| `/api/version` | 版本与交付说明（读 `config/version.json`） |
| `/api/status` | 服务健康、标的数、缓存状态；含 `snapshot_date`（数据库基准批次日期）与 `quote_datetime`（REQ-046 真实行情快照时间，精确到分） |
| `/api/filter_schema` | 筛选字段与枚举（前端动态渲染筛选器） |
| `/api/dashboard/overview` | 仪表盘汇总 |
| `/api/macro/world` | 全球宏观指标 |
| `/api/index/list` | 指数列表 |
| `/api/index/<code>` | 指数详情（K 线、副图、自动画线数据） |
| `/api/index/<code>/minute-kline` | 指数分时/分钟 K |
| `/api/stock/<code>` | **个股详情主接口**：行情 + 日线全历史 + 分时 + 缠论分析 + 元数据 |
| `/api/stock/<code>/finance` | 财务分析 |
| `/api/stock/<code>/block` | 大宗交易 |
| `/api/stock/<code>/events` | 公司事件 |
| `/api/stock/<code>/shareholders` | 十大股东与覆盖状态 |
| `/api/stock/<code>/intraday-chanlun` | 当日分时缠论判定 |
| `/api/stock/<code>/minute-kline` | 分钟 K（含 `m1`，后端能力保留） |
| `/api/shareholders/list` | 股东研究全景穿透 |
| `/api/chanlun/radar` · `/api/chanlun/radar/scan-status` | 缠论雷达池与扫描进度 |
| `/api/screener/results` · `/api/screener/scan-status` | 策略选股结果与进度 |
| `/api/portfolio/checkup` | 持仓体检（空底册时明确拒答） |
| `/api/notify/status` · `/api/notify/history` | 告警通道状态与真实下发流水 |
| `/api/crawler/status` · `audit-list` · `baseline` · `export` | 数据中心：抓取状态、审计清单、数据库基准、导出 |
| `/api/calendar/check` | 交易日判定 |

### 写/计算端点（POST）

| 路径 | 说明 | 是否落库 |
| :--- | :--- | :--- |
| `/api/filter` | 全量标的筛选（服务端计算）；`stats` 内同时返回 `quote_dates`（日粒度）与 `quote_datetime`（REQ-046 分钟粒度） | 否 |
| `/api/chanlun/bars` | **纯计算**：提交真实 K 线序列，现场返回缠论判定（周/季/5 分复用） | **否**（刻意不落库） |
| `/api/chanlun/radar/scan` | 触发雷达扫描 | 是（`chanlun_signal_radar`） |
| `/api/screener/scan` | 触发策略扫描 | 是（`strategy_screen_results`） |
| `/api/crawler/start` · `cancel` · `audit-delete` · `baseline` | 数据中心抓取与治理 | 是 |
| `/api/server/start` · `shutdown` · `kill` | 服务生命周期 | 否 |

**约定**：数据不可得时返回结构化缺失状态（`status` / `error` / 覆盖根数），**不得**用 0、空数组冒充「有数据」。

---

## 五、数据层

### 1. SQLite 表（`data/stock_database.db`，2026-09-24 实测行数）

| 表 | 行数 | 用途 |
| :--- | ---: | :--- |
| `stocks_master` | 4601 | 全量标的主表（代码、名称、市场、行业、市值、PE 等） |
| `stock_quotes` | 4601 | 最新行情快照 |
| `stock_shareholders` | 4605 | 十大股东名册（**按姓名去重统计**，非账户总户数） |
| `stock_daily_kline` | 727 | 按证券隔离的日 K 缓存 |
| `stock_timeline` | 4 | 分时序列 |
| `verified_daily_history` | 28 | 已核验的全历史覆写（可信历史） |
| `verified_shareholder_actions` | 2 | 已核验股东增减持 |
| `verified_source_cache` | 9237 | **可追溯来源缓存**（key → payload，来源/时间/状态可查） |
| `data_fingerprints` | 4601 | 抓取指纹（幂等免重复抓取） |
| `crawl_audit_records` | 13 | 抓取审计记录 |
| `chanlun_signal_radar` | 153 | 缠论信号雷达池 |
| `strategy_screen_results` | 0 | 策略选股结果 |
| `alert_dispatch_log` | 0 | 告警真实下发流水 |

### 2. 隔离口径（`python3 scripts/dsh_stock_cli.py data-audit`）

```json
{"status": "legacy-quarantined",
 "policy": "旧无来源股东、分红、IPO、行情缓存不进入产品；不删除历史库"}
```

即：**旧的无来源缓存被隔离，不参与任何产品计算；但物理上不删除**。新增数据必须带来源与时间，走 `verified_source_cache`。

### 3. 数据来源与适配器

| 适配器（`scripts/data_sources/`） | 覆盖 |
| :--- | :--- |
| `kline_adapter.py` | 日/周/月/分钟 K 线 |
| `shareholder_adapter.py` | 十大股东、增减持 |
| `announcement_adapter.py` | 巨潮公告披露 |
| `dividend_adapter.py` | 分红派现 |
| `block_trade_adapter.py` | 大宗交易 |
| `safe_session.py` | 统一请求会话（UA、超时、重试、防爬） |

主来源：**东方财富 datacenter API**（`verified_sources.py`）、**腾讯行情**、**新浪行情**、**巨潮资讯**；`anti_crawler.py` 负责节流与反封。

### 4. 数据安全约定

- 测试与验证涉及数据库时，必须 `patch.object(stock_db, "DB_PATH", 临时路径)` 指向隔离临时库。
- 服务运行期的行情缓存写入属常态；`data/stock_database.db` 在 git 工作树中长期处于「已修改」是**预期现象**，不代表有人改了结构。
- 严禁对产品库做迁移/重建；R04~R08 各批次均声明「零数据库写入改动」。

---

## 六、缠论引擎口径（改这块之前务必读）

- **唯一算法**：`chanlun_core.py`（分型 → 笔 → 线段 → 中枢 → 背驰）＋ `chanlun_signals.py`（六类买卖点、区间套嵌套确认与降级、可执行性判定）。
- **六类买卖点**：买 1/2/3、卖 1/2/3，**等级累积**（选 3 即同时绘制第 1、2、3 类），买卖各自独立、按面板隔离。
- **级别标注**：日线级别 / 周线级别 / 季线级别 / 分时级别 / 5 分级别；每个标记的悬停提示必须给出**级别 + 判定依据**。
- **周/季/5 分判定路径**：前端提交真实 K 线序列 → `POST /api/chanlun/bars` → 后端 `build_chanlun_from_bars` → 复用 `analyze_bars`，**不落库、不另起算法**。
- **识别不到＝如实显示 0**（如季线 101 根、成笔条件不满足时为 0），**不得补造**。
- 判定口径的验收依据见 `docs/requirements.md` 的 **REQ-040 / REQ-041**（明确「不得放宽」）。

---

## 七、运行与配置

| 配置/脚本 | 说明 |
| :--- | :--- |
| `config/version.json` | **产品版本的唯一权威**：`version` + `app_name` + `release_date` + 本批交付说明；`/api/version` 与页面徽标都读它 |
| `config/stock_config.json` | 指数、自选股、持仓底册（`portfolio` / `portfolio_verified`）、预警阈值、指标参数、评分权重 |
| `config/constituents.json` | 指数成分 |
| `config/notify_config.example.json` | 告警模板；真实文件 `notify_config.json` 被 `.gitignore` 排除（**密钥不入库、不入版本控制**） |
| `scripts/ensure_server.sh` | **幂等保活**入口（推荐日常使用）：健康就直接返回，不健康才清理残留并拉起 |
| `scripts/start_server.sh` / `stop_server.sh` | 显式启停；PID 按端口隔离 |
| `scripts/daemon_launch.py` | 让服务端/看门狗**脱离调用方进程组**（2026-09-23 掉线的根因修复） |
| `scripts/watchdog.py` | 1 秒级健康探测与自愈拉起；日志 `watchdog.log` |
| `.server.pid` / `.watchdog.pid` | 进程号文件（已 gitignore） |
| `server.log` | 服务端 stdout（**当前无日志轮转，已近 1 MB**） |

---

## 八、已知结构债（优化时的靶子）

1. `web/app.js` 8574 行单文件、全局命名空间：函数名冲突风险高，测试只能用「整源求值 + DOM 桩」或「按标记切片」两种脆弱方式装载。
2. `scripts/stock_web_server.py` 1753 行手写路由：新增端点要改长 if 链，建议按主题拆 router 或改表驱动注册。
3. 前端与后端口径常量重复（画布宽、绘图区、缩放下限）导致旧验证脚本硬编码失效。
4. ~~需求编号与代码引用存在缺口~~ **已闭环（2026-09-24）**：R05 区间的 REQ-027~032 已按代码引用点与测试断言实证回填，REQ-033 明确作废不再分配。
5. `server.log` / `watchdog.log` 无轮转；`data/stock_database.db` 58 MB 无归档策略。
6. 数据库无版本化迁移机制（表结构靠 `CREATE TABLE IF NOT EXISTS` 演进）。
7. **安全**：服务端默认 `0.0.0.0:8888` 且 API 无鉴权（含 `/api/server/kill`、`/api/crawler/*` 等有副作用的端点）——同网段任何人可调用，建议改为仅监听 `127.0.0.1`。
8. 未提交的 WIP 与 HEAD 相差 8 个批次（R05~R08），且工作树含未登记改动，任何回退都缺少可比对的基线。

---

## 附：R09.1（v5.5.0）运行期约束变更

| 约束 | 现值 | 变更方式 |
| :--- | :--- | :--- |
| 监听地址 | **`127.0.0.1`**（仅本机回环，局域网不可达） | `DSH_STOCK_HOST=0.0.0.0 bash scripts/ensure_server.sh` 或 `--host 0.0.0.0` 显式放开；启动日志会标注当前暴露面 |
| 鉴权 | **无**（依赖回环绑定收敛风险） | 需多设备访问时必须另行引入鉴权（未实现） |
| 日志 | `server.log` / `watchdog.log` 在保活启动时按大小轮转，保留最近 3 份 | `DSH_STOCK_LOG_MAX_KB`（默认 5120KB）调整阈值 |
| 副图档位 | 首屏两图统一默认「成交额」，与唯一「幅图联动」控件高亮一致；手动选择后不被颗粒度/子Tab切换改写 | `web/app.js` 的 `panelDefaultSubplot` / `createPanelChartState` / `applyDefaultSubplot` |
| 版本权威 | `config/version.json` = **v5.5.0**，且**运行期即时生效**（mtime+size 失效重读，发版无需重启；见 BUG-006） | `/api/version` 与页面徽标实测同值（真机断言按一致性校验，不写死版本号） |

---

## 附：R10（v5.5.0）模块与运维增量

| 面 | 增量 |
| :--- | :--- |
| 前端装载 | `web/modules/util.js`（纯函数工具，167 行）→ `web/app.js`（8612 行）；两者均为经典脚本，全局函数作用域不变；静态套件统一经 `tests/load_web_sources.js` 按同序装载 |
| 纯函数模块 | `escapeActionText` / `escapeHtml` / `roundTo` / `formatStatVal` / `formatVolume` / `formatAmountYi` / `formatReal` / `estimateSvgTextWidth` / `layoutSubplotHeader` / `formatQuoteMoment` |
| CLI | 子命令 16 → 17：新增 `db-archive`（只读源库 + 在线备份 + 完整性/行数核验 + 可选 `VACUUM INTO` 紧凑副本 + `.manifest.json`；默认只增不删） |
| 备份产物 | `data/backups/db-archive/stock_database-<时间戳>[-标签][-compacted].db` 与同名 `.manifest.json` |
| 版本权威 | `/api/version`、`/api/status`、`/api/filter_schema`、导出包、大盘/宏观接口、启动横幅全部走 `current_version()`（逐请求按 mtime+size 校验），`APP_VERSION` 仅作启动日志初始值 |
