#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 后台守护启动器（macOS 无 setsid 的替代方案）

背景：2026-09-23 服务掉线的直接原因是服务端与看门狗都随调用方会话一起被 TERM 回收。
本脚本用 os.setsid / start_new_session 让子进程进入独立会话与进程组，
从而不再受调用方终端、工具会话或进程组回收的影响。

用法：
    python3 scripts/daemon_launch.py <日志文件> <可执行文件> [参数...]

说明：
    - 子进程标准输出/错误追加写入 <日志文件>；
    - 打印子进程真实 PID（服务端会把该 PID 写入 .server.pid，自行覆盖本脚本的写入）。
"""

import os
import sys
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write("用法: python3 daemon_launch.py <日志文件> <可执行文件> [参数...]\n")
        return 2

    log_path, program, args = sys.argv[1], sys.argv[2], sys.argv[3:]

    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(
        f"\n[daemon_launch] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"拉起: {program} {' '.join(args)}\n"
    )
    log_file.flush()

    try:
        proc = subprocess.Popen(
            [program, *args],
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # 关键：独立会话/进程组，脱离调用方回收范围
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001 - 启动失败需如实报出
        sys.stderr.write(f"启动失败: {exc}\n")
        return 1

    print(proc.pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
