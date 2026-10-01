"""R10 批次回归（REQ-054 / BUG-006）：`config/version.json` 是唯一版本权威，且必须在**运行期即时生效**。

历史缺陷（BUG-006）：版本在模块导入时被读入内存，发布新版本后运行中的服务端仍返回旧版本，
于是出现「页面徽标/标题 = 旧版本」而「config/version.json = 新版本」的不一致状态，直到手工重启才恢复。

用例策略：不启动真实服务端，直接对**真实模块**做函数级验证（含 mtime 失效与文件损坏回退），
并在临时目录里真实改写版本文件——不触碰产品 config/version.json。
"""

import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = BASE_DIR / "scripts" / "stock_web_server.py"
PRODUCT_VERSION_FILE = BASE_DIR / "config" / "version.json"


def load_server_module(version_file):
    """以指定版本文件加载服务端模块（用于隔离验证，不污染产品配置）。"""
    spec = importlib.util.spec_from_file_location("r10_stock_web_server", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    module.VERSION_FILE = str(version_file)
    spec.loader.exec_module(module)
    module.VERSION_FILE = str(version_file)   # 覆盖模块内常量，使其指向临时文件
    return module


class VersionAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="r10-version-")
        self.version_file = pathlib.Path(self.tmp) / "version.json"
        self._write("v9.9.9")
        self.mod = load_server_module(self.version_file)
        self._product_hash = PRODUCT_VERSION_FILE.read_bytes()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.assertEqual(PRODUCT_VERSION_FILE.read_bytes(), self._product_hash,
                         "用例不得改动产品 config/version.json")

    def _write(self, version, description="测试版本"):
        self.version_file.write_text(json.dumps(
            {"version": version, "app_name": "A股多维量化筛选器", "subtitle": "DSH Stock Web",
             "release_date": "2026-09-24", "description": description}, ensure_ascii=False), encoding="utf-8")

    def test_reads_current_file(self):
        self.assertEqual(self.mod.current_version(), "v9.9.9")

    def test_change_takes_effect_without_restart(self):
        """核心断言：改写版本文件后，无需重启进程，下一个请求即返回新版本。"""
        self.assertEqual(self.mod.current_version(), "v9.9.9")
        time.sleep(0.01)
        self._write("v9.9.10", description="热更新版本")
        self.assertEqual(self.mod.current_version(), "v9.9.10")
        info = self.mod.current_version_info()
        self.assertEqual(info["description"], "热更新版本")
        # 再改回去也必须即时生效（不能是"只升不降"的假缓存）
        time.sleep(0.01)
        self._write("v9.9.9")
        self.assertEqual(self.mod.current_version(), "v9.9.9")

    def test_cache_reused_when_file_untouched(self):
        first = self.mod.current_version_info()
        second = self.mod.current_version_info()
        self.assertIs(first, second, "文件未变时必须复用同一份缓存（避免每请求读盘）")

    def test_missing_file_falls_back_without_crash(self):
        os.remove(self.version_file)
        info = self.mod.current_version_info()
        self.assertIn("version", info)   # 回退到上一次已知/内置默认，绝不抛异常

    def test_broken_json_falls_back_without_crash(self):
        self.version_file.write_text("{ 这不是 JSON", encoding="utf-8")
        info = self.mod.current_version_info()
        self.assertIn("version", info)
        self.assertTrue(str(info["version"]).startswith("v"))

    def test_runtime_reads_use_live_authority(self):
        """静态契约：运行期对外暴露版本的响应不得再引用启动期常量 APP_VERSION。"""
        src = SERVER_PY.read_text(encoding="utf-8")
        self.assertNotIn('"version": APP_VERSION', src,
                         "对外响应必须调用 current_version()，否则会出现「文件已升版、接口仍旧值」")
        self.assertIn('"version": current_version()', src)
        self.assertIn("def current_version()", src)
        self.assertIn("def current_version_info()", src)


if __name__ == "__main__":
    unittest.main()
