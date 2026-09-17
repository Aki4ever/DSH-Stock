#!/usr/bin/env bash
# ==============================================================================
# DSH A股量化筛选服务端一键启动脚本
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${BASE_DIR}/.server.pid"
PORT="${DSH_STOCK_PORT:-8888}"

echo "======================================================================"
echo " 🚀 正在启动 DSH A股量化筛选 Web 服务端 (端口: ${PORT})..."
echo "======================================================================"

# 检查是否已有运行中的进程
if [ -f "${PID_FILE}" ]; then
  EXISTING_PID=$(cat "${PID_FILE}" 2>/dev/null || true)
  if [ -n "${EXISTING_PID}" ] && kill -0 "${EXISTING_PID}" 2>/dev/null; then
    echo "⚠️ 检测到服务端已在运行 (PID: ${EXISTING_PID})"
    echo "📍 网页访问地址: http://127.0.0.1:${PORT}"
    exit 0
  fi
fi

# 后台启动服务端
cd "${BASE_DIR}"
nohup python3 -u "${SCRIPT_DIR}/stock_web_server.py" --port "${PORT}" > "${BASE_DIR}/server.log" 2>&1 &
SERVER_PID=$!
echo "${SERVER_PID}" > "${PID_FILE}"

# 等待服务就绪（最多 5 秒）
echo "⏳ 正在等待服务端健康自检就绪..."
READY=0
for i in {1..10}; do
  if curl -s "http://127.0.0.1:${PORT}/api/status" | grep -q '"status": "running"'; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "${READY}" -eq 1 ]; then
  echo "✅ 服务端启动成功！(PID: ${SERVER_PID})"
  echo "🌐 浏览器访问入口: http://127.0.0.1:${PORT}"
  echo "📊 状态常显检查  : http://127.0.0.1:${PORT}/api/status"
  echo "📄 运行日志文件  : ${BASE_DIR}/server.log"
else
  echo "⚠️ 服务端正在启动中，请检查日志: cat ${BASE_DIR}/server.log"
fi
