#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Stock Server Watchdog (高可用自愈守护进程)
功能:
1. 持续监测 127.0.0.1:8888 端口与 /api/status 健康端点
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
PORT = 8888
PID_FILE = os.path.join(BASE_DIR, ".server.pid")
WATCHDOG_PID_FILE = os.path.join(BASE_DIR, ".watchdog.pid")
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

def restart_server():
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
    proc = subprocess.Popen(
        [sys.executable, "-u", SERVER_SCRIPT, "--port", str(PORT)],
        cwd=BASE_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    log(f"✅ 服务端已成功重新拉起 (新 PID: {proc.pid})，正在等待就绪...")
    time.sleep(1.5)

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
        else:
            consecutive_failures += 1
            log(f"⚠️ 健康探针未通过 (连续失败 {consecutive_failures} 次)")
            if consecutive_failures >= 2:
                restart_server()
                consecutive_failures = 0

if __name__ == "__main__":
    main()
