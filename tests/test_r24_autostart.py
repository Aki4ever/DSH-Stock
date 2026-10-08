#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-128 开机自启回归（网页服务开机自启常驻响应 · v5.17.0 基础设施补丁）

实测根因（详见 docs/execution/R24-REQ128-需求简化文案.md）：
    ① 工程原有 ensure_server.sh（幂等拉起）+ watchdog.py（进程级自愈）只覆盖"进程被 kill"，
       重启电脑后两者一起消失，launchd 里没有任何本项目条目 ⇒ 打开 http://127.0.0.1:8888
       必然 ERR_CONNECTION_REFUSED（watchdog.log 末行「收到停止信号」= 关机时被一起收走）。
    ② macOS TCC 保护 `~/Documents`：launchd 直接执行 /bin/bash 读工程脚本实测
       `Operation not permitted` / last exit code 126（脚本挪到 ~/Library 同样被拒），
       故默认走 electron 模式 —— 由已获文稿授权的 DSH 应用本体作为家长进程。
    ③ PID 文件竞态：抢端口失败的重复实例会把**健康实例**的 .server.pid 删掉（server.log 实证）。

本套件默认**全程离线、零触网、零 launchd 副作用**：
    · 只跑 `install_autostart.sh print`（零副作用入口）与源码/行为断言，
      绝不 install / uninstall（避免污染本机 LaunchAgents）；
    · plist 用标准库 plistlib 真解析；PID 归属逻辑用 AST 抽真函数体真跑；
    · 真机装载/自愈/重启演练由 DSH_STOCK_LIVE_TEST=1 显式开启（默认跳过）。

运行：
    python3 -m unittest tests.test_r24_autostart
    DSH_STOCK_LIVE_TEST=1 python3 -m unittest tests.test_r24_autostart   # 追加真机用例
