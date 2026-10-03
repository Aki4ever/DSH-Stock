# R13 需求文案与实施记录（已落地 · v5.7.0）

> 状态：`[ACTIVE]` **实施阶段已完成**（2026-10-02）。需求文案 → 物理实现 → 自动化 + 真机验证全链路闭环。
> 行号锚点以 2026-10-02 工作树为准（`web/app.js` 9015 行 / `web/style.css` 3855 行 / `web/index.html` 2622 行）。
> 需求来源：用户口述两条（截图 image1＝控制栏、image2＝副图信息条）→「简化成更利于执行的需求文案」后按文案实施。

---

## 一、根因证据（实跑，非推测）

### REQ-097（「努力与结果」按钮无反馈）

| 判据 | 方法 | 实测结果 |
| :--- | :--- | :--- |
| 截图视窗根数 | 截图底部「(30 周期)」+ `panelEffectiveCount` 下限 30（`app.js:6436`） | 视窗 = **30 根**（2026-08-19 ~ 2026-09-30） |
| 真实数据复算 | 取 `/api/stock/601939` 的 4606 根真实日线，原样复跑 `calculateWyckoffEffortResult`（`app.js:5965`） | 该 30 根内 **0 命中**；effort 最大仅 **1.26x**，阈值要求 **≥1.65x** |
| 视窗放宽 | 同上，取末 60 / 200 / 全量 | 60 根 **0** · 200 根 **1**（2026-03-03） · 全量 4606 根 **71** |
| 图层渲染条件 | `app.js:7166` `(showAmtDraw \|\| showEffortDraw)` → `generateFirstPrinciplesOverlaySVG` | 图层确实被调用，但 **`signals` 为空 → 循环体不产出任何 SVG** |
| 零命中时的反馈 | 通读 `app.js:6086-6115` + `6130-6138` | **无空状态文案、无图层状态徽标**；仅 1.9s `showChartToast`（`app.js:3388`，浮动在面板右上角、不在图内）与按钮高亮 |

**结论**：不是渲染链路坏了，而是「**默认/最小视窗下必然零命中** ＋ **零命中时图层零反馈**」两者叠加。另有 2 处口径缺陷：① `reason` 文案写「20日均量」而代码用 **15 根**切片均值（`app.js:5972/6008`）；② `anomalyIndices` 仅用于**副图异动柱高亮**（`app.js` 副图柱分支），主图上除买卖点标记外**没有任何图层状态指示**（开/关在图上不可辨）。

### REQ-098（副图信息条文字过小）

| 判据 | 方法 | 实测结果 |
| :--- | :--- | :--- |
| 字号来源 | `app.js:5596 / 5609`（分时副图表头）、`6975 / 6991`（K线副图表头）、`7948`（指数） | 全部硬编码 `fontSize: 10` |
| 屏显缩放 | `style.css:3539` `.chart-svg-host svg { width:100%; height:auto }` ＋ `style.css:3528` `.dual-panel .chart-panel { flex: 1 1 50% }` | viewBox 920 → 双栏面板 ≈660px，缩放系数 **≈0.72** |
| 实际屏显字号 | 10 × 0.72 | **≈7.2 CSS px**（这才是「看不清」的物理原因，非单纯字号小） |
| 排版约束 | `web/modules/util.js:73-135` `layoutSubplotHeader`，`rowPitch = fontSize + 2`，`maxRows` 默认 3 | 字号翻倍后「长标题 + 5 项统计」在 730px 内宽**必然换行 2~3 行**（44~66px），当前 `subHeight=125` 放不下 |
| 连带几何 | `app.js:4983-4987`：`920×540` / `mainHeight 350` / `subHeight 125`；柱高压缩量 `(rows-1)*12`（`app.js:6980`、`5601`） | 按 12 计（而非 `22`）会**把柱子压到表头下**；必须同步放大画布与压缩公式 |

---

## 二、简化后的需求文案（L0 · 一句话可验收）

- **REQ-097**：让「⚡ 努力与结果」图层的开/关在 **K 线主图内**有确定性可见反馈；**当前视窗零命中时必须显式说明零命中及其阈值口径**，不得静默无反应。
- **REQ-098**：把 K 线图（含分时图）副图信息条红框内文字**放大到 2 倍**（屏显 ≥2×），并**同步放大画布/副图高度**以保证不裁剪、不重叠、不压柱。

---

## 三、递归分裂到物理实现层（L1 执行层 → L2 物理落点）

> 判定标准：每一层都必须落到**具体文件 + 具体函数/行**，否则继续分裂。

