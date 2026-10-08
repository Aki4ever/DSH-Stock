#!/usr/bin/env bash
# ==============================================================================
# DSH A股量化筛选服务端 · 开机自启安装/卸载/状态（需求 REQ-128）
# ------------------------------------------------------------------------------
# 需求根因（2026-10-08 实测，非推测）：
#   工程原本已有两道保活 —— scripts/ensure_server.sh（幂等拉起）+ scripts/watchdog.py
#   （进程级自愈）。但两者都只在"进程被别人 kill 掉"这类场景有效：
#   重启电脑后进程与看门狗一起消失，`~/Library/LaunchAgents` 里**没有任何本项目条目**，
#   于是用户打开 http://127.0.0.1:8888 必然拿到 ERR_CONNECTION_REFUSED
#   （留痕：watchdog.log 末行「收到停止信号，退出看门狗守护」= 关机时被一起收走）。
#
# 本脚本补的正是"出生"这一环：注册**用户级 LaunchAgent**（不需要 sudo、不写 /Library）：
#   · RunAtLoad         → 登录即拉起
#   · StartInterval 300 → 每 5 分钟兜底复查（服务端/看门狗都掉了才需要它）
#   · ProgramArguments  → **只调用** ensure_server.sh（唯一启动口径、幂等）
# 刻意不在此脚本里自己起服务端：否则就是第二套 PID/端口语义，会与 watchdog 抢端口。
#
# ⚠️ macOS TCC 实测（本批最重要的一条物理约束）：
#   `~/Documents` 受 TCC 保护，**launchd 直接执行 /bin/bash 读工程脚本会被拒**
#   （实测 launchd.log：`Operation not permitted` · last exit code = 126）。
#   故默认采用 electron 模式：由**已获得文稿授权的 DSH 应用本体**作为家长进程
#   （ELECTRON_RUN_AS_NODE=1）运行 scripts/launchd_bootstrap.js，再拉起 ensure_server.sh
#   —— 实测同机 READ_DOCUMENTS=ok，零授权、全自动。
#   若本机没有 DSH 应用（或不想借用），用 `--legacy-bash` 走纯 bash 模式，
#   该模式需用户一次性授予 `/bin/bash` 完全磁盘访问权限，否则必然 126 失败
#   （脚本会显式告警，不静默）。
#
# 用法：
#   bash scripts/install_autostart.sh install              # 安装并装载（默认 electron 模式，幂等）
#   bash scripts/install_autostart.sh install --legacy-bash # 纯 bash 模式（需一次性 FDA 授权）
#   bash scripts/install_autostart.sh status               # 查看装载状态与健康探针
#   bash scripts/install_autostart.sh uninstall            # 卸载自启（不停止已在跑的服务端）
#   bash scripts/install_autostart.sh print [--legacy-bash] # 仅把 plist 打到 stdout（零副作用）
# 环境变量：
#   DSH_STOCK_PORT   监听端口（默认 8888；非默认端口自动使用独立 Label，多实例互不干扰）
#   DSH_STOCK_PYTHON 显式指定 python3 绝对路径
#   DSH_DESKTOP_NODE_EXECUTABLE 显式指定 DSH 应用本体可执行文件（electron 模式）
# 退出码：0 成功；1 失败；2 用法错误
# ==============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PORT="${DSH_STOCK_PORT:-8888}"

# ── 参数解析：动作 + 可选模式开关 ────────────────────────────────────────────
ACTION="install"
MODE="auto"
for arg in "$@"; do
  case "${arg}" in
    install|uninstall|status|print) ACTION="${arg}" ;;
    --legacy-bash) MODE="bash" ;;
    --electron) MODE="electron" ;;
    *) echo "用法: bash scripts/install_autostart.sh [install|uninstall|status|print] [--legacy-bash|--electron]" >&2; exit 2 ;;
  esac
done

# Label 按端口区分：默认端口沿用固定名（运维习惯），其他端口独立命名，避免多实例互相顶掉。
if [ "${PORT}" = "8888" ]; then
  LABEL="com.dsh.stock.web"
else
  LABEL="com.dsh.stock.web.${PORT}"
fi
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST="${PLIST_DIR}/${LABEL}.plist"
LAUNCHD_LOG="${BASE_DIR}/launchd.log"
BOOTSTRAP_JS="${SCRIPT_DIR}/launchd_bootstrap.js"
ENSURE_SH="${SCRIPT_DIR}/ensure_server.sh"
DOMAIN="gui/$(id -u)"
STATUS_URL="http://127.0.0.1:${PORT}/api/status"

xml_escape() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# 解释器绝对化（与 ensure_server.sh 同一口径）：launchd 的 PATH 极简，
# 本机 python3 实际在 ~/miniconda3/bin，裸 `python3` 在 launchd 环境下解析不到 ——
# 那会导致"自启装上了但服务永远起不来"这种最隐蔽的失败，故必须解析成绝对路径写进 plist。
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

