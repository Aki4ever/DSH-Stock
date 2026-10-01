# BUG-004 · 详情图 TDZ 中断与副图估算口径回退（R08 后未登记改动引入）

状态：已解决（2026-09-24 本地技术验收；真机复验 R08 40/40 PASS）。关联 REQ-025 / REQ-031 / REQ-041；影响个股详情页全部 K 线图。

表现：打开个股详情显示「未加载」，日线图/周线图/季线图整张图不渲染，缠论买卖点标记 0 个；真机套件 `browser_r08_verify.js` 只跑到第 20 项即中断、仅 15 项通过（正常应为 40/40）。副图标题由「副图：成交额（含估算：均价×成交量）」退化为「副图：成交额（含估算）」。

根因：
1. `web/app.js` 的 `generateDailyKlineSVG` 中，`const windowAmount = computeWindowTotalAmount(klines)` 与 `const totalTurnover = ...` 被声明在**使用点之后**；换手率分支（第 6571 行附近）与成交额分支（第 6600 行附近）先引用后声明，触发 TDZ（`ReferenceError: Cannot access 'windowAmount'/'totalTurnover' before initialization`），异常中断整张 SVG 字符串的构建。
2. 同一批改动把 REQ-025 验收口径 `（含估算：均价×成交量）` 简写为 `（含估算）`。
3. 附带影响：`tests/test_detail_requests.js` 采用**源码切片**方式装载 `openStockDetail`，该函数新增引用切片外的 `resolveItemTurnoverRate`，套件报 `resolveItemTurnoverRate is not defined`。

修复：
1. 把两个常量声明上移到「四维分布概要」之前（`const subStats = ...` 上方），仅调整声明顺序，不改变任何语义与渲染结果。
2. 按 REQ-025 恢复副图标题口径为 `（含估算：均价×成交量）`。
3. 在 `tests/test_detail_requests.js` 沙箱内注入 `getStockCirculatingShares` 与 `resolveItemTurnoverRate` 的**同一份真实实现**（断言意图不变，只补依赖）。

验证：`python3 -m unittest discover -s tests -p "test_*.py"` 218 PASS；`tests/test_r08_chart.js`、`tests/test_r04_chart_viewport.js`、`tests/test_detail_requests.js` 由 FAIL 转 PASS（5 套 JS 静态套件全绿）；`node tests/browser_r08_verify.js` **40/40 PASS、控制台错误 0**，五类图级别标注与六类计数、周/季成交额逐日相加标注全部恢复。证据见[接手文档](../handoff/README.md)第五节。

防复发：
1. 图表函数内的 `const`/`let` 必须先于所有分支使用点声明；改图后必须跑真机套件，不能只看静态单测。
2. 需求已验收的**图上文案口径不得随意简写**，简写即等于口径变更，须同步台账与断言。
3. 采用源码切片装载的测试，新增跨切片依赖时要在沙箱注入真实定义，不得改写被测函数来迁就测试。
4. 每批改动必须提交 Git 并登记台账 —— 本次缺陷来自 R08 验收之后、未提交也未登记的改动（`web/app.js` 9/24 11:48、`web/index.html` 9/23 21:32、`web/style.css` 9/23 22:00）。