### REQ-097

| 层 | 落点 | 具体动作 |
| :--- | :--- | :--- |
| L2-1 图层状态徽标 | `web/app.js:7166` 叠加层入口 → `generateFirstPrinciplesOverlaySVG`（`app.js:6029`） | 图层**开启即渲染**状态徽标 `<g class="effort-layer-badge">`：主图左上角输出「⚡ 努力与结果 已开启 ｜ 本视窗异动 N 根 / 买 X 卖 Y」；关闭时输出灰态「已关闭」。使「开→关」在图上**必然**产生 DOM 差异（可断言）。 |
| L2-2 零命中空状态 | `web/app.js:6086-6115`（effort 分支） | `signals.length === 0` 时输出空状态 `<text class="effort-empty-note">`：`本视窗未识别到「天量窄实体」异动（阈值：量≥1.65×15日均量 且 实体≤0.65×均实体或实体/振幅≤35%）`。阈值文案必须由**同一份常量**生成，禁止手写复述（防口径漂移）。 |
| L2-3 口径对齐 | `web/app.js:5972`（切片 15 根）vs `6008/6017`（文案「20日」） | 二选一并对齐：切片改 20 根，或文案改「15 日均量」。**默认取「切片改 20 根 + 文案同步」**（与既有文档口径「20日均量」一致）。 |
| L2-4 异动柱可见化（**核查后确认已存在，本轮不动**） | `web/app.js` 副图柱分支（`effortData.anomalyIndices.has(idx)`） | 规划阶段曾判「已算未用」，**实施期核查纠正**：`anomalyIndices` 早已用于副图异动柱高亮（半透明描边 + 柱顶 ⚡）。真正缺的是**主图上的图层状态指示**，已由 L2-1 补上。 |
| L2-5 交互一致性 | `web/app.js:6130-6138` `toggleEffortDraw` + `4812-4819` `syncPanelToolbar` | toast 文案补「本视窗命中 N」；按钮 `active` 态、左右双面板、toast 三者同源同一状态；避免二次计算导致徽标数 ≠ toast 数。 |
| L2-6 阈值语义（**需用户决策，禁止擅自改判定语义**） | `web/app.js:5990` `isAnomaly` | 方案 A（默认、最小改动）：阈值不动，只加反馈；方案 B（可选）：分级展示——「强信号（现阈值）」与「弱信号（如量≥1.3× 且 实体/振幅≤35%）」分色，默认只显示强信号。 |

### REQ-098

| 层 | 落点 | 具体动作 |
| :--- | :--- | :--- |
| L2-1 字号翻倍 | `web/app.js:5596`、`5609`、`6975`、`6991`、`7948` | `fontSize: 10 → 20`（严格 2 倍）；标题 `titleFontSize` 同步（分时/K线一致）。 |
| L2-2 画布同步放大 | `web/app.js:4983-4987` | `height 540 → 620`、`subHeight 125 → 190`（`mainHeight 350` 保持或微增）；分时图与 K 线图共用同一组常量，天然同步。 |
| L2-3 柱高压缩公式 | `web/app.js:6980`、`5601` | `(subHeaderRows - 1) * 12` → 按新行距 `fontSize + 2 = 22` 计（如 `(rows - 1) * 22`），保证表头永不压柱。 |
| L2-4 同行小字对齐 | `web/app.js:6997/7004/7013/7017`（副图底部「总成交额 / 含估算」行，现 `font-size:10`）与副图 Y 轴刻度标签 | 红框同行文字统一放大到 18~20，避免「表头大了、注释还是 7px」的层级撕裂。 |
| L2-5 屏显复核 | `web/style.css:3539` 缩放链 | 改后实际屏显 ≈ `20 × 0.72 = 14.4 CSS px`（≥2×）；单栏占满（`.single-panel`）与双栏均需截图复核不溢出。 |

---

## 四、验收标准（可测量 · 不认自述）

