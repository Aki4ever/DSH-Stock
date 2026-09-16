#!/usr/bin/env bash
# ==============================================================================
# 脚本名称：rename_session.sh
# 功能描述：通过 DSH 后台 HTTP RPC 接口，为当前会话重命名并锁定侧边栏标题
# 使用方式：./scripts/rename_session.sh "新标题" [sessionId] [webUrl]
# ==============================================================================

set -euo pipefail

TITLE="${1:-}"
SESSION_ID="${2:-${DSH_SESSION_ID:-}}"
WEB_URL="${3:-${DSH_WEB_URL:-http://127.0.0.1:50447}}"

if [[ -z "$TITLE" ]]; then
  echo "❌ 错误: 必须提供会话标题参数。示例: $0 '[R003][70分] 任务简要概述'" >&2
  exit 1
fi

if [[ -z "$SESSION_ID" ]]; then
  echo "❌ 错误: 未检测到 DSH_SESSION_ID 环境变量，也未手动指定会话 ID。" >&2
  exit 1
fi

RPC_ID="rename-$(date +%s%N 2>/dev/null || date +%s)"

PAYLOAD=$(cat <<EOF
{
  "type": "client-request",
  "rpcId": "${RPC_ID}",
  "method": "session.rename",
  "payload": {
    "sessionId": "${SESSION_ID}",
    "title": "${TITLE}"
  }
}
EOF
)

RESPONSE=$(curl -s -X POST "${WEB_URL}/api/session.rename" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}")

if echo "$RESPONSE" | grep -q '"ok":true'; then
  echo "✅ 成功重命名会话为: ${TITLE}"
  exit 0
else
  echo "❌ 重命名失败，服务器响应: ${RESPONSE}" >&2
  exit 1
fi
