#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票全盘综合研报生成引擎 (Stock Daily Report Generator)
版本: v1.0.0
遵循规范: rules/system/meta_rules.md 第十条（直达交付）、第十三条（风险揭示）
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from scripts.stock_data_engine import get_quote, get_batch_quotes, generate_mock_kline, StockQuote
from scripts.stock_indicators import evaluate_stock, QuantitativeReport
from scripts.stock_portfolio import build_portfolio_summary, PortfolioSummary, AlertMessage
from scripts.stock_chart_svg import generate_stock_svg


def generate_daily_report(config_path: Optional[str] = None) -> str:
    """生成每日股票全盘综合研报并持久化保存为 Markdown 文件与配套 SVG 图表"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if config_path is None:
        config_path = os.path.join(base_dir, "config", "stock_config.json")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    today_str = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 获取核心大盘指数行情
    raw_indices = cfg.get("indices", [])
    index_codes = [idx["code"] for idx in raw_indices]
    index_quotes = get_batch_quotes(index_codes, allow_mock=True)

    # 2. 获取自选股池行情并进行量化评分
    raw_watchlist = cfg.get("watchlist", [])
    watch_codes = [item["code"] for item in raw_watchlist]
    watch_quotes = get_batch_quotes(watch_codes, allow_mock=True)
    watch_map = {q.code: q for q in watch_quotes}

    quant_reports: List[QuantitativeReport] = []
    generated_charts: List[Dict[str, str]] = []

    charts_dir = os.path.join(base_dir, "reports", "charts")
    os.makedirs(charts_dir, exist_ok=True)

    for item in raw_watchlist:
        code = item["code"]
        name = item.get("name", code)
        q = watch_map.get(code)
        if not q:
            continue

        bars = generate_mock_kline(code, days=60, end_price=q.price)
        eval_rep = evaluate_stock(code, name, bars)
        quant_reports.append(eval_rep)

        # 为前 3 只核心自选股生成专属 SVG 走势图
        if len(generated_charts) < 3:
            chart_rel_path = f"reports/charts/chart_{code}_{today_str}.svg"
            chart_full_path = os.path.join(base_dir, chart_rel_path)
            generate_stock_svg(q, bars, output_path=chart_full_path)
            generated_charts.append({
                "code": code,
                "name": name,
                "path": chart_rel_path
            })

    # 3. 投资组合持仓与预警
    summary, alerts = build_portfolio_summary(config_path, allow_mock=True)

    # 4. 组装 Markdown 综合研报
    lines: List[str] = []
    lines.append(f"# DSH 股票量化与自选监控综合研报 ({today_str})")
    lines.append("")
    lines.append("> ### 🏷️ **报告信息与状态总览**")
    lines.append(f"> - **生成时间**：`{now_time}`")
    lines.append(f"> - **系统版本**：`{cfg.get('system', {}).get('version', 'v1.0.0')}`")
    lines.append(f"> - **监控标的数**：大盘指数 {len(index_quotes)} 只 ｜ 自选重点股 {len(quant_reports)} 只 ｜ 活跃持仓 {len(summary.positions)} 只")
    lines.append("> - **风险预警状态**：" + (f"🚨 触发 {len(alerts)} 项风险/止盈预警！" if alerts else "🟢 各标的运行平稳，无风险警报"))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 大盘指数部分
    lines.append("## 📊 一、核心大盘指数扫描")
    lines.append("")
    lines.append("| 指数代码 | 指数名称 | 最新点位 | 涨跌点数 | 当日涨跌幅 | 成交额 (亿元) | 状态 |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
    for idx_q in index_quotes:
        sign = "+" if idx_q.change >= 0 else ""
        icon = "🔴" if idx_q.change >= 0 else "🟢"
        lines.append(
            f"| `{idx_q.code}` | **{idx_q.name}** | `{idx_q.price:,.2f}` | {sign}{idx_q.change:.2f} | {icon} **{sign}{idx_q.change_pct:.2f}%** | {idx_q.turnover/100000000:,.1f} | {'反弹收红' if idx_q.change >= 0 else '承压调整'} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # 自选股量化扫描雷达
    lines.append("## 🎯 二、自选股池 100 分制多空量化雷达")
    lines.append("")
    lines.append("| 代码 | 标的名称 | 最新价 | 涨跌幅 | 量化总分 | 综合评级 | 核心多空信号 | 操作策略建议 |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :--- | :--- | :--- |")
    for r in quant_reports:
        q = watch_map.get(r.code)
        chg_str = f"{'+' if q.change >= 0 else ''}{q.change_pct:.2f}%" if q else "0.00%"
        sig_str = "；".join(r.signals[:2]) if r.signals else "处于盘整均势"
        lines.append(
            f"| `{r.code}` | **{r.name}** | `{r.current_price:.2f}` | **{chg_str}** | **`{r.score:.1f}分`** | {r.grade} | {sig_str} | {r.action} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # 投资组合持仓看板
    lines.append("## 💼 三、投资组合持仓体检与浮动盈亏看板")
    lines.append("")
    pnl_sign = "+" if summary.total_floating_pnl >= 0 else ""
    day_sign = "+" if summary.today_floating_pnl >= 0 else ""
    lines.append(f"> ### 💰 **投资组合整体资产看板**")
    lines.append(f"> - 📌 **持仓总成本**：`¥{summary.total_cost:,.2f}`")
    lines.append(f"> - 💎 **最新总市值**：`¥{summary.total_market_value:,.2f}`")
    lines.append(f"> - 📊 **累计浮动盈亏**：`{pnl_sign}¥{summary.total_floating_pnl:,.2f}` (`{pnl_sign}{summary.total_floating_pnl_pct:.2f}%`)")
    lines.append(f"> - ⚡ **今日收益变动**：`{day_sign}¥{summary.today_floating_pnl:,.2f}`")
    lines.append("")
    lines.append("| 标的代码 | 证券名称 | 持仓股数 | 持仓均价 | 最新市价 | 市值 (元) | 仓位占比 | 累计盈亏 | 累计收益率 | 今日浮动盈亏 |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for pos in summary.positions:
        p_sign = "+" if pos.total_pnl >= 0 else ""
        d_sign = "+" if pos.daily_pnl >= 0 else ""
        lines.append(
            f"| `{pos.code}` | **{pos.name}** | {pos.shares:,} | {pos.cost_price:.2f} | {pos.current_price:.2f} | {pos.market_value:,.2f} | {pos.weight_pct:.1f}% | {p_sign}{pos.total_pnl:,.2f} | **{p_sign}{pos.total_pnl_pct:.2f}%** | {d_sign}{pos.daily_pnl:,.2f} |"
        )
    lines.append("")

    # 预警提醒
    if alerts:
        lines.append("### 🚨 重点风控与预警事件")
        for alt in alerts:
            lines.append(f"- **{alt.title}** (`{alt.code} {alt.name}`)：{alt.description}。👉 *建议：{alt.suggestion}*")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 矢量 SVG 走势图直达
    lines.append("## 📈 四、精选标的矢量 SVG 走势图表")
    lines.append("")
    for item in generated_charts:
        lines.append(f"- **{item['name']} (`{item['code']}`) K线走势图**：[`{item['path']}`]({item['path']})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 资本异动与多维基本面透视 (新增)
    lines.append("## 🔍 五、重点持仓与自选股多维资本异动透视")
    lines.append("")
    try:
        from scripts.data_sources import StockDataHub
        # 挑选重点持仓或自选进行基本面扫描
        target_codes = [p.code for p in summary.positions[:2]] or [w["code"] for w in watchlist[:2]]
        for t_code in target_codes:
            clean_c = t_code.lower().replace("sh", "").replace("sz", "")
            h_data = StockDataHub.get_holders(clean_c)
            top10 = h_data.get("top10", {})
            h_count = h_data.get("history_count", [])
            divs = StockDataHub.get_dividends(clean_c, limit=1)
            notices = StockDataHub.get_announcements(clean_c, limit=2)
            blocks = StockDataHub.get_block_trades(code=clean_c, limit=2)

            name = top10.get("name") or clean_c
            lines.append(f"### 🏢 标的：`{clean_c}` {name}")
            
            # 1. 股东与筹码
            if top10.get("holders"):
                top1_name = top10["holders"][0]["name"]
                top1_ratio = top10["holders"][0]["hold_ratio"]
                lines.append(f"- **第一大股东**：{top1_name} (持股 `{top1_ratio:.2f}%`)")
            if h_count:
                latest_h = h_count[0]
                chg_h = f"{'+' if latest_h['change_ratio'] >= 0 else ''}{latest_h['change_ratio']:.2f}%"
                lines.append(f"- **最新股东户数**：`{latest_h['holder_num']:,} 户` (环比: `{chg_h}`，集中度: `{latest_h['focus_level']}`)")

            # 2. 分红情况
            if divs:
                d = divs[0]
                lines.append(f"- **最新分红预案/进度**：{d['report_period']} [{d['progress']}] `{d['plan_detail']}`")

            # 3. 大宗交易
            if blocks:
                b = blocks[0]
                prem = f"{'+' if b['premium_ratio'] >= 0 else ''}{b['premium_ratio']:.2f}%"
                lines.append(f"- **近期大宗交易**：{b['trade_date']} 成交 `{b['amount_wan']:.1f}万元` (折溢价: `{prem}`，买方: `{b['buyer']}`)")

            # 4. 官方公告
            if notices:
                lines.append("- **最新官方公告**：")
                for n in notices:
                    lines.append(f"  - `[{n['publish_time']}]` [{n['title']}]({n['pdf_url']})")
            lines.append("")
    except Exception as e:
        lines.append(f"> *(基本面多维透视模块获取异常: {str(e)})*")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 🛡️ 六、风控纪律备忘")
    lines.append("1. **严守止盈止损**：单一标的亏损触及止损线（-8%）必须强制复盘并视情况减仓，杜绝侥幸死扛；")
    lines.append("2. **拒绝追高超买**：RSI-6 > 80 标的进入极度超买阶段，严禁盲目追高；")
    lines.append("3. **仓位动态平衡**：任何单一行业龙头持仓市值占比建议控制在 35% 以内，防范单一赛道行业系统性黑天鹅。")
    lines.append("")

    report_content = "\n".join(lines)
    report_rel_path = f"reports/stock_report_{today_str}.md"
    report_full_path = os.path.join(base_dir, report_rel_path)

    with open(report_full_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_rel_path
