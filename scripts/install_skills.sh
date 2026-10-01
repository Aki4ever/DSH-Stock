#!/usr/bin/env bash
# ==============================================================================
# 脚本名称：install_skills.sh
# 需求归属：REQ-006（CLI + DSH Agent Skill 赋能）、REQ-055（stockper 智能体 + DSH 宿主注册）
#
# 存在理由（为什么需要这一步，不能只留 skills/*.md）：
#   本工程 `skills/` 下的文档（`SKILL.md` / `SKILL_STOCKPER.md`）**不是 DSH 宿主可装载的形态**。
#   DSH 的技能提供方 `@deepseek-ai/dsh-skill-filesystem` 只扫描固定根目录，且要求
#   `<根>/<技能名>/SKILL.md` 首部带 YAML frontmatter（`name` / `description`）：
#
#     rank 100  <projectRoot>/.dsh/skills      ← 本项目根（最优先，本脚本默认）
#     rank 200  <projectRoot>/.agents/skills
#     rank 300  Config.customSkillDirs
#     rank 400  <DSH_HOME>/skills
#     rank 500  <DSH_AGENTS_HOME|~/.agents>/skills
#
#   `~/.claude/skills/` **不在**该扫描表内（装到那里等于没装）——这正是本脚本存在的理由。
#
# 本脚本把本工程技能安装成宿主可装载的物理形态并逐步自证：
#   1. 目录真实创建  2. frontmatter 真实写入  3. 入口脚本真实可执行（--help 退出码）
#   4. 回读自检      5. 打印扫描根技能清单（可被 `skill` 工具发现）
#
# 用法：
#   bash scripts/install_skills.sh                                   # 装到项目根 .dsh/skills
#   DSH_SKILL_DIR=~/.agents/skills bash scripts/install_skills.sh    # 装到用户级技能根
# 幂等：重复执行只覆盖本脚本生成的文件，不动其它技能。
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SKILL_DIR="${DSH_SKILL_DIR:-${BASE_DIR}/.dsh/skills}"

ok()   { echo "✅ $*"; }
info() { echo "   $*"; }

echo "======================================================================"
echo " 🧩 安装 DSH 宿主技能（工程: ${BASE_DIR}）"
echo " 📂 宿主技能目录: ${SKILL_DIR}"
echo "======================================================================"

mkdir -p "${SKILL_DIR}"
ok "宿主技能目录已就绪"

# ---------------------------------------------------------------------------
# 1) stockper —— A 股信息权威调研与真实数据抓取（REQ-055）
# ---------------------------------------------------------------------------
SP_DIR="${SKILL_DIR}/stockper"
mkdir -p "${SP_DIR}"
cat > "${SP_DIR}/SKILL.md" <<'EOF'
---
name: stockper
description: A-share (A股) information authority research and REAL data fetching agent. Use when the user asks which public source/channel is most authoritative for 大宗交易 (block trades), 十大流通股东 (top-10 float shareholders), 分红送配 (dividends), K线/行情 (kline/quotes), or 财务报表 (financial statements) — or asks to actually FETCH that data for a given stock code. Compares official exchanges (上交所/深交所/巨潮) vs portals (东方财富/同花顺/腾讯/新浪) vs open-source libs (AkShare/Tushare). Triggered by phrases like "从哪里获取更权威", "数据源对比", "抓取大宗交易", "十大流通股东", "分红", "财务报表".
---

# stockper — A股信息权威调研与真实抓取

本技能挂载本仓库的独立智能体 `scripts/stockper_agent.py`（Python 标准库零依赖，真实调用公开接口）。

## 何时使用

| 用户意图 | 调用 |
| :--- | :--- |
| 问「大宗交易/股东/分红/K线/财报 从哪里获取更权威」 | `survey` / `compare` |
| 自然语言问询，且带股票代码要「顺便取数」 | `ask "<query>"` |
| 明确要抓取某维度真实数据 | `fetch <dimension> <code>` |

维度取值：`block_trade`（大宗交易）｜`shareholders`（十大流通股东占比）｜`dividend`（分红送配）｜`kline`（K线行情）｜`finance`（财务报表）。

## 命令（工作目录必须为本仓库根目录）

```bash
python3 scripts/stockper_agent.py survey block_trade          # 单维度调研详情
python3 scripts/stockper_agent.py compare                     # 五维横向对比矩阵
python3 scripts/stockper_agent.py ask "600519 的大宗交易和分红从哪里拿更权威"
python3 scripts/stockper_agent.py fetch kline 600519 --limit 10 --format json
```

