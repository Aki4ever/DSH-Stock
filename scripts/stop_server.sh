#!/usr/bin/env bash
# ==============================================================================
# DSH A股量化筛选服务端一键安全停止脚本
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${BASE_DIR}/.server.pid"
PORT="${DSH_STOCK_PORT:-8888}"

echo "======================================================================"
echo " 🛑 正在停止 DSH A股量化筛选 Web 服务端..."
echo "======================================================================"

STOPPED=0

# 0. 先停止高可用守护进程 (Watchdog)，防止停止时被自动拉起
WATCHDOG_PID_FILE="${BASE_DIR}/.watchdog.pid"
if [ -f "${WATCHDOG_PID_FILE}" ]; then
  WD_PID=$(cat "${WATCHDOG_PID_FILE}" 2>/dev/null || true)
  if [ -n "${WD_PID}" ] && kill -0 "${WD_PID}" 2>/dev/null; then
    echo "正在停止高可用守护进程 (Watchdog PID: ${WD_PID})..."
    kill -TERM "${WD_PID}" 2>/dev/null || kill -9 "${WD_PID}" 2>/dev/null || true
  fi
  rm -f "${WATCHDOG_PID_FILE}"
fi

# 1. 优先通过 PID 文件停止
if [ -f "${PID_FILE}" ]; then
  PID=$(cat "${PID_FILE}" 2>/dev/null || true)
  if [ -n "${PID}" ] && kill -0 "${PID}" 2>/dev/null; then
    echo "正在向服务端进程 (PID: ${PID}) 发送安全关闭信号..."
    kill -TERM "${PID}" 2>/dev/null || true
    # 等待进程退出
    for i in {1..10}; do
      if ! kill -0 "${PID}" 2>/dev/null; then
        STOPPED=1
        break
      fi
      sleep 0.3
    done
    if [ "${STOPPED}" -eq 0 ]; then
      echo "⚠️ 进程未及时退出，执行强制关闭..."
      kill -9 "${PID}" 2>/dev/null || true
    fi
  fi
  rm -f "${PID_FILE}"
fi

# 2. 如果端口仍被占用，查找并释放
OCCUPIED_PID=$(lsof -ti :${PORT} 2>/dev/null || true)
if [ -n "${OCCUPIED_PID}" ]; then
  echo "正在释放端口 ${PORT} 占用的进程 (PID: ${OCCUPIED_PID})..."
  kill -9 ${OCCUPIED_PID} 2>/dev/null || true
fi

echo "✅ 服务端已成功关闭，端口 ${PORT} 已释放。"
