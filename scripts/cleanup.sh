#!/usr/bin/env bash
# ==============================================================================
# DSH A股应用清理与自毁守护脚本 (确保卸载/删除时完全释放服务)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[Cleanup] 正在清理 DSH 股票服务进程与临时文件..."
bash "${SCRIPT_DIR}/stop_server.sh" || true

rm -f "${BASE_DIR}/.server.pid"
rm -f "${BASE_DIR}/server.log"

echo "[Cleanup] 清理完毕，已无残留服务进程。"
