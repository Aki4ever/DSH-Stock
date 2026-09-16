#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票矢量 SVG K线走势与技术指标图表生成引擎 (Stock SVG Chart Generator)
版本: v1.0.0
遵循规范: rules/system/meta_rules.md 第十条（直达交付）、第十五条（资产管控）
"""

import os
from typing import List, Optional
from scripts.stock_data_engine import KLineBar, StockQuote
from scripts.stock_indicators import calculate_ma, calculate_boll, calculate_macd


def generate_stock_svg(
    quote: StockQuote,
    bars: List[KLineBar],
    output_path: Optional[str] = None,
    width: int = 960,
    height: int = 540
) -> str:
    """
    生成高颜值矢量 SVG 股票走势图（含主图K线、MA均线、副图成交量与指标速查）
    """
    if not bars:
        raise ValueError("K线数据不能为空")

    # 裁剪展示最近 40~60 根 K 线
    display_bars = bars[-50:] if len(bars) > 50 else bars
    n_bars = len(display_bars)

    # 边距与布局规划
    pad_left = 65
    pad_right = 75
    pad_top = 80
    chart_w = width - pad_left - pad_right
    main_h = int((height - pad_top) * 0.65)  # 主图高度
    gap_h = 25
    vol_y = pad_top + main_h + gap_h
    vol_h = height - vol_y - 45             # 成交量子图高度

    # 提取价格与成交量范围
    highs = [b.high for b in display_bars]
    lows = [b.low for b in display_bars]
    vols = [b.volume for b in display_bars]

    all_closes = [b.close for b in bars]
    all_ma5 = calculate_ma(all_closes, 5)[-n_bars:]
    all_ma10 = calculate_ma(all_closes, 10)[-n_bars:]
    all_ma20 = calculate_ma(all_closes, 20)[-n_bars:]

    max_p = max(highs) * 1.01
    min_p = min(lows) * 0.99
    price_range = max_p - min_p if max_p > min_p else 1.0
    max_vol = max(vols) * 1.15 if max(vols) > 0 else 1.0

    # 坐标转换辅助函数
    bar_step = chart_w / n_bars
    candle_w = max(3.0, bar_step * 0.65)

    def price_to_y(p: float) -> float:
        return pad_top + (max_p - p) / price_range * main_h

    def vol_to_y(v: float) -> float:
        return vol_y + vol_h - (v / max_vol) * vol_h

    def idx_to_x(i: int) -> float:
        return pad_left + i * bar_step + bar_step / 2.0

    # 涨跌主色定义（遵循中国A股红涨绿跌习惯）
    c_up = "#eb4d4b"      # 涨：靓丽红
    c_down = "#2ecc71"    # 跌：青翠绿
    c_bg = "#131722"      # 专业金融暗黑底色
    c_grid = "#2a2e39"    # 网格浅灰
    c_text = "#848e9c"    # 辅助文本灰
    c_ma5 = "#f1c40f"     # MA5 黄
    c_ma10 = "#00d2d3"    # MA10 青
    c_ma20 = "#e056fd"    # MA20 紫

    svg_parts: List[str] = []
    svg_parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="100%" style="background-color: {c_bg}; font-family: -apple-system, BlinkMacSystemFont, PingFang SC, Segoe UI, sans-serif;">'
    )

    # 渐变与滤镜定义
    svg_parts.append('''
    <defs>
        <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.3"/>
        </filter>
    </defs>
    ''')

    # 1. 顶部 Header 信息栏
    sign = "+" if quote.change >= 0 else ""
    header_color = c_up if quote.change >= 0 else c_down
    svg_parts.append(f'''
    <!-- 顶部状态栏 -->
    <text x="{pad_left}" y="36" fill="#ffffff" font-size="20" font-weight="bold">{quote.name} ({quote.code})</text>
    <text x="{pad_left}" y="60" fill="{c_text}" font-size="12">最新: <tspan fill="{header_color}" font-weight="bold" font-size="16">{quote.price:.2f}</tspan>  涨跌: <tspan fill="{header_color}">{sign}{quote.change:.2f} ({sign}{quote.change_pct:.2f}%)</tspan>  高: {quote.high:.2f}  低: {quote.low:.2f}  额: {quote.turnover/100000000:.2f}亿</text>
    <text x="{width - pad_right}" y="36" fill="{c_text}" font-size="12" text-anchor="end">{quote.timestamp}</text>
    <!-- 图例 -->
    <g transform="translate({width - pad_right - 230}, 50)" font-size="11">
        <circle cx="0" cy="0" r="4" fill="{c_ma5}" />
        <text x="8" y="4" fill="{c_ma5}">MA5</text>
        <circle cx="55" cy="0" r="4" fill="{c_ma10}" />
        <text x="63" y="4" fill="{c_ma10}">MA10</text>
        <circle cx="120" cy="0" r="4" fill="{c_ma20}" />
        <text x="128" y="4" fill="{c_ma20}">MA20</text>
    </g>
    ''')

    # 2. 绘制水平网格与 Y 轴价格刻度
    n_grids = 5
    for g in range(n_grids + 1):
        gy = pad_top + (main_h / n_grids) * g
        g_price = max_p - (price_range / n_grids) * g
        svg_parts.append(
            f'<line x1="{pad_left}" y1="{gy}" x2="{width - pad_right}" y2="{gy}" stroke="{c_grid}" stroke-width="1" stroke-dasharray="3,3" />'
        )
        svg_parts.append(
            f'<text x="{width - pad_right + 8}" y="{gy + 4}" fill="{c_text}" font-size="10">{g_price:.2f}</text>'
        )

    # 3. 绘制 K 线实体与影线
    for idx, b in enumerate(display_bars):
        x = idx_to_x(idx)
        is_up = b.close >= b.open
        candle_c = c_up if is_up else c_down

        y_open = price_to_y(b.open)
        y_close = price_to_y(b.close)
        y_high = price_to_y(b.high)
        y_low = price_to_y(b.low)

        top_body = min(y_open, y_close)
        body_h = max(1.5, abs(y_close - y_open))

        # 上下影线
        svg_parts.append(
            f'<line x1="{x:.1f}" y1="{y_high:.1f}" x2="{x:.1f}" y2="{y_low:.1f}" stroke="{candle_c}" stroke-width="1.2" />'
        )
        # K线柱体
        svg_parts.append(
            f'<rect x="{x - candle_w/2:.1f}" y="{top_body:.1f}" width="{candle_w:.1f}" height="{body_h:.1f}" '
            f'fill="{candle_c}" rx="1" />'
        )

        # 4. 对应成交量副图柱子
        vy = vol_to_y(b.volume)
        vh = max(1.0, (pad_top + main_h + gap_h + vol_h) - vy)
        svg_parts.append(
            f'<rect x="{x - candle_w/2:.1f}" y="{vy:.1f}" width="{candle_w:.1f}" height="{vh:.1f}" fill="{candle_c}" opacity="0.85" />'
        )

    # 5. 绘制 MA 均线折线 (MA5, MA10, MA20)
    def render_ma_polyline(ma_list: List[Optional[float]], stroke_color: str):
        pts = []
        for idx, val in enumerate(ma_list):
            if val is not None:
                x = idx_to_x(idx)
                y = price_to_y(val)
                pts.append(f"{x:.1f},{y:.1f}")
        if pts:
            svg_parts.append(
                f'<polyline points="{" ".join(pts)}" fill="none" stroke="{stroke_color}" stroke-width="1.8" stroke-linecap="round" />'
            )

    render_ma_polyline(all_ma5, c_ma5)
    render_ma_polyline(all_ma10, c_ma10)
    render_ma_polyline(all_ma20, c_ma20)

    # 6. 成交量副图分割线与标签
    svg_parts.append(
        f'<line x1="{pad_left}" y1="{vol_y - 12}" x2="{width - pad_right}" y2="{vol_y - 12}" stroke="{c_grid}" stroke-width="1" />'
    )
    svg_parts.append(
        f'<text x="{pad_left}" y="{vol_y - 2}" fill="{c_text}" font-size="10">成交量 VOL</text>'
    )
    svg_parts.append(
        f'<text x="{width - pad_right + 8}" y="{vol_y + 12}" fill="{c_text}" font-size="9">{int(max_vol):,}</text>'
    )

    # 7. X 轴日期刻度
    date_step = max(1, n_bars // 6)
    for i in range(0, n_bars, date_step):
        x = idx_to_x(i)
        d_str = display_bars[i].date[5:]  # MM-DD
        svg_parts.append(
            f'<text x="{x:.1f}" y="{height - 18}" fill="{c_text}" font-size="10" text-anchor="middle">{d_str}</text>'
        )

    # 8. 闭合标签
    svg_parts.append("</svg>")
    svg_content = "\n".join(svg_parts)

    # 若指定路径，持久化写入文件
    if output_path:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

    return svg_content
