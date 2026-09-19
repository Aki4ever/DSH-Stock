# DSH股票项目现状基线

基线编号：`DSH-BASELINE-20260919-01`；任务：`R01`；首次基线，无上一版。记录时间：2026-09-19，北京时间。本次只审查、验证和新增基线资料，未修复业务逻辑，也不代表发布验收。

**结论：项目已有可运行的 Web、CLI、数据库和采集能力，但数据真实性、日期语义、冷启动和访问边界存在已证实的缺口。可以以此为后续改动的比较起点，不能把当前版本定义为“全量真实数据且全部验收通过”的稳定版。**

## 1. 本次整体需求与成果

- 目标：摸清当前项目，为继续改动建立可追溯、可复现的基线。
- 范围：源码、既有需求、Git 工作区、数据库只读汇总、当前服务入口、原有测试与有界问题复现。
- 成果：[当前报告](README.md)、[回归与改动指南](regression.md)、[文件指纹](manifest.json)、[原始证据](evidence/)、[只读比较工具](verify_manifest.py)。
- 验收：关键结论有源码位置或日志；原有业务文件保留；未证实能力明确为待验证。
- 未执行：业务修复、数据库迁移、重启当前服务、重新全量采集、Git 提交/推送/标签、发布、交易操作。
- UI 视觉及点击全流程未验收；没有将 HTTP 200 或静态文件可读当成浏览器交互验收。

现有唯一需求台账仍是 [docs/requirements.md](../../requirements.md)。本报告是审查记录，不新建第二套生效需求，也不把修复建议直接视为已批准的新功能需求。

## 2. 当前可复用的版本锚点

| 项目 | 本次读回结果 |
| --- | --- |
| Git 分支 | `main` |
| HEAD | `f8b53aa9dd5985c0cdaf4463922a0c2fc336e1b7` |
| Web / config/version.json | `v4.3.0` |
| README / 架构文档 / CLI status | 仍为 `v1.0.0` |
| 缠论需求 REQ-007 | `v1.1.0`，已写进工作区台账，尚未提交 |
| 本地与 origin/main 跟踪记录 | ahead 0 / behind 0；未联网 fetch，不能代表远端实时状态 |
| 既有改动 | 2 个跟踪文件修改，14 个未跟踪文件，暂存区为空 |
| 运行入口 | `http://127.0.0.1:8888/`，本次首页及 JS/CSS 均 HTTP 200 |
| 服务身份 | PID 6427；状态 running；实际监听 `*:8888` |
| Python | 3.9.6；源码导入均为标准库及项目内模块；无需新增依赖安装 |

原有修改为 `data/stock_database.db`、`docs/requirements.md`。未跟踪内容包括 3 个缠论脚本、3 个制图脚本、4 张教学 SVG、3 个缠论报告/图表以及 `.watchdog.pid`。完整列表见 [git-initial.json](evidence/git-initial.json)。没有清理、暂存或覆盖这些文件。

本基线不是 Git 提交或发布标签。`manifest.json` 记录开始审查时 87 个文件的 SHA-256；数据库和 PID 被标为易变项。另有 `workspace-delta.tar.gz` 保存当时尚未提交的文档、代码和图表副本，排除数据库与 PID；其文件表与校验值见 `delta-bundle.json`。压缩包供查看、恢复前比较，不能直接覆盖解压到工作区。

数据库当前由服务管理。本次使用只读 SQLite 连接和 backup API 创建临时一致性副本做验证，交付包仅保留结构与汇总，不包含数据库恢复备份。原数据库的文件散列是观察值，不能代替数据库备份。

## 3. 实际架构与改动入口

| 模块 | 当前实现 | 改动会影响 |
| --- | --- | --- |
| Web 界面 | `web/index.html` 1,931 行，`web/style.css` 3,139 行，`web/app.js` 5,323 行 | 股票筛选、详情、K线/画线、股东、指数、宏观、采集控制 |
| HTTP 与筛选 | `scripts/stock_web_server.py` | 路由、筛选口径、进程状态、详情回补；导入模块即初始化数据并启动后台线程 |
| 本地存储 | `scripts/stock_db.py`，`data/stock_database.db` | 主表、行情、股东汇总、K线、分时、采集指纹与审计 |
| 采集和数据源 | `manual_crawler.py`、`anti_crawler.py`、`real_chart_engine.py`、`data_sources/` | 腾讯/东方财富/新浪行情及其他公开接口，超时和返回空值 |
| 财务与股东 | `company_finance_engine.py`、`shareholder_engine.py` | 财报、公司资料、持股结构、商誉及相关筛选；存在生成数据 |
| 宏观和指数 | `world_macro_engine.py`、`index_engine.py`、`dashboard_engine.py` | 宏观看板、指数详情、横截面统计；宏观事件/价格为代码内固定列表 |
| CLI 与报告 | `dsh_stock_cli.py`、`stock_reporter.py`、`stock_portfolio.py` | 自选、持仓、技术评分、SVG和日报；与Web使用的数据链路不完全一致 |
| 缠论 | 未跟踪的 `chanlun_core.py`、`chanlun_strategy_engine.py`、`chanlun_chart_svg.py`；另有 JS `generateChanlunOverlaySVG` | Python分析与Web画线各有实现，尚无一致性验收 |
| 生命周期 | `start_server.sh`、`stop_server.sh`、`watchdog.py` | 端口、PID和守护进程；不能随意用 stop 脚本测试当前服务 |