| 编号 | 验收判据 |
| :--- | :--- |
| R-097-A | 默认 30 根视窗下，连续点击 2 次按钮：主图 SVG 内 `effort-layer-badge` **存在性发生翻转**（DOM 断言）。 |
| R-097-B | 零命中时图上出现裸眼可见空状态文案，且文案里的阈值数字与该函数实际使用的常量**同源**（改常量即改文案）。 |
| R-097-C | 按钮 `active` 态、左右两面板徽标、toast 文案三者状态一致。 |
| R-097-D | 真机（服务端 `127.0.0.1:8888` 在跑）实点实测：图层开→关，主图 SVG 文本节点数变化 **≥1**，控制台 **0 异常**。 |
| R-098-A | 源码与渲染后 SVG 双断言：副图表头 `font-size ≥ 20`；屏显高度 ≥ 2× 原值。 |
| R-098-B | 表头各行与副图柱顶、画布四边**零重叠、零裁剪**（新增自动化断言：表头行数 × 行距 ≤ 预留高度）。 |
| R-098-C | `tests/test_r09_subplot_header.js`、`test_r04_chart_viewport.js`、`test_r08_chart.js`、`test_first_principles_signals.js` 全绿；Python 全量 + 8 套前端静态套件全绿。 |
| R-098-D | 画布放大后十字光标、缩放、画线命中、tooltip 仍与几何一致（`bindChartCrosshair` / `bindChartZoomAndDrawing` 与渲染共用同一组常量）。 |

### 回归面（写代码前先锁定）

- `tests/test_r09_subplot_header.js`：直调 `layoutSubplotHeader({fontSize:10})` 的「单行零重叠」断言**不受影响**（`util.js` 不动）；但 `assertNoOverlap` 在真实 SVG 上按 `fontSize=10` 反推宽度，字号翻倍后会**假通过** → 必须新增"表头 vs 副图柱不重叠"断言，否则等于没测。
- `tests/test_first_principles_signals.js`：正则抽取 `calculateWyckoffEffortResult` 函数体在沙箱执行 → 改动函数签名/依赖外部常量会**直接打断抽取**，需同步。
- 无任何测试钉住 `920×540/350/125` 几何常量（已核查）→ 画布放大不会引发既有断言失败，但必须补截图证据。

---

## 五、连带与风险（如实登记）

1. **指数页同源**：`app.js:7948` 与个股共用排布器，字号改动会**连带放大指数副图表头**（属预期连带，需登记并复核）。
2. **行号漂移**：锚点为 2026-10-02 工作树；改前需重新核对。
3. **双栏/单栏差异**：双栏 ≈0.72 缩放、单栏接近 1.0，2× 字号在单栏下可能偏大 → 以真机截图判定，必要时按面板宽度自适应（`fontSize = clamp(20, panelWidth/46, 24)`）。
4. **版本与台账**：进入实施批次时应同步 `config/version.json`、本台账与 `docs/operations/product-entry.json`，建议版本 `v5.7.0`（本轮规划阶段**未动**）。
5. **首动改名受阻**：本会话标题实跑 `./scripts/rename_session.sh` 返回 `unauthorized`（宿主 Web RPC 需鉴权 token；本工程该脚本为**旧版**：method `session.rename`、URL `/api/session.rename`、无 cookie），权威版为全局 `name_me.sh`（从 Electron Cookies 取 `dsh-auth-*` + method `session/rename`）。直写会话存储又被宿主实时重写（`seq` 407→432 持续递增，edit 因 FS_STALE 被拒）→ 命名锁定交由前端/终端侧完成，如实登记为宿主限制（与 R12「子会话宿主限制不可改名」同类）。

---

## 六、实施记录与验证证据（2026-10-02 · v5.7.0）

### 改动清单（写文件范围不重叠，均为最小必要改动）

| 文件 | 改动 |
| :--- | :--- |
| `web/app.js` | ① `calculateWyckoffEffortResult`：阈值常量收敛为函数内 `threshold`（`avgBars:20 / volRatioMin:1.65 / resultRatioMax:0.65 / bodyRangeMax:0.35`）并随返回值输出，循环起点与切片统一到 `avgBars`，reason 文案 `${threshold.avgBars}日均量` 同源；② 新增 `effortThresholdText(threshold)`；③ 叠加层新增 `effort-layer-badge` 状态徽标（`data-state`/`data-signals`/`data-anomalies`）与 `.effort-empty-note` 两档空状态；④ `toggleEffortDraw` toast 报出「本视窗命中 N 个」；⑤ 新增 `SUBPLOT_HEADER_FONT_SIZE=20` / `SUBPLOT_HEADER_ROW_PITCH=22` 常量，4 处副图表头与副图刻度标签全部走常量；⑥ 画布 540→620、`subHeight` 125→190、`margin.left` 65→112；⑦ 柱高压缩改 `sh - 8 - rows×22`；⑧ 重合图提示行下移（`m.top+42`→`+66`）避让徽标 |
| `tests/test_r13_effort_layer_feedback_and_font.js` | 新增静态回归（阈值同源 / 开关必有 DOM 差异 / 零命中与「有异动无买卖点」两档提示 / toast 命中数 / 字号=20 / 表头不压柱 / 刻度标签不裁切 / 画布尺寸，共 25 项断言） |
| `tests/browser_r13_verify.js` | 新增真机验证（26 项：真实点击开→关→开、徽标翻转、toast、字号实测 getBBox+getScreenCTM、零重叠、不越界） |
| `tests/browser_r09_verify.js` | 载体修复两处：① `captureScreenshot` 加超时+降级（本机 headless Chrome 148 下原实现会**无限挂起**）；② 同行判定由「包围盒纵向相交」改为**基线相等**（字号 20 后行距 22 < 字框高 23.8，原判据会把相邻行误判为同行 → 假重叠） |
| `config/version.json` · `docs/operations/product-entry.json` · `docs/requirements.md` | 版本归位 `v5.7.0` + 需求台账登记 |

