# DSH 股票信息权威调研与数据抓取智能体技能说明书 (SKILL_STOCKPER.md)

> ### 🏷️ **技能元数据**
> - **技能代号**：`stockper`
> - **版本**：`v1.0.0` (归属 R11 批次 / REQ-055)
> - **适用宿主**：DeepSeek Harness (DSH) Agent 基座
> - **运行基准**：Python 3.9+（零外部三方依赖，纯标准库驱动）
> - **核心入口**：`scripts/stockper_agent.py`

---

## 🎯 技能定位与核心职责
本智能体（Agent `stockper`）专为中国 A 股量化投资者与研报系统打造，专门负责：
1. **权威度调研与决策**：深度调研与甄别 A 股 5 大核心信息（**大宗交易**、**十大流通股东占比**、**分红**、**K线图**、**财务报表**）从哪里获取更权威；
2. **多维横向对比**：穿透获知公开渠道的名称、抓取接口、抓取信息口径、有效性指标、风险点、优势劣势，并提供同类信息在不同渠道（官方交易所/巨潮 vs 东方财富/同花顺 vs 腾讯/新浪 vs AkShare/Tushare）的横向对比矩阵；
3. **快速问询与自动抓取**：当用户或宿主 Agent 问询时，快速给出对应的权威抓取渠道建议，并**直接负责调用接口获取到该股票的真实有效数据**！

---

## 🛠️ 子能力调用矩阵与命令规范

### 1. 渠道调研与对比矩阵 (`survey` / `compare`)
- **正向触发**：用户问及“大宗交易去哪里抓更权威”、“各大网站股东数据有什么区别”、“K线行情哪个接口最稳定”；
- **调用方式**：
  ```bash
  # 查看指定维度的调研详情
  python3 scripts/stockper_agent.py survey block_trade
  
  # 生成五大维度的横向对比全景报告
  python3 scripts/stockper_agent.py compare
  ```

### 2. 智能问询与即时抓取 (`ask`)
- **正向触发**：用户以自然语言咨询数据源，或同时要求获取某股票数据（例如“请问 600519 的十大流通股东去哪里获取更权威，并帮我抓一下？”）；
- **调用方式**：
  ```bash
  python3 scripts/stockper_agent.py ask "大宗交易从哪里获取更权威？"
  python3 scripts/stockper_agent.py ask "请问600519的十大流通股东去哪里获取更权威，并帮我获取最新的十大流通股东占比？"
  ```

### 3. 负责直接抓取核心数据 (`fetch`)
- **支持维度**：
  - `block_trade`：大宗交易（成交价、成交量、折溢价率、买卖营业部席位）
  - `shareholders`：十大流通股东（最新报告期排位、股东名称、持股数、占比、合计持股比例）
  - `dividend`：分红送配（分红预案、除权除息日、派息日、实施进度）
  - `kline`：K线图行情（开高低收OHLC、前复权序列、成交量额）
  - `finance`：财务报表（资产负债表、利润表、现金流量表核心科目）
- **调用方式**：
  ```bash
  # 抓取十大流通股东及合计占比
  python3 scripts/stockper_agent.py fetch shareholders 600519
  
  # 抓取大宗交易明细
  python3 scripts/stockper_agent.py fetch block_trade 600519 --limit 5
  
  # 抓取分红送配历史与最新方案
  python3 scripts/stockper_agent.py fetch dividend 600519
  
  # 抓取前复权日K线数据
  python3 scripts/stockper_agent.py fetch kline 600519 --limit 30
  
  # 抓取三张财务报表
  python3 scripts/stockper_agent.py fetch finance 600519
  ```
