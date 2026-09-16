# DSH 股票量化监控与投资组合分析工程 (DSH Stock)

> ### 🏷️ **版本信息与实施追踪**
> - **当前系统实施总版本**：`v1.0.0`
> - **维护团队**：DSH 量化生态与智能体工程组
> - **最后更新日期**：2026-09-16
> - **版本状态**：`[Release 稳定生效]`

---

## 🚀 项目 DSH 赋能规划卡

> ### 🚀 **新项目 DSH 赋能规划卡** `[ DSH股票 / DSH-STOCK-QUANT ]`
> ────────────────────────────────────────────────────────────
> - 📌 **项目业务定位**：面向中国 A 股主板/创业板/科创板、主要大盘指数及自选组合的实时行情追踪、100 分制多空量化评分、持仓盈亏分析、风险止盈止损预警及零依赖矢量 SVG 走势图表出具中枢。
> - 🌲 **选用的 DSH 宿主能力维度 (已选用 3 项)**：
>   - [x] **1. CLI 命令行与终端基座**：封装为全功能标准化 CLI 终端工具（`scripts/dsh_stock_cli.py`），提供色彩丰富的行情查询、组合体检、参数校验与标准退出码门禁。
>   - [x] **2. 宿主 API / RPC 网关联动**：集成 DSH 会话重命名 RPC（`scripts/rename_session.sh`），在执行关键看盘与量化任务时锁定侧边栏标题。
>   - [x] **3. 动态 Agent Skill 技能包**：在 `skills/` 输出标准 `SKILL.md` 与 Schema 规范，使 DSH 智能体能自然语言秒级调用行情获取、量化打分与图表研报生成能力。
> - 🔌 **具体集成与落地方式**：
>   - 接口契约：提供 `python3 scripts/dsh_stock_cli.py <quote|list|analyze|portfolio|chart|report|status>` 命令行。
>   - 数据流转：实时对接腾讯/新浪公开金融接口（带离线 Mock 降级保护），零依赖纯 Python 标准库驱动，自动渲染独立 SVG 矢量图表并输出 Markdown 研报。
>   - 原生可视化呈现：在 DSH Web 终端呈现 ANSI 彩色涨跌表与进度条，在会话尾部输出可直接点击的 SVG 走势图与研报路径。
> - 📈 **预期效能增益**：实现秒级获取行情与多空量化体检，告别繁重的商业炒股软件等待，零外部三方依赖安装，单测 0.6 秒全量绿灯，大幅提升投资决策与风险预警效率。

---

## 📁 目录架构全景

```text
.
├── config/                      # 核心配置中心
│   ├── stock_config.json        # 监控指数、自选股池、持仓底册、预警规则与指标参数
│   └── README.md                # 配置中心说明
├── scripts/                     # 核心业务引擎与运维脚本
│   ├── stock_data_engine.py     # 实时/历史行情数据引擎 (腾讯公开接口 + 拟真K线 + Mock回退)
│   ├── stock_indicators.py      # 技术指标计算库 (MA/MACD/RSI/BOLL/KDJ) 与 100分制量化模型
│   ├── stock_portfolio.py       # 持仓投资组合管理与多维风险/止盈止损预警中枢
│   ├── stock_chart_svg.py       # 原生纯 SVG 矢量 K线/均线/成交量走势图生成引擎
│   ├── stock_reporter.py        # 每日全盘分析研报生成器 (Markdown + SVG 直达)
│   ├── dsh_stock_cli.py         # 标准化全功能 CLI 命令行交互终端
│   ├── rename_session.sh        # DSH 会话重命名 RPC 辅助脚本
│   └── README.md                # 脚本目录说明
├── reports/                     # 研报与图表归档目录
│   ├── stock_report_YYYY-MM-DD.md # 每日综合行情研报
│   ├── charts/                  # 自动生成的矢量 SVG 走势图表
│   └── README.md                # 报告目录说明
├── docs/                        # 说明文档与核心台账
│   ├── requirements.md          # 独立核心需求管理台账 (REQ-001 ~ REQ-006)
│   ├── architecture.md          # 总体架构设计、量化打分模型与接口契约
│   └── README.md                # 文档目录说明
├── tests/                       # 自动化测试与质量门禁 (100% 绿灯)
│   ├── test_stock_data.py       # 行情获取与代码标准化测试
│   ├── test_stock_indicators.py # 经典技术指标与评分数学公式验证
│   ├── test_stock_portfolio.py  # 持仓盈亏计算与风险预警测试
│   ├── test_stock_cli.py        # SVG 渲染、研报输出与 CLI 子命令测试
│   └── README.md                # 测试目录说明
├── skills/                      # DSH Agent 动态技能包
│   ├── stock_skill.json         # 技能清单与能力边界 Schema
│   ├── SKILL.md                 # 智能体调用与反例约束规范手册
│   └── README.md                # 技能目录说明
├── .gitignore                   # Git 版本忽略配置
├── .gitattributes               # 换行符与文件属性配置
└── README.md                    # 本工程主说明文档
```