Web 主流程为：浏览器 → HTTP 处理器 → 内存股票字典/SQLite → 缺失数据时请求外部接口并写库 → JSON → 前端渲染。CLI 的分析与日报则直接使用另一条行情/拟真 K 线链路。股票详情 GET 也可能抓取并写库，因此本次未在现有服务调用详情或启动采集。

关键接口：GET `/api/status`、`/api/version`、`/api/filter_schema`、`/api/stock/{code}`、`/api/index/list`、`/api/shareholders/list`、`/api/dashboard/overview`、`/api/macro/world`、`/api/crawler/status`；POST `/api/filter`、`/api/server/start`、`/api/server/shutdown`、`/api/crawler/start`、`/api/crawler/cancel`。具体路由以源码为准。

CLI 现有 11 个子命令：`quote/list/analyze/portfolio/chart/holder/dividend/notice/blocktrade/report/status`。`--help` 与 `status` 可用；`--json status` 返回退出码 2（不支持 `--json`）。Web 多条件筛选、采集状态/审计、数据库诊断、统一版本和缠论没有对应的统一 CLI 命令。当前无需重建 CLI，后续优先补这些常用自动化入口。

## 4. 数据覆盖与可信边界

采样时刻为 2026-09-19 19:39 左右；数量是本地库统计，**不代表当日全市场完整性或每条记录真实性已验证**。

| 数据 | 实测范围 | 限制 |
| --- | --- | --- |
| 股票底册 | 4,601；上海 1,701、深圳 2,900 | 未与交易所当期全量证券名单核对 |
| 行情 | 4,601 条，价格均大于 0 | 行情时间字段为 2026-09-18 16:14–16:15；不能据接口的当天 snapshot_date 称为当天行情 |
| 股东汇总 | 4,605 条，报告期字段 2026-03-31 至 2026-09-08 | 行数多于底册；逐条来源和报告期正确性未核验 |
| 历史日 K | 727 行，仅 4 个标的 | 日期整体范围 2024-01-29 至 2026-09-18，不代表每个标的覆盖全区间 |
| 分时缓存 | 4 个标的，存储日期字段 2026-09-19 | 存储日期取系统当天，不能直接认定为实际交易日 |
| 采集指纹 | 4,601 个，类型均为 quote | 不是所有业务维度的完备血缘或真实性证明 |
| 采集审计 | 8 条：2 次全新更新、6 次免抓 | 免抓文案不是远端数据重新校验成功证据 |
| SQLite quick_check | `ok` | 只证明本次结构一致性检查通过 |

来源：[database-summary.json](evidence/database-summary.json)、[http-smoke.json](evidence/http-smoke.json)。本次不评判策略收益，也不核实固定宏观新闻是否真实发生。

## 5. 验证结果与需求对应

| 验证 | 实测结果 | 可证明的范围 |
| --- | --- | --- |
| 原有 unittest | **27/27 通过**，测试框架计时 14.678 秒 | 指标、持仓、旧CLI、报告和适配器当前断言通过 |
| Python AST | 43/43 文件可解析 | 语法可解析，不等于运行逻辑正确 |
| JavaScript | `node --check web/app.js` 退出 0 | 语法通过，不等于浏览器渲染、交互通过 |
| 只读 HTTP | 7/7 返回 200：首页、JS、CSS、status、version、filter_schema、crawler/status | 当前进程与所列入口响应成功 |
| 空数据库 | **失败** | 已复现初始化缺列，不能证明干净环境可启动 |
| 专项复现 | 日期筛选、盈利筛选、股东生成、断网档案、缓存TTL及K线LIMIT行为已记录 | 使用隔离副本和明确 fixture；未作为真实金融数据 |
| 缠论 | 空输入返回空信号；已有信号文件含19条，full_scan文件为空列表 | 没有几何算法、实盘信号有效性或Python/JS一致性的完整验收 |
| UI全流程 | 未执行 | 不提供视觉或交互通过结论 |

REQ-001～006 有旧实现与部分测试对应，但 README 的“19项”和“全模块100%覆盖”不足以描述当前系统。REQ-007 的“标准递归测试”“22支资产19个有效买点”只有文档/报告声明，`tests/` 无缠论测试。本次只确认文件里有19条记录，没有重跑扫描或确认交易有效性。

