#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股上市公司官方公告与大事提醒引擎 (Stock Official Announcements & Major Events Engine)
版本: v1.9.0

功能:
1. 抓取与穿透上市公司最新官方公告 (巨潮资讯网 / 上交所 / 深交所)
2. 聚合 5 大核心大事备忘录:
   - 📅 定期报告与业绩预告披露 (年报/中报/三季报)
   - 🎁 现金分红与送转除权除息日程
   - 🔓 限售解禁与流通股流通变动
   - 👥 股东大会与决议日
   - 💼 董监高增持/减持与股份质押动态
"""

import json
import urllib.request
import ssl
from typing import List, Dict, Any, Optional
from datetime import datetime


class StockEventsEngine:
    """股票公告与大事提醒中枢"""

    EASTMONEY_NOTICE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"

    @classmethod
    def get_stock_events_and_notices(cls, code: str, name: str = "") -> Dict[str, Any]:
        """
        获取单只股票的重大公告列表与大事提醒日程
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")

        # 1. 尝试从东方财富官方公告网关拉取真实公告
        notices = cls._fetch_real_notices(clean_code)


        # 2. 生成结构化大事备忘录 (Milestones)
        milestones = []

        return {
            "code": clean_code,
            "name": name,
            "milestones": milestones,
            "status": "available" if notices else "unavailable",
            "source": cls.EASTMONEY_NOTICE_API,
            "error": None if notices else "公告未获取，不能判定为无公告",
            "notices": notices
        }

    @classmethod
    def _fetch_real_notices(cls, clean_code: str) -> List[Dict[str, Any]]:
        """从官方金融公告中枢穿透拉取最新公告列表"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://data.eastmoney.com/notices/",
            "Accept": "application/json, text/plain, */*"
        }
        ctx = ssl.create_default_context()


        # 构造请求参数: 每页 15 条
        url = f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=12&page_index=1&ann_type=A&client_source=web&stock_list={clean_code}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                list_items = (data.get("data") or {}).get("list") or []
                results = []
                for it in list_items:
                    title = it.get("title_ch") or it.get("title") or ""
                    date_str = (it.get("notice_date") or "")[:10]
                    art_code = it.get("art_code") or ""
                    
                    # 识别公告类别标签
                    tag = "日常公告"
                    tag_color = "#38bdf8"
                    if "业绩" in title or "报告" in title or "财务" in title:
                        tag = "定期财务"
                        tag_color = "#ef4444"
                    elif "分红" in title or "派息" in title or "权益分派" in title:
                        tag = "分红实施"
                        tag_color = "#10b981"
                    elif "减持" in title or "增持" in title or "股份变动" in title:
                        tag = "股东增减持"
                        tag_color = "#f59e0b"
                    elif "解禁" in title or "限售" in title:
                        tag = "限售解禁"
                        tag_color = "#c084fc"
                    elif "股东大会" in title:
                        tag = "股东大会"
                        tag_color = "#60a5fa"

                    results.append({
                        "title": title,
                        "date": date_str,
                        "tag": tag,
                        "tag_color": tag_color,
                        "url": f"https://data.eastmoney.com/notices/detail/{clean_code}/{art_code}.html" if art_code else "https://www.cninfo.com.cn/"
                    })
                return results
        except Exception:
            return []
