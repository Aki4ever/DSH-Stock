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
from pathlib import Path
import tempfile
import json
from unittest.mock import patch
from tests.market_fixtures import generate_mock_quote, generate_mock_kline

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stock_data_engine import get_quote
from scripts.stock_chart_svg import generate_stock_svg
from scripts.stock_reporter import generate_daily_report


class TestStockCliAndReports(unittest.TestCase):
    """测试 SVG 矢量绘制、综合研报输出与 CLI 终端交互"""

    def test_generate_stock_svg(self):
        q = generate_mock_quote("sh600519")
        bars = generate_mock_kline("sh600519", days=40, end_price=q.price)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        test_svg_path = os.path.join(tmp.name, "test_chart.svg")

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
        # Output and fixtures are isolated from the product report directory.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scripts').mkdir()
            cfg=root/'config.json';cfg.write_text(json.dumps({'indices':[],'watchlist':[],'portfolio':[{'code':'sh600519'}]}))
            with patch('scripts.stock_reporter.__file__',str(root/'scripts'/'stock_reporter.py')),patch('scripts.stock_reporter.get_batch_quotes',return_value=[]):
                rel=generate_daily_report(str(cfg))
            text=(root/rel).read_text()
            self.assertIn('持仓未获取',text)
            self.assertNotIn('¥0.00',text)

    def test_cli_subcommands(self):
        cli_py=os.path.join(BASE_DIR,'scripts','dsh_stock_cli.py')
        for command in ['status','--help','data-audit']:
            res=subprocess.run([sys.executable,cli_py,command],capture_output=True,text=True)
            self.assertEqual(res.returncode,0,res.stderr)
        res=subprocess.run([sys.executable,cli_py,'portfolio'],capture_output=True,text=True)
        self.assertEqual(res.returncode,1)
        self.assertIn('持仓配置未确认来源',res.stdout)


if __name__ == "__main__":
    unittest.main()
