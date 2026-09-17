#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票网络风控与防反爬基础模块 (Safe Request Session)
版本: v1.0.0
特性:
1. 动态主流桌面浏览器 User-Agent 随机轮换池
2. 自动化 Referer / Origin / Accept 合规请求头注入
3. 指数退避与抖动延迟 (Jitter Backoff)，杜绝高频冲撞
4. 统一超时、重试、错误兜底降级处理
"""

import time
import random
import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, Optional, Union

# 动态桌面端真实 User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
]

class AntiScrapingSession:
    """具备抗反爬能力的 HTTP 会话管理工具"""

    def __init__(self, min_interval: float = 0.3, max_interval: float = 1.0):
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._last_request_time = 0.0

    def _apply_rate_limit(self):
        """执行微秒级随机抖动延迟，防止请求过于机械化被源站 WAF 识别"""
        now = time.time()
        elapsed = now - self._last_request_time
        target_delay = random.uniform(self.min_interval, self.max_interval)
        if elapsed < target_delay:
            time.sleep(target_delay - elapsed)
        self._last_request_time = time.time()

    def build_headers(self, referer: Optional[str] = None, is_json: bool = False, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构建合规的高拟真浏览器请求头"""
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*" if is_json else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache"
        }
        if referer:
            headers["Referer"] = referer
        if custom_headers:
            headers.update(custom_headers)
        return headers

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        referer: Optional[str] = None,
        timeout: float = 6.0,
        max_retries: int = 2,
        is_json: bool = False,
        encoding: str = "utf-8"
    ) -> Optional[str]:
        """执行 GET 请求，带自动重试、退避和反爬防护"""
        if params:
            query_str = urllib.parse.urlencode(params)
            url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"

        for attempt in range(1, max_retries + 1):
            self._apply_rate_limit()
            try:
                headers = self.build_headers(referer=referer, is_json=is_json)
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw_data = resp.read()
                    return raw_data.decode(encoding, errors="replace")
            except Exception as e:
                if attempt == max_retries:
                    return None
                # 指数退避加随机抖动
                time.sleep(0.5 * attempt + random.uniform(0.1, 0.4))
        return None

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        referer: Optional[str] = None,
        timeout: float = 6.0,
        max_retries: int = 2,
        encoding: str = "utf-8"
    ) -> Optional[Union[Dict[str, Any], list]]:
        """执行 GET 请求并直接安全解析 JSON"""
        raw_text = self.get(url, params=params, referer=referer, timeout=timeout, max_retries=max_retries, is_json=True, encoding=encoding)
        if not raw_text:
            return None
        try:
            # 去除可能的 jsonp 包装 (如 jQuery1234(...) 或 var xxx=...)
            cleaned = raw_text.strip()
            if cleaned.endswith(";"):
                cleaned = cleaned[:-1].strip()
            if "(" in cleaned and cleaned.endswith(")"):
                start = cleaned.find("(")
                cleaned = cleaned[start + 1 : -1].strip()
            return json.loads(cleaned)
        except Exception:
            return None

    def post_json(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        referer: Optional[str] = None,
        timeout: float = 6.0,
        max_retries: int = 2,
        encoding: str = "utf-8"
    ) -> Optional[Union[Dict[str, Any], list]]:
        """执行 POST 请求（以 Form-Urlencoded 或 JSON 形式发送）并返回解析后的 JSON"""
        for attempt in range(1, max_retries + 1):
            self._apply_rate_limit()
            try:
                encoded_data = urllib.parse.urlencode(data).encode(encoding) if data else None
                headers = self.build_headers(
                    referer=referer,
                    is_json=True,
                    custom_headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
                )
                req = urllib.request.Request(url, data=encoded_data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw_data = resp.read().decode(encoding, errors="replace")
                    return json.loads(raw_data)
            except Exception:
                if attempt == max_retries:
                    return None
                time.sleep(0.5 * attempt + random.uniform(0.1, 0.4))
        return None

# 单例全局防反爬会话
safe_session = AntiScrapingSession()