## 边界与诚信约束（不得放宽）

1. **只回真实数据**：抓不到就如实报错/返回空，绝不生成样例值或估算值冒充真实披露。
2. **标注来源**：结果自带 `source_channel` 与 `api_endpoint`，引用时必须一并给出。
3. **不臆造权威度**：渠道优劣以 `docs/stockper_data_sources_survey.md` 的调研矩阵为准。
EOF
ok "stockper 技能已安装 → ${SP_DIR}/SKILL.md"

# ---------------------------------------------------------------------------
# 2) dsh-stock —— 本工程 CLI/Skill 入口（REQ-006）
# ---------------------------------------------------------------------------
DS_DIR="${SKILL_DIR}/dsh-stock"
mkdir -p "${DS_DIR}"
cat > "${DS_DIR}/SKILL.md" <<'EOF'
---
name: dsh-stock
description: This repository's own A-share CLI (17 subcommands) — real-time quotes, 100-point quantitative scoring, watchlist/portfolio, SVG charts, Markdown research reports, verified daily history, shareholder increase/decrease, 缠论 (Chanlun) structure & buy/sell points, strategy screening, Feishu/DingTalk alerts, database archive. Use when working INSIDE the DSH股票 project and the user wants its own CLI/endpoints rather than the generic eastmoney-quant skill. Triggered by phrases like "跑一下本工程CLI", "生成研报", "db-archive", "持仓体检", "缠论雷达", "策略选股".
---

# dsh-stock — 本工程自有 CLI 与能力入口

工作目录：本仓库根目录（`scripts/dsh_stock_cli.py` 所在目录）。

## 常用命令

```bash
python3 scripts/dsh_stock_cli.py --help                      # 17 个子命令清单
python3 scripts/dsh_stock_cli.py quote 600519 sh000001       # 实时行情
python3 scripts/dsh_stock_cli.py analyze 600519              # 100 分制量化体检
python3 scripts/dsh_stock_cli.py report                      # 全盘 Markdown 研报 + SVG
python3 scripts/dsh_stock_cli.py history 600519 --json       # 真实不复权日线
python3 scripts/dsh_stock_cli.py holder-actions 600519 --days 365 --json
python3 scripts/dsh_stock_cli.py portfolio --json            # 持仓体检（需底册已核实）
python3 scripts/dsh_stock_cli.py db-archive --help           # 非破坏归档
```

## 服务端与本工程技能

- 服务端：`python3 scripts/stock_web_server.py --port 8888`（默认仅绑 127.0.0.1）
- 真实抓取智能体：见 `stockper` 技能
- 工程规则与需求台账：`AGENTS.md`、`docs/requirements.md`

## 边界

- 产品链路**禁止 Mock 回退**：取不到就报未获取，不得展示模拟行情或推造指标。
- 涉及持仓的功能需要 `portfolio_verified=true`（由持仓本人设置），否则按设计拒绝输出结论。
EOF
ok "dsh-stock 技能已安装 → ${DS_DIR}/SKILL.md"

# ---------------------------------------------------------------------------
# 3) 物理自证：入口可执行 + frontmatter 可解析 + 目录清单
# ---------------------------------------------------------------------------
echo "----------------------------------------------------------------------"
echo " 🔍 物理自证"
if [[ -f "${BASE_DIR}/scripts/stockper_agent.py" ]]; then
  if python3 "${BASE_DIR}/scripts/stockper_agent.py" --help >/dev/null 2>&1; then
    ok "stockper 入口可执行：python3 scripts/stockper_agent.py --help（退出码 0）"
  else
    echo "❌ stockper 入口不可执行"; exit 1
  fi
else
  echo "❌ 缺少 scripts/stockper_agent.py"; exit 1
fi

for d in stockper dsh-stock; do
  f="${SKILL_DIR}/${d}/SKILL.md"
  if [[ "$(head -1 "$f")" == "---" ]] && grep -q "^name: ${d}$" "$f" && grep -q "^description: " "$f"; then
    ok "${d}/SKILL.md frontmatter 合法（name=${d} + description）"
  else
    echo "❌ ${d}/SKILL.md frontmatter 不合法"; exit 1
  fi
done

info "扫描根现有技能："
ls -1 "${SKILL_DIR}" | sed 's/^/     - /'
echo "======================================================================"
echo " ✅ 安装完成。宿主 watcher 会刷新会话技能目录；若未刷新，新开会话即生效。"
echo "======================================================================"