---

## 📊 100 分制多空量化评分模型

系统综合四大维度评估股票的多空强度与风险系数（满分 100 分）：

| 维度 | 权重 | 评估指标 | 关键多空特征与评判依据 |
| :--- | :---: | :--- | :--- |
| **1. 趋势面** | 35分 | 移动均线 (MA5/10/20) 排列形态 | 多头排列得 35分；短期金叉站上 MA20 得 28分；均线缠绕得 20分；空头排列得 6分 |
| **2. 动量面** | 25分 | MACD (DIF/DEA/柱状线) 动能 | 零轴上方红柱扩张得 25分；多头延续得 20分；绿柱收敛金叉得 16分；空头杀跌得 4分 |
| **3. 均线与支撑面** | 20分 | 布林带 (BOLL) 通道与中轨位置 | 运行于布林中轨上方得 19分；突破上轨加速得 15分；跌破下轨超跌得 8分 |
| **4. 波动与风险面** | 20分 | RSI-6 相对强弱与超买超卖 | 45~68 良性进攻区得 20分；>80 极度超买扣分至 10分 (追高风险)；<25 超卖反弹得 14分 |

### 评级分类与操作指引
- 🟢 **85 ~ 100 分**：`【强烈看多 · Strong Bullish】` 多头共振加速，建议积极顺势配置。
- 🔵 **70 ~ 84 分**：`【偏多进攻 · Bullish】` 上升通道保持良好，逢回调中轨分批介入。
- 🟡 **50 ~ 69 分**：`【震荡蓄势 · Neutral】` 多空胶着均势，建议控制半仓观望。
- 🟠 **35 ~ 49 分**：`【偏空防御 · Bearish】` 下行承压明显，注意逢反弹减仓避险。
- 🔴 **< 35 分**：`【高危回避 · Strong Bearish】` 破位杀跌形态恶化，严守止损纪律，空仓回避。

---

## 🛠️ 快速上手与操作指南

### 1. 查询股票实时行情 (支持批量查询与指数)
```bash
python3 scripts/dsh_stock_cli.py quote 600519 300750 sh000001
```

### 2. 查看核心指数与重点自选股池
```bash
python3 scripts/dsh_stock_cli.py list
```

### 3. 对单只股票进行 100 分制多空量化深度体检
```bash
python3 scripts/dsh_stock_cli.py analyze 600519
```

### 4. 检查投资组合持仓、浮动盈亏与止盈止损预警
```bash
python3 scripts/dsh_stock_cli.py portfolio
```

### 5. 生成矢量 SVG K线与技术指标走势图
```bash
python3 scripts/dsh_stock_cli.py chart 600519
```

### 6. 一键生成每日全盘研报与全套图表
```bash
python3 scripts/dsh_stock_cli.py report
```

### 7. 查看工程运行基线与配置概要
```bash
python3 scripts/dsh_stock_cli.py status
```

---

## 🧪 自动化测试与质量门禁验证

本工程遵循质量零缺陷法典，测试用例覆盖全部核心模块，具备离线内置 Mock 机制，可随时进行一键验证：

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```
> **当前门禁状态**：19 个测试用例全部通过，100% 绿灯。
