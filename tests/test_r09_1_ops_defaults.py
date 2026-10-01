"""R09.1 补丁（v5.4.1）静态回归：安全默认（回环绑定）、日志轮转、测试资产归档、首屏副图档位口径。

对应需求：REQ-049（默认仅绑定本机回环）/ REQ-050（日志按大小轮转）/ REQ-051（R05 快照归档）/ REQ-037 修订（首屏副图统一）。
口径：只做**真实文件与真实函数**的断言，不 mock 产品实现；涉及进程的项只验证传参链路，不启动服务端。
"""

import importlib.util
import os
import pathlib
import re
import unittest
from unittest import mock

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = BASE_DIR / "scripts" / "stock_web_server.py"
ENSURE_SH = BASE_DIR / "scripts" / "ensure_server.sh"
WATCHDOG_PY = BASE_DIR / "scripts" / "watchdog.py"
APP_JS = BASE_DIR / "web" / "app.js"


def load_server_module():
    """按文件路径加载服务端模块（模块名唯一，避免与其它测试相互污染）。"""
    spec = importlib.util.spec_from_file_location("r091_stock_web_server", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBindHostDefaults(unittest.TestCase):
    """REQ-049：默认只绑定本机回环，环境变量与 CLI 参数可显式放开。"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_server_module()

    def test_default_is_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DSH_STOCK_HOST", None)
            self.assertEqual(self.mod.resolve_bind_host(None), "127.0.0.1")

    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"DSH_STOCK_HOST": "0.0.0.0"}):
            self.assertEqual(self.mod.resolve_bind_host(None), "0.0.0.0")
            # 环境变量优先于 CLI 参数（保活脚本/看门狗以环境变量下发口径）
            self.assertEqual(self.mod.resolve_bind_host("192.168.1.10"), "0.0.0.0")

    def test_cli_override_when_no_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DSH_STOCK_HOST", None)
            self.assertEqual(self.mod.resolve_bind_host("0.0.0.0"), "0.0.0.0")

    def test_blank_values_fall_back_to_loopback(self):
        with mock.patch.dict(os.environ, {"DSH_STOCK_HOST": "   "}):
            self.assertEqual(self.mod.resolve_bind_host(None), "127.0.0.1")
            self.assertEqual(self.mod.resolve_bind_host("  "), "127.0.0.1")

    def test_run_server_signature_default_is_loopback(self):
        import inspect

        sig = inspect.signature(self.mod.run_server)
        self.assertEqual(sig.parameters["host"].default, "127.0.0.1")

    def test_argparse_default_is_none_so_env_can_apply(self):
        src = SERVER_PY.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--host", type=str, default=None', src)
        self.assertIn("run_server(host=resolve_bind_host(args.host)", src)
        # 旧的世界可见默认值不得再出现在 argparse 里
        self.assertNotIn('default="0.0.0.0"', src)


class TestOpsScriptsWiring(unittest.TestCase):
    """REQ-049/050：保活脚本与看门狗同口径传参 + 日志轮转实现。"""

    @classmethod
    def setUpClass(cls):
        cls.sh = ENSURE_SH.read_text(encoding="utf-8")
        cls.wd = WATCHDOG_PY.read_text(encoding="utf-8")

    def test_ensure_server_passes_bind_host(self):
        self.assertIn('BIND_HOST="${DSH_STOCK_HOST:-127.0.0.1}"', self.sh)
        self.assertIn('--host "${BIND_HOST}"', self.sh)

    def test_watchdog_passes_bind_host(self):
        self.assertIn('os.environ.get("DSH_STOCK_HOST", "127.0.0.1")', self.wd)
        self.assertIn('"--host", bind_host', self.wd)

    def test_no_hardcoded_world_binding_left(self):
        # 只检查真实代码行（注释里说明「可用 DSH_STOCK_HOST=0.0.0.0 放开」是应当保留的文档）
        sh_code = "\n".join(l for l in self.sh.splitlines() if not l.strip().startswith("#"))
        self.assertNotIn("0.0.0.0", sh_code)
        self.assertNotIn('"0.0.0.0"', self.wd)

    def test_rotate_log_implementation(self):
        self.assertIn("rotate_log()", self.sh)
        self.assertIn('LOG_MAX_KB="${DSH_STOCK_LOG_MAX_KB:-5120}"', self.sh)
        # 轮转必须在拉起服务端之前执行（否则本轮日志会先写进旧文件）
        self.assertLess(self.sh.index('rotate_log "${SERVER_LOG}"'),
                        self.sh.index('daemon_launch.py" "${SERVER_LOG}"'))
        # 保留 3 份历史：.3 被删除、.1/.2 依次后移
        self.assertIn('rm -f "${file}.3"', self.sh)
        self.assertIn('mv "${file}.2" "${file}.3"', self.sh)
        self.assertIn('mv "${file}.1" "${file}.2"', self.sh)
        self.assertIn('mv "${file}" "${file}.1"', self.sh)

    def test_rotate_log_threshold_is_configurable_and_reported(self):
        self.assertIn("DSH_STOCK_LOG_MAX_KB", self.sh)
        self.assertIn("日志已轮转", self.sh)


class TestR05SnapshotArchived(unittest.TestCase):
    """REQ-051：R05 过时快照脚本必须已从 tests/ 移出，归档件保留历史声明。"""

    def test_not_in_tests_dir(self):
        self.assertFalse((BASE_DIR / "tests" / "browser_r05_verify.js").exists(),
                         "tests/ 下不应再存在基于旧口径的 R05 快照脚本")

    def test_archived_copy_exists_with_header(self):
        archived = BASE_DIR / "docs" / "verification" / "2026-09-20-r05" / "browser_r05_verify.snapshot.js"
        self.assertTrue(archived.exists(), "归档副本应存在")
        head = archived.read_text(encoding="utf-8")[:1200]
        self.assertIn("历史快照说明", head)
        self.assertIn("不再代表现行需求", head)

    def test_no_doc_still_points_at_old_path_as_a_gate(self):
        offenders = []
        for path in list((BASE_DIR / "docs").rglob("*.md")) + [BASE_DIR / "README.md"]:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                # 只拦「把它当作可运行入口」的写法（如 `node tests/browser_r05_verify.js`）；
                # 说明文件搬迁去向的记录行（含 → 归档路径）不算违规
                if "node tests/browser_r05_verify.js" in line and "~~" not in line:
                    offenders.append(f"{path.relative_to(BASE_DIR)}: {line.strip()[:80]}")
        self.assertEqual(offenders, [], f"仍有文档把旧路径当作可运行入口：{offenders}")


class TestFirstScreenSubplotUnified(unittest.TestCase):
    """REQ-037 修订：首屏两图默认副图统一为成交额（与唯一「幅图联动」控件高亮一致）。"""

    @classmethod
    def setUpClass(cls):
        cls.js = APP_JS.read_text(encoding="utf-8")

    def test_panel_default_subplot_returns_amt(self):
        body = re.search(r"function panelDefaultSubplot\(_st\) \{\s*return '(\w+)';\s*\}", self.js)
        self.assertIsNotNone(body, "panelDefaultSubplot 实现缺失或签名已变")
        self.assertEqual(body.group(1), "amt")

    def test_timeline_branch_no_longer_forces_vol(self):
        body = re.search(r"function panelDefaultSubplot\([^)]*\)\s*\{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(body)
        self.assertNotIn("'vol'", body.group(1), "首屏默认档位不应再按维度分叉")

    def test_chart_state_default_is_amt(self):
        block = re.search(r"subplot:\s*'(\w+)',\s*\n\s*subplotTouched", self.js)
        self.assertIsNotNone(block, "createPanelChartState 的 subplot 默认值定位失败")
        self.assertEqual(block.group(1), "amt")
        self.assertNotIn("dimension === 'kline' ? 'amt' : 'vol'", self.js)

    def test_manual_choice_protection_kept(self):
        body = re.search(r"function applyDefaultSubplot\(st\) \{(.*?)\n\}", self.js, re.S).group(1)
        self.assertIn("if (!st.subplotTouched)", body)
        self.assertIn("panelDefaultSubplot(st)", body)


if __name__ == "__main__":
    unittest.main()