# DSH 应用本体（electron 模式的家长进程）：它已有文稿授权，能把该授权传给子进程。
resolve_dsh_node() {
  if [ -n "${DSH_DESKTOP_NODE_EXECUTABLE:-}" ] && [ -x "${DSH_DESKTOP_NODE_EXECUTABLE}" ]; then
    printf '%s' "${DSH_DESKTOP_NODE_EXECUTABLE}"
    return 0
  fi
  local cand
  for cand in "/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness" \
              "${HOME}/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness"; do
    if [ -x "${cand}" ]; then
      printf '%s' "${cand}"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(resolve_python || true)"
if [ -z "${PYTHON_BIN}" ]; then
  echo "❌ 未找到可用的 python3（可用 DSH_STOCK_PYTHON=<绝对路径> 显式指定）" >&2
  exit 1
fi
PY_DIR="$(dirname "${PYTHON_BIN}")"
PLIST_PATH_ENV="${PY_DIR}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
DSH_NODE_BIN="$(resolve_dsh_node || true)"

if [ "${MODE}" = "auto" ]; then
  if [ -n "${DSH_NODE_BIN}" ]; then MODE="electron"; else MODE="bash"; fi
fi
if [ "${MODE}" = "electron" ] && [ -z "${DSH_NODE_BIN}" ]; then
  echo "❌ electron 模式要求 DSH 应用本体可执行文件存在（可用 DSH_DESKTOP_NODE_EXECUTABLE 指定），或改用 --legacy-bash" >&2
  exit 1
fi

render_plist() {
  if [ "${MODE}" = "electron" ]; then
    cat <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$(xml_escape "${LABEL}")</string>
	<!-- REQ-128: 经 DSH 应用本体（com.deepseek.dsh，已有文稿授权）作为家长进程，
	     绕开 macOS TCC 对 ~/Documents 的拦截；再拉起 ensure_server.sh（唯一启动口径）。 -->
	<key>ProgramArguments</key>
	<array>
		<string>$(xml_escape "${DSH_NODE_BIN}")</string>
		<string>$(xml_escape "${BOOTSTRAP_JS}")</string>
	</array>
	<key>WorkingDirectory</key>
	<string>$(xml_escape "${BASE_DIR}")</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>ELECTRON_RUN_AS_NODE</key>
		<string>1</string>
		<key>PATH</key>
		<string>$(xml_escape "${PLIST_PATH_ENV}")</string>
		<key>DSH_STOCK_PORT</key>
		<string>$(xml_escape "${PORT}")</string>
		<key>DSH_STOCK_PYTHON</key>
		<string>$(xml_escape "${PYTHON_BIN}")</string>
	</dict>
	<key>RunAtLoad</key>
	<true/>
	<key>StartInterval</key>
	<integer>300</integer>
	<key>ThrottleInterval</key>
	<integer>10</integer>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>$(xml_escape "${LAUNCHD_LOG}")</string>
	<key>StandardErrorPath</key>
	<string>$(xml_escape "${LAUNCHD_LOG}")</string>
</dict>
</plist>
PLIST_EOF
  else
    cat <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$(xml_escape "${LABEL}")</string>
	<!-- REQ-128 legacy-bash 模式：⚠️ 必须先给 /bin/bash 授予「完全磁盘访问权限」，
	     否则 macOS TCC 会拒读 ~/Documents（实测退出码 126 / Operation not permitted）。 -->
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>$(xml_escape "${ENSURE_SH}")</string>
	</array>
	<key>WorkingDirectory</key>
	<string>$(xml_escape "${BASE_DIR}")</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>$(xml_escape "${PLIST_PATH_ENV}")</string>
		<key>DSH_STOCK_PORT</key>
		<string>$(xml_escape "${PORT}")</string>
		<key>DSH_STOCK_PYTHON</key>
		<string>$(xml_escape "${PYTHON_BIN}")</string>
	</dict>
	<key>RunAtLoad</key>
	<true/>
	<key>StartInterval</key>
	<integer>300</integer>
	<key>ThrottleInterval</key>
	<integer>10</integer>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>$(xml_escape "${LAUNCHD_LOG}")</string>
	<key>StandardErrorPath</key>
	<string>$(xml_escape "${LAUNCHD_LOG}")</string>
</dict>
</plist>
PLIST_EOF
  fi
}

probe_healthy() {
  curl -s --max-time 3 "${STATUS_URL}" | grep -q '"status": "running"'
}

case "${ACTION}" in
  print)
    # 零副作用：不建目录、不写文件、不碰 launchd
    render_plist
    exit 0
    ;;

  install)
    mkdir -p "${PLIST_DIR}" || { echo "❌ 无法创建 ${PLIST_DIR}" >&2; exit 1; }
    TMP_PLIST="${PLIST}.tmp.$$"
    render_plist > "${TMP_PLIST}" || { echo "❌ 生成 plist 失败" >&2; rm -f "${TMP_PLIST}"; exit 1; }
    mv "${TMP_PLIST}" "${PLIST}" || { echo "❌ 写入 plist 失败：${PLIST}" >&2; exit 1; }

    if ! plutil -lint "${PLIST}" >/dev/null 2>&1; then
      echo "❌ plist 未通过 plutil 语法校验：${PLIST}" >&2
      exit 1
    fi

    # 幂等装载：先卸旧的（不存在则忽略），再装新的
    launchctl bootout "${DOMAIN}/${LABEL}" >/dev/null 2>&1 || true
    LOADED=0
    if launchctl bootstrap "${DOMAIN}" "${PLIST}" >/dev/null 2>&1; then
      LOADED=1
    else
      # 旧版 macOS 回退通道（bootstrap 在部分系统版本上不可用）
      launchctl unload "${PLIST}" >/dev/null 2>&1 || true
      if launchctl load -w "${PLIST}" >/dev/null 2>&1; then
        LOADED=1
      fi
    fi
    if [ "${LOADED}" -ne 1 ]; then
      echo "❌ launchctl 装载失败：${PLIST}" >&2
      exit 1
    fi

    echo "✅ 已安装并装载开机自启：${PLIST}"
    echo "    Label            : ${LABEL}"
    echo "    模式             : ${MODE}$([ "${MODE}" = "electron" ] && echo "（经 DSH 应用绕开 macOS 文稿保护，零授权）" || echo "（⚠️ 需 /bin/bash 完全磁盘访问权限）")"
    echo "    触发             : 登录即拉起 + 每 5 分钟兜底复查（服务端/看门狗都掉了才介入）"
    echo "    唯一启动口径     : ${ENSURE_SH}（幂等）"
    echo "    解释器（绝对化） : ${PYTHON_BIN}"
    [ "${MODE}" = "electron" ] && echo "    家长进程         : ${DSH_NODE_BIN}"
    echo "    launchd 日志     : ${LAUNCHD_LOG}"

    # 立即生效一次（不等下一次节拍）
    bash "${ENSURE_SH}" >/dev/null 2>&1 || true
    if probe_healthy; then
      echo "🌐 当前已就绪：http://127.0.0.1:${PORT}（健康探针通过）"
    else
      echo "⚠️  服务端暂未就绪，请查看 ${BASE_DIR}/server.log"
    fi
    exit 0
    ;;

  uninstall)
    launchctl bootout "${DOMAIN}/${LABEL}" >/dev/null 2>&1 || true
    launchctl unload "${PLIST}" >/dev/null 2>&1 || true
    rm -f "${PLIST}"
    echo "✅ 已卸载开机自启（Label: ${LABEL}）；已在运行的服务端**不受影响**，如需停止："
    echo "   bash ${SCRIPT_DIR}/stop_server.sh"
    exit 0
    ;;

  status)
    echo "======================================================================"
    echo " 🔎 开机自启状态（Label: ${LABEL} · 模式: ${MODE}）"
    echo "======================================================================"
    if [ -f "${PLIST}" ]; then
      echo "📄 plist 文件    : ${PLIST}"
      if plutil -lint "${PLIST}" >/dev/null 2>&1; then
        echo "   plutil 校验   : ✅ 合法"
      else
        echo "   plutil 校验   : ⛔ 非法"
      fi
    else
      echo "📄 plist 文件    : ⛔ 不存在（尚未安装：bash ${SCRIPT_DIR}/install_autostart.sh install）"
    fi
    if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
      echo "🛡️ launchd 装载  : ✅ 已装载"
      launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep -E "^\s*(state|last exit code|runs) =" | sed 's/^/   /' || true
    else
      echo "🛡️ launchd 装载  : ⛔ 未装载"
    fi
    if probe_healthy; then
      echo "🌐 健康探针      : ✅ 通过（http://127.0.0.1:${PORT}）"
    else
      echo "🌐 健康探针      : ⛔ 未通过"
    fi
    if [ "${MODE}" = "bash" ]; then
      echo "⚠️  提示          : legacy-bash 模式依赖「/bin/bash 完全磁盘访问权限」；"
      echo "                    若 last exit code = 126，即未授权（TCC 拒读文稿目录）。"
    fi
    exit 0
    ;;

  *)
    echo "用法: bash scripts/install_autostart.sh [install|uninstall|status|print] [--legacy-bash|--electron]" >&2
    exit 2
    ;;
esac