### 验证判据（全部可复跑）

| 判据 | 命令 | 实测结果 |
| :--- | :--- | :--- |
| Python 全量 | `python3 -m unittest discover -s tests -p "test_*.py"` | **311 PASS（skipped 2）** |
| 前端静态套件 | `node tests/test_*.js`（9 套） | **9/9 PASS**（含新增 R13） |
| 真机 R13 | `node tests/browser_r13_verify.js` | **26/26 PASS** · 控制台 0 异常 |
| 真机 R09 回归（REQ-047 同源区域） | `node tests/browser_r09_verify.js` | **28/28 PASS** · 控制台 0 异常 |
| 运行期版本 | `curl -s http://127.0.0.1:8888/api/version` | `v5.7.0`（与 `config/version.json` 同源，REQ-054 即时生效） |
| 真机点击链路 | R13 探针：`#btnEffortDraw_right.click()` | `data-state on→off→on` · 文本节点 29→28 · toast「已隐藏」→「已开启（本视窗命中 0 个）」 |
| 零命中反馈 | 同上（30 根视窗，真实命中 0） | 图上出现「本视窗未识别到「天量窄实体」异动（口径：量≥1.65×20日均量 且 实体≤0.65×均实体（或实体/振幅≤35%））」 |
| 有异动时反馈 | R13 探针 `switchKlineCount(180)` | 徽标「异动 1 根」· 副图异动柱高亮 1 根 · 提示「检出 1 根…均未构成买/卖点」三者一致 |
| 屏显字号 | R13 探针 `getScreenCTM().a × font-size` | 缩放 0.7563 · **7.56 → 15.13 CSS px（严格 2×）** |
| 放大后布局 | R13 探针 `getBBox()` | 同行重叠 **0 处** · 表头不越界 · 刻度标签 `x=15.9 ≥ 0`（未被左缘裁切） |

### 如实登记的边界（不美化）

1. **本轮无真机截图**：本机 headless Chrome 148 下 `Page.captureScreenshot` 会无限挂起（已加 15s→6s 超时并降级 `fromSurface:false`，两次仍失败即快速跳过）→ 两份真机报告的 `shots` 为空，判据全部来自 DOM / `getBBox()` / `getScreenCTM()` 实测，已在报告 `note` 字段写明。历史批次截图仍可复跑（`docs/verification/2026-09-24-r09/`）。
2. **指数页未同步放大**：`app.js` 指数副图表头仍为 `fontSize: 10`（唯一残留），因其布局与个股不同且本轮无该页基线截图；用户红框指向的是**个股 K 线图**，故不动并登记为后续项。
3. **副图底部注释行未放大**：`总成交额 / 含估算 N 根` 与右侧 `⚠️ 其中 N 根…` 同行右对齐，20px 下两段文字实测宽度和 > 绘图区宽（会重叠），故本轮保持 10px；如需放大必须先把这两句改成两行排布（另立需求）。
4. **跨行字框相触**：字号 20 时行距 22px < 字框高 23.8px，相邻两行 em 框相触约 1.8px（真机实测 4~6 处），**字形本身不相碰**（CJK 字面高约 14px）。如需更松的行距需给 `layoutSubplotHeader` 增加 `rowPitch` 选项（本轮未动 `util.js`）。
5. **单栏模式未实测**：双栏缩放 0.7563 已实测；单栏（`.single-panel`）缩放接近 1.0，2× 字号在该模式下会更醒目，未单独截图验证。
6. **均量基准由 15 根改 20 根**：属口径对齐（代码原先与「20日均量」文案不一致），会轻微改变命中集合；**判定阈值（1.65×/0.65×/35%）未改**。历史命中数参考：601939 全量 4606 根 71 个信号（新口径）。
