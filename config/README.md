# 配置中心 (config) 说明文档

## 📌 目录定位
- **路径**：`config/`
- **主要作用**：用于存放与管理股票工程的核心配置，包括自选股票池、指标分析参数、预警阈值、API 数据源接口配置及持仓基础设置。

---

## 📋 文件收纳与命名规范
1. **文件分类**：仅存放 JSON / YAML / 配置说明文档，不得存放业务脚本；
2. **命名格式**：采用小写下划线命名，如 `stock_config.json`；
3. **关联文档**：配置变更需在项目主说明文档 `README.md` 及需求台账中同步登记。

---

## 🛠️ 维护与更新原则
- 新增或修改配置项时，必须提供有效默认值；
- 避免配置语法错误，支持热重载与缺省自动回退。

---

## 持仓底册（`stock_config.json` 的 `portfolio` / `portfolio_verified`）

### 为什么需要 `portfolio_verified`
本项目**不对未核实的持仓产出任何盈亏或风险结论**。当 `portfolio` 非空而 `portfolio_verified`
不为字面 `true` 时，`scripts/portfolio_checkup.py`、`GET /api/portfolio/checkup`、Web「💼 持仓体检」页
与 `dsh_stock_cli portfolio` 都会拒绝出结论：不返回任何盈亏数字、不显示任何持仓行，
并且响应体中不会出现底册里的证券名或成本价。

`portfolio_verified` **只接受字面 `true`**（`"true"`、`"True"`、`1`、`0` 一律视为未核实）。
该标记**必须由持仓本人设置**——体检流程从不修改配置文件（有测试断言文件内容零改动）。

当前默认状态为 `"portfolio": []` 且 `"portfolio_verified": false`，即**未配置持仓**：
页面对应位置会明确显示「持仓底册为空，未配置任何持仓，无可体检内容」。

### 如何填写
核实每条持仓的代码、股数、成本价与买入日期后填入，再把 `portfolio_verified` 置为 `true`：

```json
"portfolio_verified": true,
"portfolio": [
  {
    "code": "sh600519",
    "name": "贵州茅台",
    "shares": 100,
    "cost_price": 1580.0,
    "buy_date": "2026-06-15",
    "notes": "备注（可为空）"
  }
]
```

字段说明：

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| `code` | 是 | 带市场前缀的代码，如 `sh600519` / `sz300750` |
| `name` | 否 | 名称，缺失时以代码显示 |
| `shares` | 是 | 股数（整数） |
| `cost_price` | 是 | 每股成本价；为 0 时收益率无法计算，会显示「未获取」而不是 0% |
| `buy_date` | 是 | 买入日期 `YYYY-MM-DD`。移动止盈回撤需要它来确定持仓期峰值；缺失或早于数据覆盖起点时，会标注峰值可能被低估 |
| `notes` | 否 | 自定义备注 |

### 规则阈值
- 静态规则阈值在 `alert_rules`：`take_profit_ratio`（默认 0.20）、`stop_loss_ratio`（默认 -0.08）、
  `daily_surge_ratio` / `daily_plunge_ratio`（默认 ±0.05）。
- 动态规则阈值在 `dynamic_rules`：`ma_period`（默认 20）、`trailing_drawdown_ratio`（默认 0.08），
  以及 `enable_ma_breakdown` / `enable_chanlun_sell` / `enable_trailing_stop` 三个开关。

这些都是**纪律参数**，不是收益承诺；本项目不做回测也不声称任何阈值适合特定风险偏好。

### 多份底册
设置环境变量 `DSH_STOCK_CONFIG` 可指向另一份配置文件（例如实盘/模拟分开维护）。
`portfolio_checkup` 与 `stock_portfolio` 采用同一优先级：显式参数 > `DSH_STOCK_CONFIG` > 默认路径。