Web筛选、数据库迁移、后台刷新、股东生成、财务矩阵、前端画线等未被当前测试直接覆盖。适配器测试多用 `if data:` 再断言，返回空数据也可能通过；行情测试允许 Mock；CLI分析使用拟真K线。所以27项通过不能推出在线采集完整、真值准确或全产品验收通过。

## 6. 已确认问题与后续顺序

以下优先级是本次工程审查建议，不修改现有需求状态。

| 编号 | 优先级 | 发现及影响 | 证据 / 后续验收 |
| --- | --- | --- | --- |
| B01 | P1 | 财务矩阵按市值和固定比例生成；股东、异动、商誉按代码字符生成；公司资料断网返回固定法人和资本；宏观价格/事件为静态列表。与v4.3.0“全部真实”声明冲突 | `company_finance_engine.py:75`、`shareholder_engine.py:123`、`:326`、`world_macro_engine.py:174`；逐字段来源、报告期、采样时点和缺失状态必须可追溯 |
| B02 | P1 | 前端在持股占比低/高时重算数字，列表用46+seed，详情用48+seed；相同股票可显示不同生成值 | `web/app.js:1077`、`:3492`；列表/详情均展示同一可信字段，缺失明确unknown |
| B03 | P1 | `filter_date` 只写入返回标签；连续盈利年限仅依据PE和上市年限；日均交易额使用流通市值×换手率，并非指定周期历史均值 | `stock_web_server.py:319`、`:446`、`:461`、`:499`；固定样本核对历史截面、利润序列与均值窗口 |
| B04 | P1 | `init_db()` 未建 `dividend_total_amount`、`pinyin_abbr`，加载查询却直接依赖，空库失败 | `stock_db.py:43`、`:366`；干净目录初始化、旧库迁移和第二次幂等初始化均通过 |
| B05 | P1 | 行情后台主要补零价格；已有非空K线不会自动刷新；分时`max_age_seconds`未使用；同日免抓仅检查审计日期及数量阈值 | `stock_web_server.py:144`、`:249`、`stock_db.py:528`、`manual_crawler.py:77`；旧数据、跨日、断网恢复和手动刷新有独立验收 |
| B06 | P1 | 当前监听所有网卡；控制接口无身份校验，CORS为`*`；静态路径未约束在web目录内 | `stock_web_server.py:550`、`:580`、`:947`、`:1089`；只读请求`/web/../README.md`返回项目README，见static-path-check.json；修复后越界404/403，默认仅本机，控制入口边界可验 |
| B07 | P1 | 关键新功能没有回归测试；Python和JS缠论分叉；文档验收声明大于实际证据 | 当前tests目录和source-inventory.json；补同一固定样本跨端一致性、正常/异常/空数据用例 |
| B08 | P2 | README、架构、CLI版本与Web不一致；CLI缺少核心Web命令和JSON输出 | CLI实测日志及config/version.json；统一版本来源并提供最小自动化命令面 |
| B09 | P2 | `load_daily_klines(limit=N)` 按升序LIMIT返回最早N条，通常不符合“最近N条”使用预期 | `stock_db.py:484`；fixture的3天数据取2条返回前2天；先明确接口契约再修改 |
| B10 | P2 | start脚本支持自定义端口，看门狗写死8888；stop脚本会强杀端口占用者 | `start_server.sh:9`、`watchdog.py:24`、`stop_server.sh`；在隔离端口验证生命周期，禁止误杀非本项目进程 |

B01还影响CLI分析/图表/日报：`dsh_stock_cli.py:114`、`:190`及`stock_reporter.py:55`主动生成拟真K线。前端另有旧K线fallback函数，但本次只找到定义，未找到调用；不能把这些残留函数单独当成当前画线路径仍在造数据的证据。

建议改动顺序：先处理 B01/B02/B06 的真实性与访问边界，再处理 B04/B05 的初始化和时效，再校正 B03 的字段语义；每段同时补对应回归。之后统一缠论和CLI、同步版本与文档，最后再拆分大文件或优化外观。

规范检查器报告缺少统一入口、问题日志、CLI/UI索引和项目规则等。其“缺少docs/requirements/index.md”需结合本项目已有`docs/requirements.md`解读：不是完全没有需求台账。本次保留既有入口，不自动生成重复台账、不改规则、不宣布规范检查全部通过。

## 7. 下一次改动怎么使用

1. 从本报告选择一个问题或模块，确认对应生效需求；先看 [regression.md](regression.md) 中的影响范围。
2. 运行 `python3 docs/baselines/2026-09-19/verify_manifest.py`，检查与本基线相比哪些文件已变。
3. 业务代码、数据、测试分别核验；修复测试应从当前失败转为通过，不要把已知错误固化为应保留行为。
4. 保留本次基线，更新后续变更记录与实际证据；Git快照/提交需另按授权执行。

本次没有把建议的商业收益、行情实时性、全市场覆盖、新闻真实性或用户视觉验收写成已知事实。最终文件完整性和原工作区保留结果见 [delivery-verification.json](evidence/delivery-verification.json)。
