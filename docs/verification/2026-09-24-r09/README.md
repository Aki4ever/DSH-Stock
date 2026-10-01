# R09 验证证据（2026-09-24 · v5.4.0）

> 批次需求：**REQ-046**（顶栏「行情日期」精确到分）、**REQ-047**（副图标题与统计概要平铺不重叠）、**REQ-048**（本批符合管控机制）
> **后续补丁**：本批遗留项已在 [R09.1（v5.4.1）](../2026-09-24-r09-1/README.md) 中收口（首屏副图档位统一 / 默认仅回环监听 / 日志轮转 / R05 快照归档）。
> 交付版本：`v5.4.0`（`config/version.json` 为唯一版本权威）
> 验证对象：本机真实运行实例 `http://127.0.0.1:8888/`（真实来源行情，非构造数据、非 Mock）

## 1. 门禁结果

| 门禁 | 命令 | 结果 |
| :--- | :--- | :--- |
| Python 单元/接口测试 | `python3 -m unittest discover -s tests -p "test_*.py"` | **228 项 PASS**（本轮新增 `test_r09_quote_datetime.py` 10 项） |
| 前端静态回归 | `node tests/test_chart_integrity.js` / `test_detail_requests.js` / `test_layer_interaction.js` / `test_r04_chart_viewport.js` / `test_r08_chart.js` / `test_r09_subplot_header.js` | **6 套全 PASS**（本批新增 1 套） |
| 真机浏览器验证 | `node tests/browser_r09_verify.js` | **28/28 PASS**，控制台错误 0 |
| 旧批次真机回归 | `node tests/browser_r06/r07/r08_verify.js` | **39/39 · 44/44 · 40/40 PASS**（R09 探针修订后全绿，见第 4 节） |
| R05 历史快照 | `node docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js` | 9 项通过 / 11 项过时失败 / 后续中断 —— **非回归**（旧口径快照，见第 4 节留痕） |
| 需求台账 | `docs/requirements.md` R09 批次 | REQ-046 / REQ-047 / REQ-048 已登记且与上述用例双向绑定 |
| 数据安全 | —— | 本轮**零数据库写入 / 零迁移 / 零重建** |

复现命令（本目录截图与报告由第一条命令生成）：

```bash
bash scripts/ensure_server.sh
DSH_CDP_PORT=9396 DSH_SHOT_DIR=docs/verification/2026-09-24-r09 node tests/browser_r09_verify.js
python3 -m unittest discover -s tests -p "test_*.py"
```

## 2. REQ-046 证据：行情日期精确到分

接口实测（`GET /api/status`，2026-09-24 13:32 本机真实快照）：

```json
"snapshot_date": "2026-09-23",
"quote_date": "2026-09-24",
"quote_datetime": {
  "raw": "20260924133201", "date": "2026-09-24", "time": "13:32",
  "datetime": "2026-09-24 13:32", "display": "2026年9月24日 13:32",
  "precision": "minute", "source": "quote_snapshot"
}
```

- 顶栏徽标实测文本：`📅 行情日期: 2026年9月24日 13:32` —— 与 `quote_datetime.display` **逐字一致**（真机断言）。
- 徽标 `title`：`行情来源的真实快照时间（精确到分）· 原始值 20260924133201`（保留来源原始值可核对）。
- 行情来源说明同步到分：`腾讯证券行情 · 来源时间 2026-09-24 13:32 · …`。
- **口径分离**：`snapshot_date`（数据库基准批次 2026-09-23）与 `quote_datetime`（真实行情 2026-09-24 13:32）同时暴露、互不覆盖。
- 降级路径（静态用例逐条断言，不依赖运行期是否有该数据形态）：
  - `20260923`（只给日期）→ `precision=day`，界面只显示「2026年9月23日」，**不出现任何 HH:MM**；
  - `null` / `bad` / `1234` → 返回 `None`，界面显示「📅 行情日期未获取」，**不使用服务器本地时钟**。