"""

import ast
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
INSTALL = SCRIPTS / "install_autostart.sh"
ENSURE = SCRIPTS / "ensure_server.sh"
BOOTSTRAP_JS = SCRIPTS / "launchd_bootstrap.js"
START = SCRIPTS / "start_server.sh"
STOP = SCRIPTS / "stop_server.sh"
WATCHDOG = SCRIPTS / "watchdog.py"
SERVER = SCRIPTS / "stock_web_server.py"
DSH_APP_EXE = Path("/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness")

LIVE = os.environ.get("DSH_STOCK_LIVE_TEST") == "1"


def run_print(port: str = "8888", home: str = None, legacy_bash: bool = False):
    """跑 print 入口（零副作用）。home 用临时目录隔离，避免任何写盘落到真实 HOME。"""
    env = dict(os.environ)
    if home:
        env["HOME"] = home
    env["DSH_STOCK_PORT"] = port
    args = ["bash", str(INSTALL), "print"]
    if legacy_bash:
        args.append("--legacy-bash")
    return subprocess.run(args, capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)


def load_functions(*names):
    """用 AST 从 stock_web_server.py 抽出指定函数体真跑（不 import 重型模块、零副作用）。"""
    src = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = {}
    for name in names:
        node = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if node is None:
            raise AssertionError(f"stock_web_server.py 里找不到函数 {name}")
        out[name] = ast.get_source_segment(src, node)
    return src, out


class TestScriptCarriers(unittest.TestCase):
    """脚本载体与语法：文件必须在、bash/node 语法必须过、红线脚本必须没被动过。"""

    def test_files_exist(self):
        for f in (INSTALL, ENSURE, BOOTSTRAP_JS, WATCHDOG, SERVER, START, STOP):
            self.assertTrue(f.exists(), f"缺文件：{f}")

    def test_bash_syntax_ok(self):
        for f in (INSTALL, ENSURE):
            proc = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, f"{f.name} bash 语法错误：{proc.stderr}")

    def test_bootstrap_js_syntax_ok(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("本机 PATH 无 node，跳过 JS 语法校验（真机由 launchd 实跑覆盖）")
        proc = subprocess.run([node, "--check", str(BOOTSTRAP_JS)],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, f"launchd_bootstrap.js 语法错误：{proc.stderr}")

    def test_bootstrap_js_delegates_to_ensure_server(self):
        src = BOOTSTRAP_JS.read_text(encoding="utf-8")
        self.assertIn("ensure_server.sh", src, "引导器必须走唯一启动口径")
        self.assertIn("spawn('/bin/bash'", src)
        self.assertIn("process.exit", src, "必须透传退出码，launchd 才能记录 last exit code")

    def test_install_script_supports_both_modes(self):
        src = INSTALL.read_text(encoding="utf-8")
        self.assertIn("resolve_dsh_node", src, "electron 模式需要 DSH 应用本体路径解析")
        self.assertIn("--legacy-bash", src, "必须保留纯 bash 模式（需 FDA 授权）作为备用")
        self.assertIn("ELECTRON_RUN_AS_NODE", src)
        self.assertIn("TCC", src, "必须把 macOS 文稿保护这条物理约束写在载体里")


class TestEnsureServerHardening(unittest.TestCase):
    """ensure_server.sh 的三处加固（本批实测踩坑点）。"""

    def test_uses_absolute_python(self):
        src = ENSURE.read_text(encoding="utf-8")
        self.assertIn("PYTHON_BIN=", src)
        self.assertIn('"${PYTHON_BIN}" "${SCRIPT_DIR}/daemon_launch.py"', src)
        self.assertIn('"${PYTHON_BIN}" -u "${SCRIPT_DIR}/stock_web_server.py"', src)
        self.assertIn('"${PYTHON_BIN}" -u "${SCRIPT_DIR}/watchdog.py"', src)
        self.assertNotIn('python3 "${SCRIPT_DIR}/daemon_launch.py"', src)
        self.assertNotIn('python3 -u "${SCRIPT_DIR}/stock_web_server.py"', src)
        self.assertIn("miniconda3/bin/python3", src)

    def test_healthy_branch_also_revives_watchdog(self):
        """健康分支必须连看门狗一起校验，否则「服务端活着、看门狗死了」永远补不回来。"""
        src = ENSURE.read_text(encoding="utf-8")
        i_probe = src.index("if probe_healthy; then")
        i_wd = src.index("if watchdog_alive; then", i_probe)
        self.assertLess(i_probe, i_wd)
        self.assertIn("start_watchdog || exit 1", src)

    def test_launchd_log_is_rotated(self):
        src = ENSURE.read_text(encoding="utf-8")
        self.assertIn('LAUNCHD_LOG="${BASE_DIR}/launchd.log"', src)
        self.assertIn('rotate_log "${LAUNCHD_LOG}"', src)

    def test_start_stop_semantics_untouched(self):
        """本批红线：不动 start/stop 的 PID/端口口径（只做加法）。"""
        self.assertIn('.server.pid', START.read_text(encoding="utf-8"))
        self.assertIn('PORT="${DSH_STOCK_PORT:-8888}"', START.read_text(encoding="utf-8"))
        self.assertIn('.watchdog.pid', STOP.read_text(encoding="utf-8"))
        self.assertIn('PORT="${DSH_STOCK_PORT:-8888}"', STOP.read_text(encoding="utf-8"))


class TestPidFileOwnershipRace(unittest.TestCase):
    """
    REQ-128 连带修复：抢端口失败的重复实例曾删除**健康实例**的 .server.pid
    （server.log 实证：`已写入 .server.pid` 紧跟 `[Errno 48]`，随后 PID 文件消失）。
    这里用 AST 抽真函数体真跑，断言「非我所属的 PID 文件绝不动」与「绑定成功后才写」。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsh_r24_pid_")
        self.pid_file = Path(self.tmp) / ".server.pid"
        _, funcs = load_functions("cleanup_pid_file", "write_pid_file")
        self.ns = {"os": os, "PID_FILE": str(self.pid_file), "sys": sys}
        exec(funcs["cleanup_pid_file"], self.ns)          # noqa: S102 - 抽真源码真跑
        exec(funcs["write_pid_file"], self.ns)            # noqa: S102
        self.ns["os"] = os

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cleanup_removes_only_own_pid_file(self):
        self.pid_file.write_text(str(os.getpid()))
        self.ns["cleanup_pid_file"]()
        self.assertFalse(self.pid_file.exists(), "自己所属的 PID 文件应被清理")

    def test_cleanup_keeps_other_process_pid_file(self):
        self.pid_file.write_text("999999")               # 模拟健康实例（别的 PID）
        self.ns["cleanup_pid_file"]()
        self.assertTrue(self.pid_file.exists(), "⛔ 不得删除非自己所属的 PID 文件（本批修复的竞态）")
        self.assertEqual(self.pid_file.read_text(), "999999")

    def test_cleanup_is_safe_when_missing(self):
        self.ns["cleanup_pid_file"]()                    # 不存在时不得抛异常
        self.assertFalse(self.pid_file.exists())

    def test_write_pid_file_writes_own_pid(self):
        self.ns["write_pid_file"]()
        self.assertEqual(self.pid_file.read_text(), str(os.getpid()))

    def test_pid_written_after_bind(self):
        """写 PID 必须在端口绑定成功之后，否则重复实例会先覆盖健康实例的 PID。"""
        src = SERVER.read_text(encoding="utf-8")
        i_bind = src.index("SERVER_INSTANCE = ThreadingHTTPServer(server_address, StockRequestHandler)")
        i_write = src.index("write_pid_file()", src.index("def run_server("))
        self.assertLess(i_bind, i_write, "write_pid_file() 必须晚于 ThreadingHTTPServer 构造")


