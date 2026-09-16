#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVG 图表、综合研报与 CLI 命令自动化测试套件 (Test Stock CLI, SVG & Report)
映射需求: REQ-005, REQ-006
"""

import unittest
import os
import sys
import subprocess

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stock_data_engine import get_quote, generate_mock_kline
from scripts.stock_chart_svg import generate_stock_svg
from scripts.stock_reporter import generate_daily_report


class TestStockCliAndReports(unittest.TestCase):
    """测试 SVG 矢量绘制、综合研报输出与 CLI 终端交互"""

    def test_generate_stock_svg(self):
        q = get_quote("sh600519", allow_mock=True)
        bars = generate_mock_kline("sh600519", days=40, end_price=q.price)
        test_svg_path = os.path.join(BASE_DIR, "reports", "charts", "test_chart.svg")

        svg_content = generate_stock_svg(q, bars, output_path=test_svg_path)
        self.assertTrue(os.path.exists(test_svg_path))
        self.assertIn("<svg", svg_content)
        self.assertIn("</svg>", svg_content)
        self.assertIn("MA5", svg_content)
        self.assertIn("MA10", svg_content)
        self.assertIn("MA20", svg_content)
        self.assertIn("VOL", svg_content)

        # 清理单测生成的临时测试文件
        if os.path.exists(test_svg_path):
            os.remove(test_svg_path)

    def test_generate_daily_report(self):
        rep_rel = generate_daily_report()
        full_path = os.path.join(BASE_DIR, rep_rel)
        self.assertTrue(os.path.exists(full_path))

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("DSH 股票量化与自选监控综合研报", content)
        self.assertIn("核心大盘指数扫描", content)
        self.assertIn("自选股池 100 分制多空量化雷达", content)
        self.assertIn("投资组合持仓体检与浮动盈亏看板", content)
        self.assertIn("reports/charts/", content)

    def test_cli_subcommands(self):
        """测试 CLI 命令行终端各子命令退出码与输出无崩溃"""
        cli_py = os.path.join(BASE_DIR, "scripts", "dsh_stock_cli.py")

        # 1. 测试 status
        res_status = subprocess.run([sys.executable, cli_py, "status"], capture_output=True, text=True)
        self.assertEqual(res_status.returncode, 0)
        self.assertIn("DSH 股票工程环境状态概要", res_status.stdout)

        # 2. 测试 list
        res_list = subprocess.run([sys.executable, cli_py, "list"], capture_output=True, text=True)
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("核心大盘基准指数", res_list.stdout)

        # 3. 测试 quote
        res_quote = subprocess.run([sys.executable, cli_py, "quote", "600519", "300750"], capture_output=True, text=True)
        self.assertEqual(res_quote.returncode, 0)
        self.assertIn("sh600519", res_quote.stdout)

        # 4. 测试 analyze
        res_ana = subprocess.run([sys.executable, cli_py, "analyze", "600519"], capture_output=True, text=True)
        self.assertEqual(res_ana.returncode, 0)
        self.assertIn("多空量化深度体检报告", res_ana.stdout)

        # 5. 测试 portfolio
        res_port = subprocess.run([sys.executable, cli_py, "portfolio"], capture_output=True, text=True)
        self.assertEqual(res_port.returncode, 0)
        self.assertIn("投资组合资产全景看板", res_port.stdout)


if __name__ == "__main__":
    unittest.main()
