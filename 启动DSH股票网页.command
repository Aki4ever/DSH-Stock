#!/usr/bin/env bash
# ==============================================================================
# DSH A股量化筛选 · 双击启动入口（需求 REQ-128 · 方案B 兜底）
# ------------------------------------------------------------------------------
# 用途：不依赖开机自启、也不需要任何系统授权 —— 在访达里**双击本文件**即可：
#   ① 幂等拉起服务端（复用唯一启动口径 scripts/ensure_server.sh）
#   ② 等健康探针通过后自动打开浏览器到 http://127.0.0.1:8888
#   ③ 若起不来，**当面给出中文原因与日志路径**，绝不留下 ERR_CONNECTION_REFUSED 白屏
#
# 首次双击时 macOS 可能弹出「终端 想要访问"文稿"文件夹」——点「允许」即可（仅一次）。
# 想彻底免双击、开机即响应：跑 `bash scripts/install_autostart.sh install`（见 README/需求文案）。
# ==============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${DSH_STOCK_PORT:-8888}"
URL="http://127.0.0.1:${PORT}"
STATUS_URL="${URL}/api/status"
SERVER_LOG="${SCRIPT_DIR}/server.log"

printf '\033[1mDSH A股量化筛选 · 本地网页启动器\033[0m\n'
printf '工程目录：%s\n\n' "${SCRIPT_DIR}"

printf '⏳ 正在确认服务端（幂等，已在跑则直接复用）...\n'
bash "${SCRIPT_DIR}/scripts/ensure_server.sh" || true

READY=0
for _ in $(seq 1 30); do
  if curl -s --max-time 3 "${STATUS_URL}" | grep -q '"status": "running"'; then
    READY=1
    break
  fi
  sleep 1
done

if [ "${READY}" -eq 1 ]; then
  printf '\033[32m✅ 服务端已就绪：%s\033[0m\n' "${URL}"
  printf '🌐 正在打开浏览器...\n'
  open "${URL}" 2>/dev/null || printf '（浏览器未自动打开，请手动访问 %s）\n' "${URL}"
  exit 0
fi

printf '\033[31m❌ 服务端未能就绪。\033[0m\n\n'
printf '排查线索（按顺序看）：\n'
printf '  1) 日志尾部（完整：%s）：\n' "${SERVER_LOG}"
if [ -f "${SERVER_LOG}" ]; then
  tail -20 "${SERVER_LOG}" | sed 's/^/     /'
else
  printf '     （暂无 %s，说明服务端从未成功启动到写日志这一步）\n' "${SERVER_LOG}"
fi
printf '  2) 端口占用：lsof -nP -iTCP:%s -sTCP:LISTEN\n' "${PORT}"
printf '  3) 解释器：%s/bin/python3（launchd/访达环境下必须绝对路径）\n' "${HOME}/miniconda3"
printf '\n（按任意键关闭本窗口）'
read -r -n 1 -s
exit 1
