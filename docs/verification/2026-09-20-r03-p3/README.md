# R03 第四批 (P3) 本地验证记录 · v4.9.0

直接前版 v4.8.0。范围：REQ-021 持仓组合风险体检与动态止盈止损，以及 PID 文件/看门狗端口化加固。
入口 http://127.0.0.1:8888/。

## 自动化门禁

| 套件 | 结果 |
| :--- | :--- |
| `python3 -m unittest discover -s tests` | 173 项 PASS |
| `PYTHONPATH=. python3 tests/test_r03_portfolio_checkup.py` | 31 项 PASS |
| `PYTHONPATH=. python3 tests/test_r03_screener_alerts.py` | 43 项 PASS |
| `PYTHONPATH=. python3 tests/test_r03_chanlun_signals.py` | 32 项 PASS |
| `PYTHONPATH=. python3 tests/test_r03_data_center.py` | 9 项 PASS |
| `PYTHONPATH=. python3 tests/test_r02_integrity.py` | 15 项 PASS |
| Node 三套件（图形完整性 / 详情时序 / 图层交互） | 全部 PASS |

REQ-021 新增断言的关键价值：**门禁不可被绕过**——`portfolio_verified` 为 `None`/`False`/`0`/`"true"`/`"True"`/`1` 时全部拒绝，只有字面 `True` 通过；未核实时 `positions` 与 `summary` 必须为空且响应体不含底册中任何证券名或成本价；体检流程对配置文件的字节内容零改动（防止系统自行打上「已核实」标记）。**「无法判定」与「未触发」必须分离**：缺数据时规则状态为 `unavailable`，逐一断言之。

## 双实例门禁对照（真实浏览器）

由于真实持仓底册的 `portfolio_verified` 尚未由用户设置，验证分两路进行，且**不触碰真实配置**：

1. **默认实例 127.0.0.1:8888（未核实真实底册）** → 门禁生效。浏览器 11/11 PASS：门禁条显示且明确引用 `portfolio_verified`；汇总条不显示；表格不产出任何持仓行；持仓计数为 `0 只`（不虚报）；接口返回 `status=unverified`、`positions=[]`、`summary={}`、`portfolio_declared_count=3`；响应体经正则断言**不含** `1580`/`192.5`/`255.0`/贵州茅台/宁德时代/比亚迪任何一项。证据 `01-portfolio-unverified-gate.png`、`browser-report.json`。

2. **临时实例 127.0.0.1:8890（指向一份 3 条持仓、`portfolio_verified=true` 的临时底册副本）** → 完整渲染路径。浏览器 15/15 PASS：门禁解除、组合概览含危险/警示/无法判定计数、3 行持仓、18 条规则全部渲染、规则按**危险 2 / 警示 8 / 达标 1 / 未触发 7** 四类语义分别着色（合计 18，与后端触发计数一致）、日线非最新时逐只标注、规则文案给出真实数值与阈值、筛选交互正确、页面无任何买卖建议式措辞。证据 `02-portfolio-verified-full.png`、`03-portfolio-risk-only.png`、`browser-report-verified.json`。

3. **交叉对照**：在方案 2 运行期间回查默认实例，仍为 `status=unverified`、`positions=0`、`summary` 空 —— 证明验证实例的临时底册**没有污染**真实配置。验证结束后临时底册目录已删除，`git diff config/stock_config.json` 为空。

## 本轮验证发现并修复的真实缺陷

1. **「止盈达标」被渲染成风险色**：前端对「已触发且非 DANGER」的规则统一使用警示色，于是 `S1_take_profit`（盈利达标，正向信号）与真实风险信号视觉上无法区分——违反 Gestalt 相似性原则，会让用户把达标误读为警报。触发点是浏览器断言中的计数不匹配（后端触发警示 8 条，前端着色 9 条）。已改为五类语义分别着色（危险/警示/达标/信息/无法判定/未触发）。
2. **多实例共用 PID 文件导致停错进程**：`.server.pid` 被写死为单一文件，临时测试实例启动时**覆盖**了默认实例的 PID 文件，其后 `stop_server.sh` / `watchdog.py` 会依据错误 PID 判断存活甚至误杀。这不是测试环境的偶发问题，而是同机多账户/多底册场景下的真实运维风险。已按端口区分 PID 与看门狗文件（默认端口沿用原文件名以保持向后兼容）。
3. **`stop_server.sh` 中 `PORT` 先使用后定义**：变量在判断非默认端口分支时尚未赋值，`${PORT:-8888}` 恒等于 8888，导致非默认端口实例**永远停不掉默认实例而误杀/误判**。已调整定义顺序。
4. **引擎不可被测试注入**：`portfolio_checkup` 把 `get_batch_quotes`/`fetch_daily_bars` 写成函数内局部导入，测试无法替换真实来源，等于该模块的判定层无法离线验证。已提升为模块级导入（与 `stock_portfolio.py` 既有做法一致）。
5. **日线来源故障时结构数据被整体丢弃**（承 P2）：体检复用 P2 建立的 `stale` 口径，慢变量规则（MA20、峰值回撤）在来源不可用时仍可参考并逐只标注，而不是无谓熄火。

## 持仓底册状态（用户已确认，见 v4.9.1）

`config/stock_config.json` 中原有的 3 条持仓经**用户确认是占位数据而非真实持仓**。据此底册已清空为 `"portfolio": []` 且 `"portfolio_verified": false`，功能保持门禁关闭。

本项目**不代替用户认定持仓真实性**，也从不自行置位该标记（有测试断言配置文件字节零改动）。因此「已核实」路径的验证是在**临时底册副本**上完成的；真实持仓上的体检结论尚未产生，也不应被当作已产出。

空底册下的浏览器验证：**9/9 PASS**，证据 `04-portfolio-empty.png`、`browser-report-empty.json`。覆盖门禁条引用「未配置任何持仓」、不显示汇总数字、不产出持仓行、计数如实为 0 只、数据口径提示为「等待持仓核实」、空底册与已填未核实两种引导文案被区分、接口如实返回 `unverified` 且 `portfolio_declared_count=0`、规则版本与免责声明仍下发。

## 已知边界（如实记录）

- 空底册下无法产出任何体检结论，这是设计意图而非缺陷；待用户填写并核实真实持仓后启用。
- 峰值回撤规则受数据覆盖区间限制：若买入日早于来源覆盖起点，标注 `peak_coverage_incomplete`，峰值可能被低估。
- 规则阈值（+20% / -8% / ±5% / MA20 / 8%）为**纪律参数**，未经任何回测或有效性评估；本项目不承诺收益，也不声称这些阈值适合任何人的风险偏好。
