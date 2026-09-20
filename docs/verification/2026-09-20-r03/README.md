# R03 第一批 (P0) 本地验证记录 · v4.6.0

直接前版 v4.5.0。范围：REQ-014 画线图层化、REQ-015 重合置顶、REQ-016 数据中心多选删除、REQ-017 数据库基准、REQ-018 格式塔交互规范。
入口 http://127.0.0.1:8888/。本批不含任何新数据来源，全部为呈现层与口径层改动。

## 自动化门禁

| 套件 | 命令 | 结果 |
| :--- | :--- | :--- |
| Python 全量 | `python3 -m unittest discover -s tests` | 67 项 PASS |
| R02 完整性 | `PYTHONPATH=. python3 tests/test_r02_integrity.py` | 15 项 PASS |
| R03 数据中心 | `PYTHONPATH=. python3 tests/test_r03_data_center.py` | 9 项 PASS |
| JS 图形完整性 | `node tests/test_chart_integrity.js` | PASS |
| JS 详情时序 | `node tests/test_detail_requests.js` | PASS |
| JS 图层交互 | `node tests/test_layer_interaction.js` | PASS |

`python3 -m compileall -q scripts tests` 与 `node --check web/app.js` 通过，`git diff --check` 无空白问题。
所有构造数据仅存在于临时数据库与测试 fixture，未写入产品库。

R03 新增断言覆盖：成功批次的自动基准与全局唯一、部分覆盖/手动取消/旧版未核验日志不具备基准资格、手动切换基准与切回、无合规批次时不回退不伪造、旧库无 `is_baseline` 列的迁移、批量删除仅删指定行、基准记录受保护、缺失/非法 ID 容错、删除不触碰 `stocks_master` 与 `stock_daily_kline`；以及多模型共存、分模型清除互不影响、分模型显隐、重合轮换置顶、标签精准置顶、未命中不改状态、统一渲染器不产生 NaN。

## 真实接口回执

- `/api/status`：`snapshot_date=2026-09-20`、`snapshot_source=baseline`、`quote_date=2026-09-18`，基准批次 `#crawl_1789891698`。基准日期与真实来源日期分别呈现，未互相改写。
- 真实抓取两次（各 100/100 只）后，基准自动前移到最新批次（id 11 → 12），验证 REQ-017.2 默认策略；手动切回旧批次再切回，`/api/status` 与 `/api/crawler/baseline` 同步跟随。
- `POST /api/crawler/audit-delete` 传入基准 ID → `deleted=0 / protected=1`，提示「请先切换基准」；传入不存在 ID → `skipped=1`；传入旧版未核验日志 ID 设基准 → 400 且基准保持不变。

## 真实浏览器验证

`node tests/browser_r03_verify.js`（headless Chrome 148 + CDP，Node 内置模块，无三方依赖）→ **20/20 PASS**，页面控制台错误 0。
证据：[browser-report.json](assets/browser-report.json)，截图 [screenshots](assets/)。

覆盖：复选框列与全部记录对应、恰好一行基准徽标、基准口径条区分批次日期与行情日期、未选中时批操作条 `hidden=true / display=none`、勾选 1 条计数、表头全选 12/12、部分选中呈 indeterminate 半选态、基准删除保护、图层面板 8 行模型、三模型共存（自动 3 + 压力 1 + 支撑 1）、日线缺成交额时不生成且显式说明原因、SVG 实渲染条数与状态一致、清除压力线后自动线与支撑线保留、重合轮换置顶三连、重合标注出现、指数图层面板两模型、指数清除自动线后手动线保留。

## 已知边界（如实记录，不计为通过项）

- 自动多阶线依赖真实成交额：当前日线来源不提供成交额，故仅分时周期可测算自动线；该限制已在界面显式说明，未做任何推造。
- 历史「旧版日志（数据未核验）」不具备基准资格，是既有的 REQ-012 核验口径使然，非本批缺陷。
- 本批不涉及缠论买卖点增强、策略选股告警与持仓体检（R03 第二~四批，尚未实施）；金融收益与策略有效性不在本次技术通过范围。
