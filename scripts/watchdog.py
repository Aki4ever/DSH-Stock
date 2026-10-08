#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Stock Server Watchdog (高可用自愈守护进程)
功能:
1. 持续监测 127.0.0.1:<DSH_STOCK_PORT|8888> 端口与 /api/status 健康端点
2. 当发现服务失去响应、端口拒绝连接或进程意外退出时，1秒内自动平滑拉起服务
3. 记录自愈日志与异常重启次数，保障 7x24 小时高可用在线
"""

import os
import sys
import time
import signal
import urllib.request
import json
import subprocess
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
def _port_scoped(port: str, default_name: str, template: str) -> str:
    """默认端口沿用既有文件名（保持运维习惯），其他端口独立命名，避免多实例互相覆盖。"""
    return os.path.join(BASE_DIR, default_name if port == "8888" else template.format(port=port))


PORT = int(os.environ.get("DSH_STOCK_PORT") or 8888)
_P = str(PORT)
PID_FILE = os.environ.get("DSH_PID_FILE") or _port_scoped(_P, ".server.pid", ".server-{port}.pid")
WATCHDOG_PID_FILE = os.environ.get("DSH_WATCHDOG_PID_FILE") or _port_scoped(_P, ".watchdog.pid", ".watchdog-{port}.pid")
SERVER_SCRIPT = os.path.join(CURRENT_DIR, "stock_web_server.py")
WATCHDOG_LOG = os.path.join(BASE_DIR, "watchdog.log")

STOP_REQUESTED = False

def log(msg: str):
    t_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{t_str}] [Watchdog] {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

def handle_exit(signum=None, frame=None):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    log("收到停止信号，退出看门狗守护...")
    if os.path.exists(WATCHDOG_PID_FILE):
        try:
            os.remove(WATCHDOG_PID_FILE)
        except Exception:
            pass
    sys.exit(0)

def is_server_healthy() -> bool:
    try:
        url = f"http://127.0.0.1:{PORT}/api/status"
        req = urllib.request.Request(url, headers={"User-Agent": "DSH-Watchdog-Probe"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") in ("running", "stopped")
    except Exception:
        pass
    return False

# 需求REQ-128: 冷启动宽限期。
# 实测根因（2026-10-08 终局验收抓到的抖动死循环）：旧实现拉起服务端后只 sleep(1.5)
# 就交回主循环，而主循环 2 秒一探、连续失败 2 次即重启 —— 本机服务端要全量加载 SQLite
# 底册（4,601 只）后才 bind，实测首次可服务约 5~10 秒，于是看门狗**反复 SIGKILL 自己
# 刚刚拉起的实例**，watchdog.log 实证：19450 → 19473 … 每次存活不到 7 秒，服务永远起不来。
# 修法：拉起后带**有界宽限期**等待就绪，且宽限期内既不判失败也不重启。
SPAWN_GRACE_SECONDS = 30.0
_last_proc = None
_last_spawn_at = 0.0


def child_starting() -> bool:
    """是否处于"刚拉起、仍在冷启动"的宽限期内（此时绝不允许再杀、再拉）。"""
    global _last_proc, _last_spawn_at
    if _last_proc is None:
        return False
    if _last_proc.poll() is not None:      # 进程已退出 → 不是"在启动"，走正常失败/重启判定
        return False
    return (time.time() - _last_spawn_at) < SPAWN_GRACE_SECONDS


def wait_ready(timeout: float = SPAWN_GRACE_SECONDS) -> bool:
    """有界等待服务端就绪；期间响应停止信号。"""
    deadline = time.time() + timeout
    while time.time() < deadline and not STOP_REQUESTED:
        if is_server_healthy():
            return True
        time.sleep(0.5)
    return is_server_healthy()

def restart_server():
    global _last_proc, _last_spawn_at
    log("⚠️ 探测到 Web 服务端未响应或进程退出，正在执行自动自愈重启...")
    # 1. 尝试清理残留进程或占用端口
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_p = int(f.read().strip())
            os.kill(old_p, signal.SIGKILL)
        except Exception:
            pass
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
    time.sleep(0.5)

    # 2. 启动服务
    log_file = open(os.path.join(BASE_DIR, "server.log"), "a", encoding="utf-8")
    env = dict(os.environ)
    env["DSH_STOCK_PORT"] = str(PORT)
    env["DSH_PID_FILE"] = PID_FILE
    # 需求REQ-049: 与保活入口同口径 —— 默认仅绑定本机回环，DSH_STOCK_HOST 可显式放开
    bind_host = os.environ.get("DSH_STOCK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    proc = subprocess.Popen(
        [sys.executable, "-u", SERVER_SCRIPT, "--port", str(PORT), "--host", bind_host],
        cwd=BASE_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    _last_proc = proc
    _last_spawn_at = time.time()
    log(f"✅ 服务端已成功重新拉起 (新 PID: {proc.pid})，正在等待就绪...")

    # 3. 有界等待真正就绪（需求REQ-128：旧实现只 sleep(1.5) 就交回主循环 → 抖动死循环）
    if wait_ready(SPAWN_GRACE_SECONDS):
        log(f"✅ 服务端已在宽限期内就绪 (PID: {proc.pid}，用时 {time.time() - _last_spawn_at:.1f}s)")
    else:
        alive = proc.poll() is None
        log(f"⚠️ 服务端在 {SPAWN_GRACE_SECONDS:.0f} 秒宽限期内未就绪（进程存活={alive}），交由下一轮判定")

def main():
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    with open(WATCHDOG_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log(f"🚀 高可用自愈守护进程已启动 (Watchdog PID: {os.getpid()})，保护端口: {PORT}")

    consecutive_failures = 0

    while not STOP_REQUESTED:
        time.sleep(2.0)
        if is_server_healthy():
            consecutive_failures = 0
        elif child_starting():
            # 需求REQ-128: 冷启动宽限期内**不判失败、不重启** ——
            # 旧实现在这里连续失败 2 次就 SIGKILL 掉自己刚拉起的实例（抖动死循环）。
            continue
        else:
            consecutive_failures += 1
            log(f"⚠️ 健康探针未通过 (连续失败 {consecutive_failures} 次)")
            if consecutive_failures >= 2:
                restart_server()
                consecutive_failures = 0

if __name__ == "__main__":
    main()