class TestPlistGeneration(unittest.TestCase):
    """plist 生成：真解析 + 关键键 + 端口作用域 + 零副作用（两种模式都验）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp_home = tempfile.mkdtemp(prefix="dsh_r24_home_")
        cls.proc = run_print("8888", cls.tmp_home)
        cls.ok = cls.proc.returncode == 0
        cls.plist = plistlib.loads(cls.proc.stdout.encode("utf-8")) if cls.ok else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp_home, ignore_errors=True)

    def test_print_exit_zero_and_parses(self):
        self.assertEqual(self.proc.returncode, 0, f"print 失败：{self.proc.stderr}")
        self.assertIn("Label", self.plist)

    def test_login_start_and_periodic_recheck(self):
        self.assertIs(self.plist.get("RunAtLoad"), True, "登录必须自启")
        self.assertEqual(self.plist.get("StartInterval"), 300,
                         "每 5 分钟兜底复查（秒级自愈由 watchdog 负责，launchd 只管出生与兜底）")

    def test_working_directory_and_logs_inside_project(self):
        self.assertEqual(self.plist.get("WorkingDirectory"), str(ROOT))
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertTrue(str(self.plist.get(key)).startswith(str(ROOT)))
        self.assertTrue(str(self.plist.get("StandardOutPath")).endswith("launchd.log"))

    def test_environment_is_launchd_proof(self):
        env = self.plist.get("EnvironmentVariables") or {}
        for d in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
            self.assertIn(d, env.get("PATH", ""), f"launchd 极简 PATH 必须补齐 {d}")
        self.assertEqual(env.get("DSH_STOCK_PORT"), "8888")
        py = env.get("DSH_STOCK_PYTHON", "")
        self.assertTrue(py.startswith("/") and os.access(py, os.X_OK), f"python 必须绝对可执行：{py!r}")
        self.assertIn(str(Path(py).parent), env["PATH"])

    def test_electron_mode_program_arguments(self):
        args = self.plist.get("ProgramArguments") or []
        if not DSH_APP_EXE.exists():
            self.skipTest("本机无 DSH 应用，electron 模式不适用（legacy-bash 用例已覆盖）")
        self.assertEqual(args[0], str(DSH_APP_EXE))
        self.assertTrue(args[1].endswith("/scripts/launchd_bootstrap.js"))
        self.assertTrue(Path(args[1]).exists(), "plist 指向的引导器必须真实存在（反悬空引用）")
        self.assertEqual((self.plist.get("EnvironmentVariables") or {}).get("ELECTRON_RUN_AS_NODE"), "1")

    def test_print_has_zero_side_effects(self):
        agents = Path(self.tmp_home) / "Library" / "LaunchAgents"
        self.assertFalse(agents.exists(), f"print 模式绝不允许创建 {agents}")

    def test_legacy_bash_mode_uses_ensure_server(self):
        with tempfile.TemporaryDirectory(prefix="dsh_r24_home_") as home:
            proc = run_print("8888", home, legacy_bash=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            p = plistlib.loads(proc.stdout.encode("utf-8"))
            args = p["ProgramArguments"]
            self.assertEqual(args[0], "/bin/bash")
            self.assertTrue(args[1].endswith("/scripts/ensure_server.sh"))
            self.assertTrue(Path(args[1]).exists())
            self.assertNotIn("ELECTRON_RUN_AS_NODE", p.get("EnvironmentVariables") or {})
            self.assertFalse((Path(home) / "Library" / "LaunchAgents").exists())

    def test_port_scoped_label(self):
        with tempfile.TemporaryDirectory(prefix="dsh_r24_home_") as home:
            proc = run_print("8899", home)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            p = plistlib.loads(proc.stdout.encode("utf-8"))
            self.assertEqual(p["Label"], "com.dsh.stock.web.8899",
                             "非默认端口必须用独立 Label，避免多实例互相顶掉")
            self.assertEqual((p.get("EnvironmentVariables") or {}).get("DSH_STOCK_PORT"), "8899")

    def test_invalid_action_returns_usage_code(self):
        proc = subprocess.run(["bash", str(INSTALL), "boom"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("用法", proc.stderr)


class TestStatusEntrypoint(unittest.TestCase):
    """status 入口必须在未安装时也给中文明确结论（不静默失败），且不产生副作用。"""

    def test_status_reports_without_crash(self):
        with tempfile.TemporaryDirectory(prefix="dsh_r24_home_") as home:
            env = dict(os.environ, HOME=home)
            proc = subprocess.run(["bash", str(INSTALL), "status"],
                                  capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("开机自启状态", proc.stdout)
            self.assertIn("⛔ 不存在", proc.stdout)     # 隔离 HOME 下必然未安装
            self.assertIn("健康探针", proc.stdout)
            self.assertFalse((Path(home) / "Library" / "LaunchAgents").exists())


@unittest.skipUnless(LIVE, "真机用例需 DSH_STOCK_LIVE_TEST=1（会真实起进程/占端口）")
class TestLiveAutostartOnIsolatedPort(unittest.TestCase):
    """真机：在 8899 端口验证「幂等 + 单实例 + 看门狗补位 + PID 文件不被误删」，不碰 8888。"""

    PORT = "8899"
    env = dict(os.environ, DSH_STOCK_PORT="8899")

    def _listen_pids(self):
        proc = subprocess.run(["lsof", "-nP", f"-iTCP:{self.PORT}", "-sTCP:LISTEN"],
                              capture_output=True, text=True, timeout=30)
        pids = set()
        for line in proc.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                pids.add(parts[1])
        return pids

    def _healthy(self):
        proc = subprocess.run(["curl", "-s", "--max-time", "3",
                               f"http://127.0.0.1:{self.PORT}/api/status"],
                              capture_output=True, text=True, timeout=30)
        return '"status": "running"' in proc.stdout

    def test_ensure_idempotent_single_instance(self):
        try:
            for _ in range(3):
                subprocess.run(["bash", str(ENSURE)], env=self.env, cwd=str(ROOT),
                               capture_output=True, text=True, timeout=180)
            self.assertTrue(self._healthy())
            self.assertEqual(len(self._listen_pids()), 1, "幂等失败：8899 上出现多实例")
            wd = ROOT / f".watchdog-{self.PORT}.pid"
            self.assertTrue(wd.exists(), "看门狗 PID 文件缺失")
            try:
                os.kill(int(wd.read_text().strip()), 0)
            except (OSError, ValueError) as exc:
                self.fail(f"看门狗进程不存在或 PID 非法：{exc}")
        finally:
            subprocess.run(["bash", str(STOP)], env=self.env, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=120)

    def test_duplicate_instance_keeps_healthy_pid_file(self):
        """重复实例抢端口失败，绝不能删掉健康实例的 PID 文件（本批修复的竞态端到端验证）。"""
        try:
            subprocess.run(["bash", str(ENSURE)], env=self.env, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=180)
            pid_file = ROOT / f".server-{self.PORT}.pid"
            self.assertTrue(pid_file.exists(), "健康实例必须写下 PID 文件")
            owner = pid_file.read_text().strip()
            subprocess.run([sys.executable, "-u", str(SERVER), "--port", self.PORT, "--host", "127.0.0.1"],
                           env=dict(self.env, DSH_PID_FILE=str(pid_file)),
                           cwd=str(ROOT), capture_output=True, text=True, timeout=120)
            self.assertTrue(pid_file.exists(), "⛔ 重复实例把健康实例的 PID 文件删掉了")
            self.assertEqual(pid_file.read_text().strip(), owner)
            self.assertTrue(self._healthy())
        finally:
            subprocess.run(["bash", str(STOP)], env=self.env, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
