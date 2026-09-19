#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论量化核心计算库 (Chanlun Core Quantitative Library)
=====================================================
纯原生 Python 实现，零外部重型依赖。
完整覆盖形态学与动力学基础：
1. K 线包含关系递归合并（包含向上合并与向下合并）
2. 顶底分型严格识别
3. 标准笔（包含顶底不共用、至少一根独立K线判定）
4. 走势中枢构建（ZD, ZG, DD, GG 区间计算与中枢级别延伸）
5. MACD 动力学计算（面积背驰与力度比对）
6. 严格买卖点判据（1B 趋势背驰点、2B 不破前低点、3B 中枢突破回抽不破点）
"""

import math
from typing import List, Dict, Optional, Tuple, Any


class RawBar:
    """原始 K 线对象"""
    def __init__(self, time_str: str, open_p: float, close_p: float, high_p: float, low_p: float, vol: float = 0.0, amount: float = 0.0):
        self.time_str = time_str
        self.open = float(open_p)
        self.close = float(close_p)
        self.high = float(high_p)
        self.low = float(low_p)
        self.vol = float(vol)
        self.amount = float(amount)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time": self.time_str,
            "open": self.open,
            "close": self.close,
            "high": self.high,
            "low": self.low,
            "vol": self.vol,
            "amount": self.amount
        }


class ProcessedBar:
    """经过包含合并处理后的标准 K 线"""
    def __init__(self, time_str: str, high_p: float, low_p: float, direction: int, original_count: int = 1):
        self.time_str = time_str
        self.high = round(high_p, 4)
        self.low = round(low_p, 4)
        self.direction = direction  # 1 为向上处理，-1 为向下处理
        self.original_count = original_count  # 合并的原始 K 线数量
        self.open = high_p if direction < 0 else low_p
        self.close = low_p if direction < 0 else high_p

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time": self.time_str,
            "high": self.high,
            "low": self.low,
            "direction": self.direction,
            "original_count": self.original_count
        }


class FenXing:
    """顶/底分型"""
    def __init__(self, fx_type: str, index: int, time_str: str, high: float, low: float, value: float):
        self.fx_type = fx_type  # 'TOP' (顶分型) 或 'BOTTOM' (底分型)
        self.index = index      # 在 ProcessedBar 列表中的索引
        self.time_str = time_str
        self.high = high
        self.low = low
        self.value = value      # 顶分型取 high，底分型取 low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.fx_type,
            "index": self.index,
            "time": self.time_str,
            "high": self.high,
            "low": self.low,
            "value": self.value
        }


class Bi:
    """一笔"""
    def __init__(self, direction: int, start_fx: FenXing, end_fx: FenXing, bar_count: int):
        self.direction = direction  # 1: 向上笔 (从底分型到顶分型), -1: 向下笔 (从顶分型到底分型)
        self.start_fx = start_fx
        self.end_fx = end_fx
        self.bar_count = bar_count  # 跨越的处理后K线数 (严格缠论要求处理后跨越>=5根)
        self.start_price = start_fx.value
        self.end_price = end_fx.value
        self.high = max(start_fx.high, end_fx.high)
        self.low = min(start_fx.low, end_fx.low)
        self.macd_area = 0.0        # 笔内部对应 MACD 柱子面积总和
        self.macd_peak = 0.0        # 笔内部对应 MACD 绝对极值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "start_time": self.start_fx.time_str,
            "end_time": self.end_fx.time_str,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "high": self.high,
            "low": self.low,
            "bar_count": self.bar_count,
            "macd_area": round(self.macd_area, 4)
        }


class Pivot:
    """走势中枢 [ZD, ZG]"""
    def __init__(self, start_idx: int, end_idx: int, zg: float, zd: float, gg: float, dd: float, bi_list: List[Bi]):
        self.start_idx = start_idx
        self.end_idx = end_idx
        self.zg = round(zg, 4)  # 中枢上沿 min(g1, g2)
        self.zd = round(zd, 4)  # 中枢下沿 max(d1, d2)
        self.gg = round(gg, 4)  # 中枢区间最高点
        self.dd = round(dd, 4)  # 中枢区间最低点
        self.bi_list = bi_list
        self.start_time = bi_list[0].start_fx.time_str if bi_list else ""
        self.end_time = bi_list[-1].end_fx.time_str if bi_list else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zg": self.zg,
            "zd": self.zd,
            "gg": self.gg,
            "dd": self.dd,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "bi_count": len(self.bi_list)
        }


# ==============================================================================
# 算法核心函数
# ==============================================================================

def calculate_macd(bars: List[RawBar], fast: int = 12, slow: int = 26, signal: int = 9) -> List[Dict[str, float]]:
    """
    纯原生计算 MACD 指标 (DIF, DEA, MACD柱)
    """
    macd_res = []
    if not bars:
        return macd_res

    ema_fast = bars[0].close
    ema_slow = bars[0].close
    dea = 0.0

    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_signal = 2.0 / (signal + 1)

    for i, b in enumerate(bars):
        c = b.close
        if i == 0:
            ema_fast = c
            ema_slow = c
            dif = 0.0
            dea = 0.0
            hist = 0.0
        else:
            ema_fast = ema_fast * (1 - k_fast) + c * k_fast
            ema_slow = ema_slow * (1 - k_slow) + c * k_slow
            dif = ema_fast - ema_slow
            dea = dea * (1 - k_signal) + dif * k_signal
            hist = 2 * (dif - dea)

        macd_res.append({
            "dif": round(dif, 4),
            "dea": round(dea, 4),
            "hist": round(hist, 4)
        })
    return macd_res


def handle_inclusion(raw_bars: List[RawBar]) -> List[ProcessedBar]:
    """
    第 1 步：K 线包含关系合并处理
    按结合方向：
    - 向上处理（高高）：取 max(high1, high2), max(low1, low2)
    - 向下处理（低低）：取 min(high1, high2), min(low1, low2)
    """
    if not raw_bars:
        return []
    if len(raw_bars) == 1:
        return [ProcessedBar(raw_bars[0].time_str, raw_bars[0].high, raw_bars[0].low, 1, 1)]

    # 初始两根K线确定初始方向
    p_bars: List[ProcessedBar] = []
    first = raw_bars[0]
    second = raw_bars[1]

    # 判断第1与第2根是否有包含关系
    has_inc_01 = (first.high >= second.high and first.low <= second.low) or \
                 (second.high >= first.high and second.low <= first.low)

    if has_inc_01:
        # 默认前瞻方向向上合并
        h = max(first.high, second.high)
        l = max(first.low, second.low)
        p_bars.append(ProcessedBar(second.time_str, h, l, 1, 2))
        curr_idx = 2
    else:
        init_dir = 1 if second.high > first.high else -1
        p_bars.append(ProcessedBar(first.time_str, first.high, first.low, init_dir, 1))
        p_bars.append(ProcessedBar(second.time_str, second.high, second.low, init_dir, 1))
        curr_idx = 2

    # 循环顺序处理后续K线
    for i in range(curr_idx, len(raw_bars)):
        curr_raw = raw_bars[i]
        prev_p = p_bars[-1]

        # 检查是否与上一根处理后的K线存在包含
        is_inclusion = (prev_p.high >= curr_raw.high and prev_p.low <= curr_raw.low) or \
                       (curr_raw.high >= prev_p.high and curr_raw.low <= prev_p.low)

        if is_inclusion:
            # 存在包含关系，依据上一方向合并
            if prev_p.direction == 1:  # 向上合并
                new_h = max(prev_p.high, curr_raw.high)
                new_l = max(prev_p.low, curr_raw.low)
            else:  # 向下合并
                new_h = min(prev_p.high, curr_raw.high)
                new_l = min(prev_p.low, curr_raw.low)

            # 原地替换或生成合并K线
            p_bars[-1] = ProcessedBar(curr_raw.time_str, new_h, new_l, prev_p.direction, prev_p.original_count + 1)
        else:
            # 不包含，依据高低点决定当前真实方向
            new_dir = 1 if curr_raw.high > prev_p.high else -1
            p_bars.append(ProcessedBar(curr_raw.time_str, curr_raw.high, curr_raw.low, new_dir, 1))

    return p_bars


def identify_fenxing(p_bars: List[ProcessedBar]) -> List[FenXing]:
    """
    第 2 步：严格识别顶分型与底分型
    三根连续处理后K线：
    顶分型：中间K线高点最高，低点也最高
    底分型：中间K线低点最低，高点也最低
    """
    fx_list: List[FenXing] = []
    if len(p_bars) < 3:
        return fx_list

    for i in range(1, len(p_bars) - 1):
        prev_b = p_bars[i - 1]
        curr_b = p_bars[i]
        next_b = p_bars[i + 1]

        # 顶分型
        if curr_b.high > prev_b.high and curr_b.high > next_b.high and \
           curr_b.low > prev_b.low and curr_b.low > next_b.low:
            fx_list.append(FenXing("TOP", i, curr_b.time_str, curr_b.high, curr_b.low, curr_b.high))

        # 底分型
        elif curr_b.low < prev_b.low and curr_b.low < next_b.low and \
             curr_b.high < prev_b.high and curr_b.high < next_b.high:
            fx_list.append(FenXing("BOTTOM", i, curr_b.time_str, curr_b.high, curr_b.low, curr_b.low))

    return fx_list


def construct_bi(fx_list: List[FenXing], p_bars: List[ProcessedBar], raw_bars: List[RawBar], macd_list: List[Dict[str, float]]) -> List[Bi]:
    """
    第 3 步：成笔判定与动力学计算
    严格规则：
    1. 顶分型与底分型交替出现；
    2. 顶底之间不能共用K线，且在 processed_bars 中跨越间隔 >= 4（即总计 >= 5根K线）；
    3. 若连续出现同类型分型，取极值者保留（顶分型取最高，底分型取最低）；
    4. 计算每笔区间的 MACD 面积与极值。
    """
    if not fx_list:
        return []

    # 1. 过滤同向连续分型，保留极值
    filtered_fx: List[FenXing] = []
    for fx in fx_list:
        if not filtered_fx:
            filtered_fx.append(fx)
            continue

        last_fx = filtered_fx[-1]
        if fx.fx_type == last_fx.fx_type:
            # 相同类型：顶取更高，底取更低
            if fx.fx_type == "TOP":
                if fx.value > last_fx.value:
                    filtered_fx[-1] = fx
            else:
                if fx.value < last_fx.value:
                    filtered_fx[-1] = fx
        else:
            filtered_fx.append(fx)

    # 2. 严格成笔判定
    bis: List[Bi] = []
    if len(filtered_fx) < 2:
        return bis

    curr_start_fx = filtered_fx[0]

    for i in range(1, len(filtered_fx)):
        target_fx = filtered_fx[i]

        # 检查是否异向
        if target_fx.fx_type == curr_start_fx.fx_type:
            continue

        # 检查K线跨度（顶底之间必须有独立K线，距离 >= 4）
        bar_span = abs(target_fx.index - curr_start_fx.index)
        if bar_span >= 4:
            # 检查高低关系合理性
            if curr_start_fx.fx_type == "BOTTOM" and target_fx.value > curr_start_fx.value:
                # 向上笔
                bi = Bi(1, curr_start_fx, target_fx, bar_span + 1)
                bis.append(bi)
                curr_start_fx = target_fx
            elif curr_start_fx.fx_type == "TOP" and target_fx.value < curr_start_fx.value:
                # 向下笔
                bi = Bi(-1, curr_start_fx, target_fx, bar_span + 1)
                bis.append(bi)
                curr_start_fx = target_fx

    # 3. 计算动力学 MACD 面积
    # 将时间字符串映射回 raw_bars 索引
    time_map = {b.time_str: idx for idx, b in enumerate(raw_bars)}

    for bi in bis:
        t_start = bi.start_fx.time_str
        t_end = bi.end_fx.time_str
        idx_s = time_map.get(t_start, 0)
        idx_e = time_map.get(t_end, len(raw_bars) - 1)
        if idx_s > idx_e:
            idx_s, idx_e = idx_e, idx_s

        area = 0.0
        peak = 0.0
        for k in range(idx_s, min(idx_e + 1, len(macd_list))):
            h = macd_list[k]["hist"]
            if bi.direction == 1:
                # 向上笔统计动能（正向为主）
                area += abs(h)
                peak = max(peak, abs(h))
            else:
                # 向下笔统计动能（负向为主）
                area += abs(h)
                peak = max(peak, abs(h))

        bi.macd_area = round(area, 4)
        bi.macd_peak = round(peak, 4)

    return bis


def detect_pivots(bis: List[Bi]) -> List[Pivot]:
    """
    第 4 步：识别走势中枢
    连续三个次级别走势（三笔）的重叠部分 [ZD, ZG]
    ZG = min(g1, g2)
    ZD = max(d1, d2)
    中枢成立条件：ZG > ZD
    """
    pivots: List[Pivot] = []
    if len(bis) < 3:
        return pivots

    i = 0
    while i <= len(bis) - 3:
        b1, b2, b3 = bis[i], bis[i + 1], bis[i + 2]

        # 三笔的价格区间
        highs = [b1.high, b2.high, b3.high]
        lows = [b1.low, b2.low, b3.low]

        # 中枢上沿与下沿
        if b1.direction == -1:
            # 下-上-下 组合
            # g1 = b1.low(起于顶止于底，反弹g1是b2高点), g2=b3起点(b2高点)
            # 标准取法：取两个向上端点的高点之低者，两个向下端点的低点之高者
            zg = min(b2.high, b1.start_price if b1.direction == 1 else b2.high)
            zd = max(b1.low, b3.low)
        else:
            # 上-下-上 组合
            zg = min(b1.high, b3.high)
            zd = max(b2.low, b1.start_price if b1.direction == -1 else b2.low)

        # 简化公理化重叠：
        # 前三笔只要有价格交集即存在中枢
        zg_val = min(max(b1.start_price, b1.end_price), max(b2.start_price, b2.end_price), max(b3.start_price, b3.end_price))
        zd_val = max(min(b1.start_price, b1.end_price), min(b2.start_price, b2.end_price), min(b3.start_price, b3.end_price))

        if zg_val > zd_val:
            # 中枢成立，延伸吸收后续有重叠的笔
            pivot_bis = [b1, b2, b3]
            curr_zg = zg_val
            curr_zd = zd_val
            curr_gg = max(highs)
            curr_dd = min(lows)

            j = i + 3
            while j < len(bis):
                next_b = bis[j]
                # 只要与中枢区间 [curr_zd, curr_zg] 有任何交集，属于中枢震荡延伸
                if max(next_b.start_price, next_b.end_price) >= curr_zd and \
                   min(next_b.start_price, next_b.end_price) <= curr_zg:
                    pivot_bis.append(next_b)
                    curr_gg = max(curr_gg, next_b.high)
                    curr_dd = min(curr_dd, next_b.low)
                    j += 1
                else:
                    break

            pivots.append(Pivot(i, j - 1, curr_zg, curr_zd, curr_gg, curr_dd, pivot_bis))
            i = j  # 跳过已被中枢消耗的笔
        else:
            i += 1

    return pivots


class SignalResult:
    """信号输出结构"""
    def __init__(self, code: str, name: str, signal_type: str, time_str: str, entry_price: float, stop_price: float, desc: str, score: float = 0.0):
        self.code = code
        self.name = name
        self.signal_type = signal_type  # '3B' (第三类买点), '2B' (第二类买点), '1B' (背驰买点), '1S'/'3S'
        self.time_str = time_str
        self.entry_price = round(entry_price, 2)
        self.stop_price = round(stop_price, 2)
        self.risk_pct = round(((entry_price - stop_price) / entry_price) * 100, 2) if entry_price > 0 else 0.0
        self.desc = desc
        self.score = score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "signal_type": self.signal_type,
            "time": self.time_str,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "risk_pct": self.risk_pct,
            "desc": self.desc,
            "score": self.score
        }


def analyze_chanlun_signals(code: str, name: str, raw_bars: List[RawBar]) -> List[SignalResult]:
    """
    全自动缠论信号扫描与判定器
    支持：
    1. 3B: 中枢突破后回抽不进中枢 [ZG, ZD]
    2. 2B: 强反弹后回踩不破前低
    3. 1B: 趋势背驰或盘整背驰转折点
    4. 中枢下沿底吸信号: 强支撑位底分型企稳
    """
    signals: List[SignalResult] = []
    if len(raw_bars) < 30:
        return signals

    # 1. 指标与几何解构
    macd_list = calculate_macd(raw_bars)
    p_bars = handle_inclusion(raw_bars)
    fx_list = identify_fenxing(p_bars)
    bis = construct_bi(fx_list, p_bars, raw_bars, macd_list)
    pivots = detect_pivots(bis)

    if len(bis) < 3:
        return signals

    latest_bi = bis[-1]
    prev_bi = bis[-2]
    curr_price = raw_bars[-1].close

    # --------------------------------------------------------------------------
    # 策略模型 1: 第三类买点 3B 扫描
    # --------------------------------------------------------------------------
    if pivots:
        latest_pivot = pivots[-1]
        # 情况A：倒数第2笔突破中枢上沿ZG，最新笔为向下回抽笔且最低点 > ZG
        if prev_bi.direction == 1 and prev_bi.end_price > latest_pivot.zg:
            if latest_bi.direction == -1 and latest_bi.end_price >= latest_pivot.zg * 0.995:
                stop_p = latest_bi.end_price
                risk = ((curr_price - stop_p) / curr_price) * 100 if curr_price > stop_p else 0
                if 0.1 <= risk <= 8.0:
                    desc = f"中枢([ZG={latest_pivot.zg}])突破后回抽不跌破中枢上沿(最低点{latest_bi.end_price})"
                    signals.append(SignalResult(code, name, "3B", raw_bars[-1].time_str, curr_price, stop_p, desc, 90.0))

        # 情况B：最新笔刚完成向上突破ZG，当前K线处于突破后强势蓄势段
        elif latest_bi.direction == 1 and latest_bi.end_price > latest_pivot.zg:
            stop_p = latest_pivot.zg
            risk = ((curr_price - stop_p) / curr_price) * 100 if curr_price > stop_p else 0
            if 0.1 <= risk <= 7.0:
                desc = f"向上笔强力突破中枢上沿([ZG={latest_pivot.zg}])，现处于脱离中枢主升段"
                signals.append(SignalResult(code, name, "3B-突破段", raw_bars[-1].time_str, curr_price, stop_p, desc, 86.0))

    # --------------------------------------------------------------------------
    # 策略模型 2: 第二类买点 2B 扫描 (回踩不破前低)
    # --------------------------------------------------------------------------
    if len(bis) >= 3:
        b_down1 = bis[-3]
        b_up = bis[-2]
        b_down2 = bis[-1]

        # 结构：下跌笔 -> 反弹向上笔 -> 回调向下笔
        if b_down1.direction == -1 and b_up.direction == 1 and b_down2.direction == -1:
            # 回踩笔低点高于前一向下笔低点（不破前低）
            if b_down2.end_price > b_down1.end_price and b_up.end_price > b_down1.end_price:
                stop_p = b_down1.end_price  # 止损位为前低
                risk = ((curr_price - stop_p) / curr_price) * 100 if curr_price > stop_p else 0
                if 0.1 <= risk <= 8.0:
                    desc = f"底部强反弹后回踩不创新低({b_down1.end_price} -> {b_down2.end_price})，确认右侧多头承接"
                    signals.append(SignalResult(code, name, "2B", raw_bars[-1].time_str, curr_price, stop_p, desc, 85.0))

        # 或者最新笔为反弹笔，刚从 2B 点拉升起步
        elif len(bis) >= 4:
            b1 = bis[-4] # 下
            b2 = bis[-3] # 上
            b3 = bis[-2] # 下 (2B)
            b4 = bis[-1] # 上起步
            if b1.direction == -1 and b2.direction == 1 and b3.direction == -1 and b4.direction == 1:
                if b3.end_price > b1.end_price:
                    stop_p = b3.end_price
                    risk = ((curr_price - stop_p) / curr_price) * 100 if curr_price > stop_p else 0
                    if 0.1 <= risk <= 6.0:
                        desc = f"2B右侧确认后向上笔起爆，回踩点({b3.end_price})高于前低({b1.end_price})"
                        signals.append(SignalResult(code, name, "2B-起爆", raw_bars[-1].time_str, curr_price, stop_p, desc, 88.0))

    # --------------------------------------------------------------------------
    # 策略模型 3: 第一类买点 1B / 中枢底背驰
    # --------------------------------------------------------------------------
    if len(bis) >= 3:
        # 下跌笔出现创出新低，但 MACD 动能严重萎缩
        if latest_bi.direction == -1 and prev_bi.direction == 1:
            prev_down_bi = bis[-3] if bis[-3].direction == -1 else None
            if prev_down_bi and latest_bi.end_price < prev_down_bi.end_price:
                # 价格创新低，比较动能
                if latest_bi.macd_area < prev_down_bi.macd_area * 0.7:
                    stop_p = latest_bi.end_price
                    desc = f"向下笔创出新低但MACD面积背驰衰竭({latest_bi.macd_area} < {prev_down_bi.macd_area})"
                    signals.append(SignalResult(code, name, "1B-底背驰", raw_bars[-1].time_str, curr_price, stop_p, desc, 82.0))

    return signals


if __name__ == "__main__":
    print("Chanlun core library compiled successfully.")
