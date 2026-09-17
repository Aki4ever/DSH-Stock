#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票交互终端与命令行界面 (DSH Stock CLI)
版本: v1.0.0
遵循规范: rules/system/meta_rules.md 第十条（直达交付）、第十八条（DSH-First）
"""

import os
import sys
import argparse
from typing import List

# 保证本地模块平滑导入
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stock_data_engine import get_quote, get_batch_quotes, generate_mock_kline, normalize_code
from scripts.stock_indicators import evaluate_stock
from scripts.stock_portfolio import build_portfolio_summary, load_config
from scripts.stock_chart_svg import generate_stock_svg
from scripts.stock_reporter import generate_daily_report
from scripts.data_sources import StockDataHub

# 终端 ANSI 彩色样式常量
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_WHITE = "\033[37m"
C_GRAY = "\033[90m"


def print_banner():
    """打印 DSH 股票终端标头"""
    print(f"{C_CYAN}{C_BOLD}======================================================================{C_RESET}")
    print(f"{C_CYAN}{C_BOLD} 📈 DSH 股票监控与多空量化分析系统 (DSH Stock CLI) v1.0.0{C_RESET}")
    print(f"{C_GRAY} 遵循 DSH-First 原生生态标准 ｜ 零外部三方依赖 ｜ 纯 Python 标准库驱动{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}======================================================================{C_RESET}")


def cmd_quote(codes: List[str]):
    """查询单只或多只股票实时行情"""
    if not codes:
        print(f"{C_YELLOW}⚠️ 请提供股票代码，例如: python3 scripts/dsh_stock_cli.py quote 600519 300750{C_RESET}")
        return 1

    quotes = get_batch_quotes(codes, allow_mock=True)
    print(f"\n{C_BOLD}🔍 实时行情查询结果 (共 {len(quotes)} 只标的):{C_RESET}\n")
    print(f"{'代码':<10} {'名称':<10} {'最新价':<10} {'涨跌额':<10} {'涨跌幅':<10} {'最高':<10} {'最低':<10} {'成交额(亿)':<12} {'更新时间'}")
    print("-" * 88)

    for q in quotes:
        color = C_RED if q.change >= 0 else C_GREEN
        sign = "+" if q.change >= 0 else ""
        turnover_yi = q.turnover / 100000000.0
        print(
            f"{q.code:<10} {q.name:<10} {color}{q.price:<10.2f}{C_RESET} "
            f"{color}{sign}{q.change:<9.2f}{C_RESET} "
            f"{color}{sign}{q.change_pct:<9.2f}%{C_RESET} "
            f"{q.high:<10.2f} {q.low:<10.2f} {turnover_yi:<12.2f} {q.timestamp}"
        )
    print("-" * 88)
    return 0


def cmd_list():
    """查看系统默认指数与自选股池全景"""
    cfg = load_config()
    raw_indices = cfg.get("indices", [])
    raw_watchlist = cfg.get("watchlist", [])

    all_codes = [idx["code"] for idx in raw_indices] + [w["code"] for w in raw_watchlist]
    quotes = get_batch_quotes(all_codes, allow_mock=True)
    q_map = {q.code: q for q in quotes}

    print(f"\n{C_CYAN}{C_BOLD}🏛️ 核心大盘基准指数:{C_RESET}")
    print(f"{'代码':<10} {'指数名称':<10} {'当前点位':<12} {'涨跌点数':<10} {'涨跌幅':<10}")
    print("-" * 60)
    for idx in raw_indices:
        q = q_map.get(idx["code"])
        if q:
            color = C_RED if q.change >= 0 else C_GREEN
            sign = "+" if q.change >= 0 else ""
            print(f"{q.code:<10} {q.name:<10} {color}{q.price:<12.2f}{C_RESET} {color}{sign}{q.change:<10.2f}{C_RESET} {color}{sign}{q.change_pct:<9.2f}%{C_RESET}")
    print("-" * 60)

    print(f"\n{C_YELLOW}{C_BOLD}⭐ 重点自选股池监控:{C_RESET}")
    print(f"{'代码':<10} {'标的名称':<10} {'板块赛道':<12} {'最新市价':<10} {'涨跌幅':<10} {'目标价(元)':<10}")
    print("-" * 72)
    for w in raw_watchlist:
        q = q_map.get(w["code"])
        if q:
            color = C_RED if q.change >= 0 else C_GREEN
            sign = "+" if q.change >= 0 else ""
            target = w.get("target_price", 0.0)
            print(f"{q.code:<10} {q.name:<10} {w.get('category', '-'):<12} {color}{q.price:<10.2f}{C_RESET} {color}{sign}{q.change_pct:<9.2f}%{C_RESET} {target:<10.2f}")
    print("-" * 72)
    return 0


def cmd_analyze(code: str):
    """对单只股票进行 100 分制多空量化评分与深度指标体检"""
    if not code:
        print(f"{C_RED}❌ 必须指定要分析的股票代码，例如: python3 scripts/dsh_stock_cli.py analyze 600519{C_RESET}")
        return 1

    q = get_quote(code, allow_mock=True)
    bars = generate_mock_kline(q.code, days=60, end_price=q.price)
    report = evaluate_stock(q.code, q.name, bars)

    print(f"\n{C_BOLD}📊 【{report.name} ({report.code})】多空量化深度体检报告{C_RESET}")
    print(f"最新价: {C_BOLD}{report.current_price:.2f}{C_RESET} 元 ｜ 更新时间: {q.timestamp}")
    print(f"量化总评分: {C_YELLOW}{C_BOLD}{report.score:.1f} / 100 分{C_RESET}  👉  {C_BOLD}{report.grade}{C_RESET}")
    print(f"操作策略建议: {C_GREEN}{report.action}{C_RESET}\n")

    print(f"{C_CYAN}📐 四维评分细项分解:{C_RESET}")
    dim = report.dimension_scores
    print(f"  • 趋势面评分 (满分35): {dim['trend']:>5.1f} 分  [{'█' * int(dim['trend'] / 35 * 10):<10}]")
    print(f"  • 动量面评分 (满分25): {dim['momentum']:>5.1f} 分  [{'█' * int(dim['momentum'] / 25 * 10):<10}]")
    print(f"  • 均线支撑面 (满分20): {dim['support']:>5.1f} 分  [{'█' * int(dim['support'] / 20 * 10):<10}]")
    print(f"  • 波动风险面 (满分20): {dim['volatility']:>5.1f} 分  [{'█' * int(dim['volatility'] / 20 * 10):<10}]")

    print(f"\n{C_CYAN}⚡ 关键技术信号探测:{C_RESET}")
    for sig in report.signals:
        print(f"  ✓ {sig}")

    print(f"\n{C_CYAN}📈 核心指标即时切片:{C_RESET}")
    snap = report.indicators_snapshot
    print(f"  • 均线系统: MA5={snap['ma5']} | MA10={snap['ma10']} | MA20={snap['ma20']}")
    print(f"  • MACD动能: DIF={snap['macd_dif']} | DEA={snap['macd_dea']} | 柱线={snap['macd_bar']}")
    print(f"  • 强弱与布林: RSI-6={snap['rsi6']} | BOLL中轨={snap['boll_mid']} (上={snap['boll_upper']} 下={snap['boll_lower']})")
    print(f"  • KDJ指标: K={snap['kdj_k']} | D={snap['kdj_d']} | J={snap['kdj_j']}")
    print("-" * 70)
    return 0


def cmd_portfolio():
    """查看投资组合持仓与浮动盈亏"""
    summary, alerts = build_portfolio_summary(allow_mock=True)
    pnl_c = C_RED if summary.total_floating_pnl >= 0 else C_GREEN
    pnl_sign = "+" if summary.total_floating_pnl >= 0 else ""
    day_c = C_RED if summary.today_floating_pnl >= 0 else C_GREEN
    day_sign = "+" if summary.today_floating_pnl >= 0 else ""

    print(f"\n{C_BOLD}💼 投资组合资产全景看板 (共 {len(summary.positions)} 只持仓标的):{C_RESET}")
    print(f"总持仓成本: {C_BOLD}¥{summary.total_cost:,.2f}{C_RESET} ｜ 最新总市值: {C_BOLD}¥{summary.total_market_value:,.2f}{C_RESET}")
    print(f"累计浮动盈亏: {pnl_c}{C_BOLD}{pnl_sign}¥{summary.total_floating_pnl:,.2f} ({pnl_sign}{summary.total_floating_pnl_pct:.2f}%){C_RESET}")
    print(f"今日盈亏变动: {day_c}{C_BOLD}{day_sign}¥{summary.today_floating_pnl:,.2f}{C_RESET}\n")

    print(f"{'代码':<10} {'名称':<10} {'持股数':<8} {'成本价':<9} {'最新价':<9} {'持仓市值':<12} {'权重':<7} {'累计盈亏':<12} {'收益率':<10} {'今日盈亏'}")
    print("-" * 98)

    for p in summary.positions:
        p_c = C_RED if p.total_pnl >= 0 else C_GREEN
        p_s = "+" if p.total_pnl >= 0 else ""
        d_c = C_RED if p.daily_pnl >= 0 else C_GREEN
        d_s = "+" if p.daily_pnl >= 0 else ""
        print(
            f"{p.code:<10} {p.name:<10} {p.shares:<8} {p.cost_price:<9.2f} {p.current_price:<9.2f} "
            f"{p.market_value:<12,.2f} {p.weight_pct:<6.1f}% "
            f"{p_c}{p_s}{p.total_pnl:<11,.2f}{C_RESET} "
            f"{p_c}{p_s}{p.total_pnl_pct:<9.2f}%{C_RESET} "
            f"{d_c}{d_s}{p.daily_pnl:<10,.2f}{C_RESET}"
        )
    print("-" * 98)

    if alerts:
        print(f"\n{C_RED}{C_BOLD}🚨 风险与止盈止损触发预警 ({len(alerts)} 条):{C_RESET}")
        for alt in alerts:
            print(f"  • [{alt.level}] {alt.title} ({alt.code} {alt.name}): {alt.description}")
            print(f"    👉 处置建议: {alt.suggestion}")
    else:
        print(f"\n{C_GREEN}🟢 所有持仓运行健康，未触碰止损或止盈预警线。{C_RESET}")
    return 0


def cmd_chart(code: str, output: str = ""):
    """生成指定股票的矢量 SVG 图表"""
    if not code:
        print(f"{C_RED}❌ 必须指定股票代码，例如: python3 scripts/dsh_stock_cli.py chart 600519{C_RESET}")
        return 1

    q = get_quote(code, allow_mock=True)
    bars = generate_mock_kline(q.code, days=60, end_price=q.price)

    if not output:
        output = f"reports/charts/chart_{q.code}.svg"

    svg_content = generate_stock_svg(q, bars, output_path=output)
    print(f"✅ 成功生成矢量 SVG 行情图表: {C_GREEN}{output}{C_RESET} (文件大小: {len(svg_content):,} 字节)")
    print(f"💡 提示: 可直接在浏览器或 DSH 界面中点击打开该 SVG 预览。")
    return 0


def cmd_holder(code: str):
    """查询指定股票的十大股东及股东户数变动"""
    clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
    print(f"\n{C_CYAN}⏳ 正在拉取股票 [{clean_code}] 最新十大股东与股东户数历史...{C_RESET}")
    res = StockDataHub.get_holders(clean_code)
    top10 = res.get("top10", {})
    history = res.get("history_count", [])

    stock_name = top10.get("name") or clean_code
    period = top10.get("period") or "最新报告期"
    print(f"\n{C_BOLD}👥 [{clean_code} {stock_name}] 十大股东明细 (报告期: {period}):{C_RESET}\n")
    print(f"{'名次':<6} {'持股比例%':<10} {'持股数(万股)':<14} {'变动情况':<10} {'股份性质':<12} {'股东名称'}")
    print("-" * 88)
    for h in top10.get("holders", []):
        change_col = C_RED if "增" in h['change'] else (C_GREEN if "减" in h['change'] else C_GRAY)
        print(f"{h['rank']:<6} {h['hold_ratio']:<10.2f} {h['hold_num_wan']:<14.2f} {change_col}{h['change']:<10}{C_RESET} {h['share_type']:<12} {h['name']}")

    if history:
        print(f"\n{C_BOLD}📊 历史股东户数变动与筹码集中度:{C_RESET}\n")
        print(f"{'报告截止日':<14} {'总户数':<12} {'较上期变动%':<12} {'户均持股(股)':<14} {'筹码集中度'}")
        print("-" * 65)
        for h in history:
            chg_col = C_GREEN if h['change_ratio'] < 0 else C_RED # 户数减少代表筹码趋向集中（绿或红色提示）
            print(f"{h['period']:<14} {h['holder_num']:<12} {chg_col}{h['change_ratio']:>+.2f}%{C_RESET}       {h['avg_hold_num']:<14.0f} {h['focus_level']}")
    print("")
    return 0


def cmd_dividend(code: str):
    """查询指定股票的历年分红与排期"""
    clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
    print(f"\n{C_CYAN}⏳ 正在拉取股票 [{clean_code}] 历年分红派现方案...{C_RESET}")
    divs = StockDataHub.get_dividends(clean_code, limit=8)
    if not divs:
        print(f"{C_YELLOW}⚠️ 未查询到 [{clean_code}] 的分红信息或网络超时{C_RESET}")
        return 1

    name = divs[0].get("name", clean_code)
    print(f"\n{C_BOLD}💰 [{clean_code} {name}] 历年分红派现明细与最新方案:{C_RESET}\n")
    print(f"{'分红年度/期':<14} {'进度状态':<10} {'每10股派现(元)':<16} {'股权登记日':<14} {'除权除息日':<14} {'分红方案说明'}")
    print("-" * 90)
    for d in divs:
        status_col = C_GREEN if d['progress'] == "实施分配" else C_YELLOW
        reg_d = d['record_date'] or "--"
        ex_d = d['ex_dividend_date'] or "--"
        print(f"{d['report_period']:<14} {status_col}{d['progress']:<10}{C_RESET} {d['cash_ratio']:<16.2f} {reg_d:<14} {ex_d:<14} {d['plan_detail']}")
    print("")
    return 0


def cmd_notice(code: str, keyword: str = ""):
    """查询官方权威公告"""
    clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
    kw_desc = f" (过滤词: '{keyword}')" if keyword else ""
    print(f"\n{C_CYAN}⏳ 正在对接巨潮资讯网检索 [{clean_code}]{kw_desc} 官方公告...{C_RESET}")
    notices = StockDataHub.get_announcements(clean_code, keyword=keyword, days=180, limit=10)
    if not notices:
        print(f"{C_YELLOW}⚠️ 未检索到 [{clean_code}] 的相关官方公告{C_RESET}")
        return 0

    name = notices[0].get("sec_name", clean_code)
    print(f"\n{C_BOLD}📢 [{clean_code} {name}] 官方公告列表 (证监会指定披露平台 巨潮资讯):{C_RESET}\n")
    for i, n in enumerate(notices, 1):
        print(f"{C_BOLD}{i}. [{n['publish_time']}] {n['title']}{C_RESET}")
        if n['pdf_url']:
            print(f"   {C_GRAY}官方PDF: {n['pdf_url']}{C_RESET}")
    print("")
    return 0


def cmd_blocktrade(code: str = ""):
    """查询大宗交易记录"""
    clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "") if code else ""
    target_desc = f"股票 [{clean_code}]" if clean_code else "全市场最新重点"
    print(f"\n{C_CYAN}⏳ 正在拉取 {target_desc} 大宗交易成交明细与席位动向...{C_RESET}")
    trades = StockDataHub.get_block_trades(code=clean_code, limit=12)
    if not trades:
        print(f"{C_YELLOW}⚠️ 近期无大宗交易成交记录{C_RESET}")
        return 0

    print(f"\n{C_BOLD}📦 大宗交易成交明细 (按折溢价与成交席位透视):{C_RESET}\n")
    print(f"{'交易日期':<12} {'代码':<8} {'名称':<8} {'成交价':<10} {'收盘价':<10} {'折溢价率%':<10} {'成交额(万)':<12} {'买方营业部/机构':<24} {'卖方营业部/机构'}")
    print("-" * 115)
    for t in trades:
        prem_col = C_RED if t['premium_ratio'] > 0 else (C_GREEN if t['premium_ratio'] < 0 else C_GRAY)
        buyer_str = f"{C_MAGENTA}【机构】{C_RESET}" if t['is_buyer_org'] else t['buyer'][:14]
        seller_str = f"{C_MAGENTA}【机构】{C_RESET}" if t['is_seller_org'] else t['seller'][:14]
        print(f"{t['trade_date']:<12} {t['code']:<8} {t['name']:<8} {t['deal_price']:<10.2f} {t['close_price']:<10.2f} {prem_col}{t['premium_ratio']:>+.2f}%{C_RESET}     {t['amount_wan']:<12.1f} {buyer_str:<32} {seller_str}")
    print("")
    return 0


def cmd_report():
    """生成每日全盘分析研报与全套图表"""
    print(f"{C_CYAN}⏳ 正在拉取大盘行情、计算自选股量化分并渲染 SVG 图表...{C_RESET}")
    rep_path = generate_daily_report()
    print(f"✅ 每日综合研报生成完毕: {C_GREEN}{C_BOLD}{rep_path}{C_RESET}")
    print(f"💡 提示: 研报已归档至 `reports/` 目录，配套矢量 SVG 图表已保存至 `reports/charts/`。")
    return 0


def cmd_status():
    """打印项目健康状态与配置概要"""
    cfg = load_config()
    print(f"\n{C_CYAN}{C_BOLD}📌 DSH 股票工程环境状态概要:{C_RESET}")
    print(f"  • 项目名称: {cfg.get('system', {}).get('project_name')}")
    print(f"  • 系统版本: {cfg.get('system', {}).get('version')}")
    print(f"  • 大盘指数基准: {len(cfg.get('indices', []))} 只")
    print(f"  • 监控自选股: {len(cfg.get('watchlist', []))} 只")
    print(f"  • 当前活跃持仓: {len(cfg.get('portfolio', []))} 只")
    print(f"  • 预警参数: 止盈={cfg.get('alert_rules', {}).get('take_profit_ratio')*100:.0f}% ｜ 止损={cfg.get('alert_rules', {}).get('stop_loss_ratio')*100:.0f}%")
    print(f"  • 工作目录: {BASE_DIR}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="DSH 股票监控与量化分析系统 CLI 命令行终端",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="支持的子命令列表")

    # quote 子命令
    p_quote = subparsers.add_parser("quote", help="查询单只或多只股票实时行情")
    p_quote.add_argument("codes", nargs="+", help="股票代码列表，如 600519 300750 sh000001")

    # list 子命令
    subparsers.add_parser("list", help="查看核心大盘指数与重点自选股池列表")

    # analyze 子命令
    p_ana = subparsers.add_parser("analyze", help="对单只股票进行 100 分制多空量化评分与指标体检")
    p_ana.add_argument("code", help="股票代码，如 600519 或 sz300750")

    # portfolio 子命令
    subparsers.add_parser("portfolio", help="查看投资组合持仓看板、累计盈亏与风险预警")

    # chart 子命令
    p_chart = subparsers.add_parser("chart", help="生成指定标的的矢量 SVG K线与技术指标走势图")
    p_chart.add_argument("code", help="股票代码，如 600519")
    p_chart.add_argument("-o", "--output", default="", help="SVG 输出文件路径 (可选)")

    # holder 子命令 (新增)
    p_holder = subparsers.add_parser("holder", help="查询股票最新十大股东明细与股东户数筹码变动")
    p_holder.add_argument("code", help="股票代码，如 600519")

    # dividend 子命令 (新增)
    p_div = subparsers.add_parser("dividend", help="查询股票历年分红派现方案与最新除权除息日")
    p_div.add_argument("code", help="股票代码，如 600519")

    # notice 子命令 (新增)
    p_not = subparsers.add_parser("notice", help="检索巨潮资讯网官方权威公告与监管披露")
    p_not.add_argument("code", help="股票代码，如 600519")
    p_not.add_argument("-k", "--keyword", default="", help="过滤关键词，如 '分红'、'减持'、'业绩'")

    # blocktrade 子命令 (新增)
    p_blk = subparsers.add_parser("blocktrade", help="查看盘后大宗交易成交明细、折溢价率与机构席位")
    p_blk.add_argument("code", nargs="?", default="", help="股票代码 (可选，留空则展示全市场最新大宗)")

    # report 子命令
    subparsers.add_parser("report", help="一键生成每日全盘分析研报 (Markdown) 与全量 SVG 图表")

    # status 子命令
    subparsers.add_parser("status", help="查看本工程运行基线与配置概况")

    args = parser.parse_args()

    if not args.command:
        print_banner()
        parser.print_help()
        return 0

    if args.command == "quote":
        return cmd_quote(args.codes)
    elif args.command == "list":
        return cmd_list()
    elif args.command == "analyze":
        return cmd_analyze(args.code)
    elif args.command == "portfolio":
        return cmd_portfolio()
    elif args.command == "chart":
        return cmd_chart(args.code, args.output)
    elif args.command == "holder":
        return cmd_holder(args.code)
    elif args.command == "dividend":
        return cmd_dividend(args.code)
    elif args.command == "notice":
        return cmd_notice(args.code, args.keyword)
    elif args.command == "blocktrade":
        return cmd_blocktrade(args.code)
    elif args.command == "report":
        return cmd_report()
    elif args.command == "status":
        return cmd_status()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