截图：`01-header-minute-badge.png`（顶栏徽标位于页面左上，与版本徽标 v5.4.0 同排）。

## 3. REQ-047 证据：副图表头平铺、零重叠（浏览器实测包围盒）

判定方式：在真实渲染的 SVG 上用 `getBBox()` 取每段文字的**实际包围盒**，同一行内任意两段文字的横向交集 > 0.5px 即判为重叠；同时校验表头右缘不得越过副图背景框右缘。

| 图表 / 副图档位 | 标题 | 统计项 | 实测重叠 | 表头右缘 vs 绘图区右缘 |
| :--- | :--- | :--- | :--- | :--- |
| 个股日K（成交额） | `副图：成交额（含估算：均价×成交量）` | 5 | **0 处** | 825.9 ≤ 855 |
| 个股日K（成交量） | `副图：成交量` | 5 | **0 处** | 633.6 ≤ 855 |
| 个股日K（换手率） | `副图：换手率` | 5 | **0 处** | 585.8 ≤ 855 |
| 当日分时（成交量 / 成交额 / 换手率） | `副图：成交量` / `副图：成交额` / `副图：换手率` | 各 5 | **0 处** | 均在框内 |
| 大盘指数（分时） | `💰 副图: 成交金额 (亿元)` | 0（无统计项） | **0 处** | 框内 |
| 大盘指数（全部K线） | `💰 副图: 成交金额 (亿元)` + 不可得说明 | 1（如实标注） | **0 处** | 579.8 ≤ 1363 |

截图：`02-right-subplot-amt.png`（成交额档，可见 `副图：成交额（含估算：均价×成交量） 总和: …（含估算） 平均: … 地量(最小): … 天量(最大): … 中位数: …` 单行平铺）、`03-right-subplot-vol.png`、`04-right-subplot-turnover.png`、`05-timeline-subplot-header.png`、`06-index-timeline-header.png`、`07-index-kline-subplot-header.png`。

**修复前 → 修复后**（同一位置的真实对比，`02/07` 截图为修复后）：

| 位置 | 修复前 | 修复后 |
| :--- | :--- | :--- |
| 个股日K成交额副图 | 标题后缀 `（含估算：均价×成交量）` 与固定起点 `m.left+92` 的「总和」叠字 | 标题 + 5 项按实测宽度逐项定位，零重叠 |
| 副图「总和」 | 恒显示 `--`（读取了不存在的 `totalYi` 字段） | `总和: 1098.74亿（含估算）`，与窗口内样本同源同口径 |
| 指数副图刻度 | `3943379.8亿`（点位×成交量的量纲错误值） | `不可得` |
| 指数副图四维分布 | `平均: 2447529.69亿 …`（同上） | `当前来源未披露该指数成交额，四维分布不可得（不以点位×成交量推测值充当）` |
| 指数交易面积 | 以估算值求和（同样量纲错误） | 估算值整段剔除 → `交易面积: 未交汇`（不再以 `0.00亿` 冒充面积为 0） |

## 4. 本批同时完成的治理收口（R09 第二批）

除 REQ-046/047/048 外，本批把接手时登记的「文档与测试漂移」一并收口（**均无产品行为变更，除标注者外不需要新版本号**）：

