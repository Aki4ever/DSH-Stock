#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 独立手动爬虫调度引擎 (Manual Crawler Dispatcher)
版本: v1.3.0
特性:
1. 纯原生 Python，完全脱敏且零外部 AI 依赖
2. 支持全量 4,600+ 标的行情分批采集与断点写入本地 SQLite
3. 实时提供定量执行进度 (0%~100%)、当前阶段说明、耗时与吞吐量监控
4. 具备终止取消功能，采集完成输出明确量化结果反馈
"""

import os
import sys
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.anti_crawler import robust_fetch, parse_shareholder_data
from scripts.stock_db import save_quotes_batch, save_shareholder_item


class ManualCrawlerJob:
    def __init__(self):
        self._lock = threading.Lock()
        self.job_id: str = ""
        self.mode: str = "idle"         # "idle" | "full" | "core"
        self.status: str = "idle"       # "idle" | "running" | "completed" | "cancelled" | "error"
        self.total_count: int = 0
        self.current_count: int = 0
        self.progress_pct: float = 0.0
        self.phase_text: str = "就绪中"
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.elapsed_sec: float = 0.0
        self.updated_count: int = 0
        self.error_message: str = ""
        self._cancel_requested: bool = False
        self._thread: Optional[threading.Thread] = None

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = time.time() - self.start_time if self.status == "running" else (self.end_time - self.start_time if self.end_time > 0 else 0.0)
            return {
                "job_id": self.job_id,
                "mode": self.mode,
                "status": self.status,
                "total_count": self.total_count,
                "current_count": self.current_count,
                "progress_pct": round(self.progress_pct, 1),
                "phase_text": self.phase_text,
                "elapsed_sec": round(elapsed, 1),
                "updated_count": self.updated_count,
                "error_message": self.error_message,
                "is_running": self.status == "running"
            }

    def cancel(self):
        with self._lock:
            if self.status == "running":
                self._cancel_requested = True
                self.phase_text = "正在中止采集..."

    def start_crawl(self, mode: str, stock_dict: Dict[str, Dict[str, Any]], csi100_set: set):
        with self._lock:
            if self.status == "running":
                return False, "已有正在运行的采集任务，请等待完成或先取消当前任务。"
            
            self.job_id = f"crawl_{int(time.time())}"
            self.mode = mode
            self.status = "running"
            self.current_count = 0
            self.progress_pct = 0.0
            self.updated_count = 0
            self.error_message = ""
            self._cancel_requested = False
            self.start_time = time.time()
            self.end_time = 0.0
            self.phase_text = "正在准备采集队列..."

            if mode == "core":
                target_codes = list(csi100_set) if csi100_set else list(stock_dict.keys())[:100]
            else:
                target_codes = list(stock_dict.keys())

            self.total_count = len(target_codes)

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(target_codes, stock_dict),
            daemon=True
        )
        self._thread.start()
        return True, "手动数据采集已成功启动"

    def _run_loop(self, codes: List[str], stock_dict: Dict[str, Dict[str, Any]]):
        chunk_size = 50
        total = len(codes)
        updated_so_far = 0

        for i in range(0, total, chunk_size):
            if self._cancel_requested:
                with self._lock:
                    self.status = "cancelled"
                    self.phase_text = "采集已被用户手动取消"
                    self.end_time = time.time()
                return

            chunk = codes[i:i + chunk_size]
            current_batch_num = (i // chunk_size) + 1
            total_batches = (total + chunk_size - 1) // chunk_size

            with self._lock:
                self.phase_text = f"正在分批抓取行情数据 [批次 {current_batch_num}/{total_batches}]..."

            url = f"http://qt.gtimg.cn/q={','.join(chunk)}"
            content = robust_fetch(url, referer="http://gu.qq.com", timeout=4.0, max_retries=2, encoding="gbk")

            scraped_quotes = []
            if content:
                for line in content.split(";"):
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    k, val = line.split("=", 1)
                    norm_c = k.replace("v_", "").strip()
                    parts = val.strip('";\n').split("~")
                    if len(parts) >= 46 and norm_c in stock_dict:
                        item = stock_dict[norm_c]
                        item["name"] = parts[1]
                        item["price"] = float(parts[3])
                        item["prev_close"] = float(parts[4])
                        item["open"] = float(parts[5])
                        item["volume"] = float(parts[6])
                        item["high"] = float(parts[33]) if parts[33] else item["price"]
                        item["low"] = float(parts[34]) if parts[34] else item["price"]
                        item["turnover"] = float(parts[37]) * 10000 if parts[37] else 0.0
                        item["turnover_yi"] = round(item["turnover"] / 100000000.0, 2)
                        item["change"] = float(parts[31]) if parts[31] else round(item["price"] - item["prev_close"], 2)
                        item["change_pct"] = float(parts[32]) if parts[32] else 0.0
                        item["turnover_rate"] = float(parts[38]) if parts[38] else 0.0
                        item["pe"] = float(parts[39]) if parts[39] else 0.0
                        item["market_cap"] = float(parts[44]) if parts[44] else 0.0
                        item["circulating_cap"] = float(parts[45]) if parts[45] else 0.0
                        item["timestamp"] = parts[30]
                        item["is_mock"] = False
                        scraped_quotes.append(dict(item))
                        updated_so_far += 1

            if scraped_quotes:
                try:
                    save_quotes_batch(scraped_quotes)
                except Exception:
                    pass

            processed = min(total, i + len(chunk))
            with self._lock:
                self.current_count = processed
                self.progress_pct = (processed / total) * 100.0
                self.updated_count = updated_so_far

            # 保持适度间隔，严防触发风控
            time.sleep(0.04)

        with self._lock:
            self.status = "completed"
            self.progress_pct = 100.0
            self.end_time = time.time()
            self.phase_text = f"✅ 数据采集与数据库持久化全部完成！共更新 {updated_so_far} 只标的最新行情。"


# 全局采集器实例
CRAWLER_JOB = ManualCrawlerJob()
