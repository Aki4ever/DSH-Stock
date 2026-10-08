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
LAUNCHD_LOG="${BASE_DIR}/launchd.log"

# 需求REQ-128: 解释器必须绝对化。launchd 的 PATH 极简（/usr/bin:/bin:/usr/sbin:/sbin），
# 而本机 python3 实际在 ~/miniconda3/bin —— 裸 `python3` 在 launchd 环境下解析不到，
# 结果是"自启装上了但服务永远起不来"这种最隐蔽的失败。此处解析出绝对路径，
# 后续所有 python3 调用（daemon_launch.py 与服务端/看门狗本体）一律走它。
resolve_python() {
  if [ -n "${DSH_STOCK_PYTHON:-}" ] && [ -x "${DSH_STOCK_PYTHON}" ]; then
    printf '%s' "${DSH_STOCK_PYTHON}"
    return 0
  fi
  local cand
  for cand in "$(command -v python3 2>/dev/null || true)" \
              "${HOME}/miniconda3/bin/python3" \
              "${HOME}/anaconda3/bin/python3" \
              /opt/homebrew/bin/python3 \
              /usr/local/bin/python3 \
              /usr/bin/python3; do
    if [ -n "${cand}" ] && [ -x "${cand}" ]; then
      printf '%s' "${cand}"
      return 0
    fi
  done
  return 1
}
PYTHON_BIN="$(resolve_python || true)"
if [ -z "${PYTHON_BIN}" ]; then
  echo "❌ 未找到可用的 python3（可用 DSH_STOCK_PYTHON=<绝对路径> 显式指定）"
  exit 1
fi

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

# 看门狗存活判定（需求REQ-128：健康分支也必须校验它，否则"服务端在跑、看门狗死了"无人复活）
watchdog_alive() {
  local pid
  pid="$(cat "${WATCHDOG_PID_FILE}" 2>/dev/null || true)"
  if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi
  return 1
}

# 拉起看门狗（独立会话，脱离调用方进程组）
start_watchdog() {
  if watchdog_alive; then
    echo "   已存在存活看门狗 (PID: $(cat "${WATCHDOG_PID_FILE}" 2>/dev/null))，跳过重复启动"
    return 0
  fi
  rotate_log "${WATCHDOG_LOG}"
  DSH_STOCK_PORT="${PORT}" DSH_PID_FILE="${PID_FILE}" DSH_WATCHDOG_PID_FILE="${WATCHDOG_PID_FILE}" \
    "${PYTHON_BIN}" "${SCRIPT_DIR}/daemon_launch.py" "${WATCHDOG_LOG}" \
    "${PYTHON_BIN}" -u "${SCRIPT_DIR}/watchdog.py" > /dev/null 2>&1 || true
  sleep 2
  if watchdog_alive; then
    echo "🛡️ 看门狗已激活 (PID: $(cat "${WATCHDOG_PID_FILE}" 2>/dev/null))，进程掉线将自动自愈"
    return 0
  fi
  echo "⚠️ 看门狗未确认存活，日志：${WATCHDOG_LOG}"
  return 1
}

# 1. 已在健康运行：幂等返回
#    需求REQ-128：launchd 每 60 秒调用本脚本一次，若只探服务端就 return，
#    "服务端活着、看门狗死了"这种半死状态永远补不回来 —— 故健康分支必须连看门狗一起校验。
if probe_healthy; then
  if watchdog_alive; then
    echo "✅ 服务端已在健康运行，无需处理：${STATUS_URL}"
    exit 0
  fi
  echo "⚠️  服务端健康但看门狗缺席，仅补位看门狗（不重启服务端，避免打断在途请求）..."
  rotate_log "${LAUNCHD_LOG}"
  start_watchdog || exit 1
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
rotate_log "${LAUNCHD_LOG}"

"${PYTHON_BIN}" "${SCRIPT_DIR}/daemon_launch.py" "${SERVER_LOG}" \
  "${PYTHON_BIN}" -u "${SCRIPT_DIR}/stock_web_server.py" --port "${PORT}" --host "${BIND_HOST}" > /tmp/dsh_stock_launch.pid 2>&1 || true

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
start_watchdog
exit 0