| 事项 | 处置 | 证据 |
| :--- | :--- | :--- |
| R05 台账缺口（REQ-027~032 有代码无条目） | 按「代码引用点 + 测试断言 + 现行实测」三处交叉**实证回填**，REQ-033 明确作废不再分配 | `docs/requirements.md`「R05 台账」小节 |
| `docs/operations/product-entry.json` 落后（v4.5.0） | 重登记为 **v5.4.0**：变更摘要（v5.4.0 / v5.3.0）、门禁快照、源指纹、Web+CLI 双入口证据 | `live-entry.json`、`cli-status.txt`、`source-fingerprints.json` |
| R06 真机探针漂移（10 项） | 几何改为「viewBox 实测 + 最宽背景矩形」、缩放改为**点击真实浮动 ➕/➖ 按钮**（滚轮缩放已按产品需求移除），并新增 3 项断言 | `r06-rerun/browser-report.json`（39/39） |
| R07 真机探针漂移（6 项） | 改查唯一控件 `#chartSubPlotControlUnified`，断言改为「联动一致性 + 手选不被改写」，并如实登记首屏档位不一致的观察项 | `r07-rerun/browser-report.json`（44/44） |
| R08 版本断言写死 | 改为「徽标与 `/api/version` 一致」（断言一致性而非具体版本号） | `docs/verification/2026-09-23-r08/README.md` 的 R09 复跑小节 |
| R05 历史快照脚本的运行状态 | 实测留痕：9 项通过 / 11 项过时失败 / 后续 `TypeError` 中断，**非产品回归**；给出归档或重写的处置建议（未擅自实施） | `r05-snapshot/README.md` |

> **注意**：`r06-rerun/`、`r07-rerun/`、`r05-snapshot/` 为本批**过程留痕**（含早期失败迭代），正式结论已分别并入 `docs/verification/2026-09-23-r06|r07/README.md` 的「R09 后的…修订」小节与台账。

### 产品行为变更声明
本批对产品代码的唯一改动为 REQ-046/047/048 及其顺带缺陷修复（BUG-005）；测试探针与文档的修订**不改变产品行为**。**唯一的语义待决项**：统一「幅图联动」控件首屏高亮与当日分时默认档位不一致（观察项，见台账 R09 附表），本批**未擅自改动**。

## 5. 本目录文件

| 文件 | 说明 |
| :--- | :--- |
| `browser-report.json` | 真机验证原始报告（28 项逐条结果、耗时、控制台错误、截图清单） |
| `01-header-minute-badge.png` | REQ-046：顶栏「行情日期: 2026年9月24日 13:32」 |
| `02-right-subplot-amt.png` | REQ-047：个股日K成交额副图表头（标题 + 总和/平均/地量/天量/中位数）平铺 |
| `03-right-subplot-vol.png` | REQ-047：成交量档 |
| `04-right-subplot-turnover.png` | REQ-047：换手率档 |
| `05-timeline-subplot-header.png` | REQ-047：当日分时副图表头 |
| `06-index-timeline-header.png` | REQ-047：指数分时副图（标题独立成行） |
| `07-index-kline-subplot-header.png` | REQ-047 + REQ-032：指数K线副图（不可得如实标注 + 刻度「不可得」） |
| `live-entry.json` | 产品入口证据：`GET /api/status` 原样回读（v5.4.0、quote_datetime、标的数） |
| `cli-status.txt` | CLI 入口证据：`python3 scripts/dsh_stock_cli.py status` 原样输出（v5.4.0） |
| `source-fingerprints.json` | 本批源指纹：`config/` + `scripts/` + `web/` 共 61 个文件的 SHA-256 与 git revision |
| `r06-rerun/` · `r07-rerun/` | R06/R07 探针修订的**逐轮过程留痕**（含早期失败迭代与最终报告） |
| `r05-snapshot/` | R05 历史快照脚本的现行运行记录与处置建议 |

## 6. 未覆盖 / 遗留（如实登记）

- ~~R06/R07 硬编码探针~~ **本批已修完**（39/39 · 44/44，见第 4 节）。
- ~~`tests/browser_r05_verify.js` 仍留在 `tests/` 目录~~ **已归档**：移入 `docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js`，`tests/` 下不再存在该文件，避免被误当回归门禁（见 `r05-snapshot/README.md`）。
- 本批未改动服务监听地址（仍为 `0.0.0.0`）与鉴权策略；`server.log` 无轮转、产品库 58 MB 未归档 —— 均属运维优化项，需产品方决定。
- 统一「幅图联动」控件首屏档位高亮与当日分时默认档位不一致（语义待决项，未擅自改动）。
