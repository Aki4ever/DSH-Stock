#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
巨潮资讯网官方公告采集适配器 (Cninfo Announcement Adapter)
版本: v1.0.0
特点:
1. 对接证监会指定法定信息披露平台巨潮资讯公开 query 接口
2. 提取公告标题、分类、发布时间及官方权威 PDF 下载直链
3. 内置防反爬与关键词精准过滤
"""

import sys
import os
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from scripts.data_sources.safe_session import safe_session

CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_REFERER = "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
CNINFO_DOWNLOAD_PREFIX = "http://static.cninfo.com.cn/"

class AnnouncementAdapter:
    """巨潮官方公告采集器"""

    @staticmethod
    def get_announcements(
        code: str,
        keyword: str = "",
        days: int = 180,
        page_size: int = 15
    ) -> List[Dict[str, Any]]:
        """
        获取指定股票近期的官方公告
        :param code: 股票纯数字代码 (如 '600519', '000001')
        :param keyword: 过滤关键词 (如 '分红', '减持', '业绩')
        :param days: 查询过去多少天
        :param page_size: 返回条数
        :return: 规范化公告列表
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # 确定板块/市场代码
        column = "szse" if clean_code.startswith(("00", "30")) else "sse"
        if clean_code.startswith(("8", "4", "92")):
            column = "bjse"

        search_term = f"{clean_code} {keyword}".strip() if keyword else clean_code

        form_data = {
            "pageNum": "1",
            "pageSize": str(page_size),
            "column": column,
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": search_term,
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true"
        }

        resp_json = safe_session.post_json(
            CNINFO_QUERY_URL,
            data=form_data,
            referer=CNINFO_REFERER,
            timeout=6.0
        )

        results = []
        if not resp_json or not isinstance(resp_json, dict) or "announcements" not in resp_json:
            return results

        announcements = resp_json.get("announcements") or []
        for item in announcements:
            # 严格过滤只保留目标股票的公告
            item_code = item.get("secCode", "")
            if item_code != clean_code:
                continue

            raw_title = item.get("announcementTitle", "")
            cleaned_title = re.sub(r"</?em>", "", raw_title).strip()
            adjunct_url = item.get("adjunctUrl", "")
            pdf_url = f"{CNINFO_DOWNLOAD_PREFIX}{adjunct_url}" if adjunct_url else ""
            
            # 时间戳解析 (毫秒转为标准日期)
            time_ms = item.get("announcementTime", 0)
            if time_ms:
                dt_str = datetime.fromtimestamp(time_ms / 1000.0).strftime("%Y-%m-%d %H:%M")
            else:
                dt_str = ""

            results.append({
                "code": clean_code,
                "sec_name": re.sub(r"</?em>", "", item.get("secName", "")).strip(),
                "title": cleaned_title,
                "publish_time": dt_str,
                "announcement_id": item.get("announcementId", ""),
                "category": item.get("announcementTypeName", "官方公告"),
                "pdf_url": pdf_url,
                "source": "巨潮资讯(官方)"
            })

        return results
