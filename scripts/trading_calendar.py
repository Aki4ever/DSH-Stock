#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股官方交易所交易日历与休市日判定引擎 (A-Share Official Trading Calendar Engine)
版本: v2.0.0

判定逻辑:
1. 周末判定: 星期六、星期日为常规休市日
2. 中国法定节假日休市 (元旦、春节、清明、劳动节、端午、中秋、国庆)
3. 调休补班日但交易所依然休市的特殊规则
4. 输出标准化判定结果，便于全系统前端控件做强视觉与文字警示
"""

from datetime import datetime, date
from typing import Dict, Any


class TradingCalendar:
    """A股交易日历与休市判定"""

    # 2026年法定休市日期区间配置库
    HOLIDAYS_2026 = {
        # 元旦: 1月1日~1月3日
        "2026-01-01": "元旦法定休市",
        "2026-01-02": "元旦法定休市",
        "2026-01-03": "元旦法定休市",
        # 春节: 2月16日~2月23日
        "2026-02-16": "除夕/春节休市",
        "2026-02-17": "春节法定休市",
        "2026-02-18": "春节法定休市",
        "2026-02-19": "春节法定休市",
        "2026-02-20": "春节法定休市",
        "2026-02-21": "春节法定休市",
        "2026-02-22": "春节法定休市",
        "2026-02-23": "春节法定休市",
        # 清明节: 4月4日~4月6日
        "2026-04-04": "清明节休市",
        "2026-04-05": "清明节休市",
        "2026-04-06": "清明节休市",
        # 劳动节: 5月1日~5月5日
        "2026-05-01": "劳动节休市",
        "2026-05-02": "劳动节休市",
        "2026-05-03": "劳动节休市",
        "2026-05-04": "劳动节休市",
        "2026-05-05": "劳动节休市",
        # 端午节: 6月19日~6月21日
        "2026-06-19": "端午节休市",
        "2026-06-20": "端午节休市",
        "2026-06-21": "端午节休市",
        # 中秋节: 9月25日~9月27日
        "2026-09-25": "中秋节休市",
        "2026-09-26": "中秋节休市",
        "2026-09-27": "中秋节休市",
        # 国庆节: 10月1日~10月7日
        "2026-10-01": "国庆节休市",
        "2026-10-02": "国庆节休市",
        "2026-10-03": "国庆节休市",
        "2026-10-04": "国庆节休市",
        "2026-10-05": "国庆节休市",
        "2026-10-06": "国庆节休市",
        "2026-10-07": "国庆节休市",
    }

    @classmethod
    def check_date_trading_status(cls, date_str: str) -> Dict[str, Any]:
        """
        输入 YYYY-MM-DD，返回是否交易日及详细说明
        """
        try:
            target_date = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except Exception:
            target_date = date.today()
            date_str = target_date.strftime("%Y-%m-%d")

        weekday = target_date.weekday() # 0是周一, 5是周六, 6是周日
        weekday_name = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][weekday]

        # 1. 优先检查法定节假日休市
        if date_str in cls.HOLIDAYS_2026:
            reason = cls.HOLIDAYS_2026[date_str]
            return {
                "date": date_str,
                "is_trading_day": False,
                "status_code": "holiday",
                "weekday": weekday_name,
                "badge_text": f"🛑 交易所休市 ({reason})",
                "color": "#ef4444",
                "bg_color": "rgba(239, 68, 68, 0.2)",
                "description": f"该日期为中国法定节假日【{reason}】，沪深北交易所全天休市不进行撮合成交。"
            }

        # 2. 检查周末常规休市
        if weekday in (5, 6):
            return {
                "date": date_str,
                "is_trading_day": False,
                "status_code": "weekend",
                "weekday": weekday_name,
                "badge_text": f"🛑 交易所休市 (常规双休日/{weekday_name})",
                "color": "#ef4444",
                "bg_color": "rgba(239, 68, 68, 0.2)",
                "description": f"该日期为{weekday_name}，属于交易所常规周末闭市时间。"
            }

        # 3. 正常交易日
        return {
            "date": date_str,
            "is_trading_day": True,
            "status_code": "trading",
            "weekday": weekday_name,
            "badge_text": f"🟢 正常开市交易 ({weekday_name})",
            "color": "#10b981",
            "bg_color": "rgba(16, 185, 129, 0.2)",
            "description": f"沪深北交易所正常开市撮合交易时间 (9:30-11:30, 13:00-15:00)。"
        }


if __name__ == "__main__":
    t1 = TradingCalendar.check_date_trading_status("2026-09-17")
    t2 = TradingCalendar.check_date_trading_status("2026-09-19")
    t3 = TradingCalendar.check_date_trading_status("2026-10-01")
    print("2026-09-17:", t1["badge_text"])
    print("2026-09-19:", t2["badge_text"])
    print("2026-10-01:", t3["badge_text"])
