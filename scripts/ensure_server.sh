#!/usr/bin/env bash
# ==============================================================================
# DSH A股量化筛选 Web 服务端「幂等保活」入口
# ------------------------------------------------------------------------------
# 作用：确保 127.0.0.1:<PORT> 上始终有一个健康的服务端在跑。
#   1. 若健康探针通过，直接返回 0，不做任何多余动作（同端口多实例会互相抢端口，故必须幂等）；
#   2. 若端口无响应，先清掉残留 PID 与占口进程，再拉起服务端与看门狗；
#   3. 服务端与看门狗经 scripts/daemon_launch.py 以独立会话启动，
#      脱离调用方终端/工具会话的进程组，避免父会话回收时被一起收走
#      （这是 2026-09-23 服务掉线的直接原因）。
# 用法：
#   bash scripts/ensure_server.sh              # 缺则拉起（推荐日常使用）
#   DSH_STOCK_PORT=8899 bash scripts/ensure_server.sh
# 停止：bash scripts/stop_server.sh
# ==============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PORT="${DSH_STOCK_PORT:-8888}"

if [ "${PORT}" = "8888" ]; then
  PID_FILE="${BASE_DIR}/.server.pid"
  WATCHDOG_PID_FILE="${BASE_DIR}/.watchdog.pid"
else
  PID_FILE="${BASE_DIR}/.server-${PORT}.pid"
  WATCHDOG_PID_FILE="${BASE_DIR}/.watchdog-${PORT}.pid"
fi

STATUS_URL="http://127.0.0.1:${PORT}/api/status"
SERVER_LOG="${BASE_DIR}/server.log"
WATCHDOG_LOG="${BASE_DIR}/watchdog.log"
# 需求REQ-049: 默认仅绑定本机回环；确需局域网访问时用 DSH_STOCK_HOST=0.0.0.0 显式放开
BIND_HOST="${DSH_STOCK_HOST:-127.0.0.1}"
# 需求REQ-050: 日志按大小轮转（保留最近 3 份），避免单文件无限增长
LOG_MAX_KB="${DSH_STOCK_LOG_MAX_KB:-5120}"

rotate_log() {
  local file="$1"
  [ -f "${file}" ] || return 0
  local size_kb
  size_kb="$(du -k "${file}" 2>/dev/null | awk '{print $1}')"
  [ -n "${size_kb}" ] || return 0
  if [ "${size_kb}" -ge "${LOG_MAX_KB}" ]; then
    rm -f "${file}.3"
    [ -f "${file}.2" ] && mv "${file}.2" "${file}.3"
    [ -f "${file}.1" ] && mv "${file}.1" "${file}.2"
    mv "${file}" "${file}.1"
    echo "   🗂️  日志已轮转：$(basename "${file}") → $(basename "${file}").1（原大小 ${size_kb}KB ≥ ${LOG_MAX_KB}KB）"
  fi
}

# 健康探针：必须返回 status=running
probe_healthy() {
  curl -s --max-time 3 "${STATUS_URL}" | grep -q '"status": "running"'
}

# 1. 已在健康运行：幂等返回
if probe_healthy; then
  echo "✅ 服务端已在健康运行，无需处理：${STATUS_URL}"
  exit 0
fi

echo "⚠️  端口 ${PORT} 当前无健康响应，开始拉起服务端..."

# 2. 清理残留：PID 文件里的死进程 + 仍占着端口的老进程
for f in "${PID_FILE}" "${WATCHDOG_PID_FILE}"; do
  if [ -f "${f}" ]; then
    OLD="$(cat "${f}" 2>/dev/null || true)"
    if [ -n "${OLD}" ] && kill -0 "${OLD}" 2>/dev/null; then
      echo "   正在停止残留进程 (PID: ${OLD})..."
      kill -TERM "${OLD}" 2>/dev/null || true
      sleep 0.5
      kill -9 "${OLD}" 2>/dev/null || true
    fi
    rm -f "${f}"
  fi
done

OCCUPIED="$(lsof -ti :"${PORT}" 2>/dev/null || true)"
if [ -n "${OCCUPIED}" ]; then
  echo "   正在释放端口 ${PORT} 占用进程 (PID: ${OCCUPIED})..."
  kill -9 ${OCCUPIED} 2>/dev/null || true
  sleep 0.5
fi

# 3. 以独立会话拉起服务端（真实 PID 由服务端自己写入 .server.pid）
rotate_log "${SERVER_LOG}"
rotate_log "${WATCHDOG_LOG}"

python3 "${SCRIPT_DIR}/daemon_launch.py" "${SERVER_LOG}" \
  python3 -u "${SCRIPT_DIR}/stock_web_server.py" --port "${PORT}" --host "${BIND_HOST}" > /tmp/dsh_stock_launch.pid 2>&1 || true

READY=0
for _ in $(seq 1 24); do
  if probe_healthy; then READY=1; break; fi
  sleep 0.5
done

if [ "${READY}" -ne 1 ]; then
  echo "❌ 服务端拉起失败，日志尾部如下（完整日志：${SERVER_LOG}）："
  tail -20 "${SERVER_LOG}"
  exit 1
fi
echo "✅ 服务端已就绪 (PID: $(cat "${PID_FILE}" 2>/dev/null || echo 未知))，地址：http://127.0.0.1:${PORT}"

# 4. 拉起看门狗（同样独立会话），负责后续 7x24 自愈
if [ -f "${WATCHDOG_PID_FILE}" ]; then
  OLD_WD="$(cat "${WATCHDOG_PID_FILE}" 2>/dev/null || true)"
  if [ -n "${OLD_WD}" ] && kill -0 "${OLD_WD}" 2>/dev/null; then
    echo "   已存在存活看门狗 (PID: ${OLD_WD})，跳过重复启动"
    exit 0
  fi
fi

DSH_STOCK_PORT="${PORT}" DSH_PID_FILE="${PID_FILE}" DSH_WATCHDOG_PID_FILE="${WATCHDOG_PID_FILE}" \
  python3 "${SCRIPT_DIR}/daemon_launch.py" "${WATCHDOG_LOG}" \
  python3 -u "${SCRIPT_DIR}/watchdog.py" > /dev/null 2>&1 || true
sleep 2
WD_PID="$(cat "${WATCHDOG_PID_FILE}" 2>/dev/null || true)"
if [ -n "${WD_PID}" ] && kill -0 "${WD_PID}" 2>/dev/null; then
  echo "🛡️ 看门狗已激活 (PID: ${WD_PID})，进程掉线将自动自愈"
else
  echo "⚠️ 看门狗未确认存活，日志：${WATCHDOG_LOG}"
fi
exit 0
