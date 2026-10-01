#!/usr/bin/env bash
# ==============================================================================
# 管控机制调用入口（薄壳）· Thin control-call shell
# ==============================================================================
# 为什么需要它（REQ-092 / R1-b 实测根因）：
#   实测扫描 16 个外部工程会话转录，`name_me` / `control_gates` / `physical_lock` / `todo_gate`
#   命中数**全部为 0** —— 这些工程的文件被改了，却一次都没跑过管控机制。
#   根因不是"没有规则"，而是**没有可调用的入口**：全局规则的脚本在另一个仓库里，
#   本工程会话根本敲不到，于是规则只剩一句文字。
#
#   本薄壳只做三件事，刻意不复制任何判定逻辑（判定逻辑的唯一权威源仍是全局规则仓库）：
#     ① 转发：把动作转交全局规则对应脚本，并把真实退出码原样带回；
#     ② 留痕：把"哪个工程、跑的哪条、退出码几"追加进本工程 `.dsh-control/run-audit.jsonl`，
#       让"这个工程到底跑没跑过管控"变成可复算的物理事实（不认自述）；
#     ③ 自证：`selfcheck` 逐条实跑四个机制入口并汇总退出码，供全域覆盖审计采信。
#
# 用法（在本工程根目录）：
#   ./scripts/control.sh check        # 累积门禁 G0~G4 看板
#   ./scripts/control.sh lock         # 底层物理锁阶梯状态
#   ./scripts/control.sh todo         # S07 待办常显判定
#   ./scripts/control.sh naming       # 会话命名合规判定
#   ./scripts/control.sh version      # 需求版本贯通 + 受管文档版本归位（只读判定）
#   ./scripts/control.sh scope        # 全域覆盖审计（只读判定）
#   ./scripts/control.sh render       # 生成信息图 / 渲染类命令（透传）
#   ./scripts/control.sh selfcheck    # 四机制入口逐条实跑并汇总（本脚本自身可证伪）
#   ./scripts/control.sh path         # 打印全局规则根目录
#
# 退出码：转发动作的真实退出码；selfcheck 为失败项数（0 = 全绿）；2 = 用法错误
# ==============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 全局规则根目录：优先环境变量（便于迁移/测试），否则回落到本机已实测的绝对路径。
GLOBAL_RULES="${DSH_GLOBAL_RULES:-/Users/linqiyu/Documents/DSH/全局规则}"
if [ ! -d "$GLOBAL_RULES/scripts" ]; then
  echo "❌ 找不到全局规则仓库：$GLOBAL_RULES（可用 DSH_GLOBAL_RULES=<路径> 覆盖）" >&2
  exit 2
fi

ACTION="${1:-check}"
LOG_DIR="$PROJECT_ROOT/.dsh-control"
LOG_FILE="$LOG_DIR/run-audit.jsonl"

log_run() {
  # 留痕一律成功失败都写：判定失败的记录同样是证据（"跑过但没过" ≠ "没跑过"）
  mkdir -p "$LOG_DIR" 2>/dev/null || return 0
  printf '{"unit":"control-shell","project":"%s","action":"%s","exit":%s,"at":"%s","cwd":"%s"}\n' \
    "$PROJECT_ROOT" "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PWD" >>"$LOG_FILE" 2>/dev/null || true
}

run() {
  local name="$1"; shift
  "$@" ; local code=$?
  log_run "$name" "$code"
  return $code
}

case "$ACTION" in
  check)
    run check bash "$GLOBAL_RULES/scripts/control_gates.sh" check
    ;;
  lock)
    run lock bash "$GLOBAL_RULES/scripts/physical_lock.sh" status
    ;;
  todo)
    run todo bash "$GLOBAL_RULES/scripts/todo_gate.sh" check
    ;;
  naming)
    # 三态退出码：0 合规 / 1 不合规 / 3 无法判定（无法判定不得折算为通过）
    run naming bash "$GLOBAL_RULES/scripts/check_task_naming.sh" --exit
    ;;
  version)
    run version-version node "$GLOBAL_RULES/scripts/req_version_audit.mjs" --check
    ;;
  scope)
    run scope-scope node "$GLOBAL_RULES/scripts/scope_audit.mjs" --check
    ;;
  render)
    run render bash "$GLOBAL_RULES/scripts/control_gates.sh" badge
    ;;
  selfcheck)
    failed=0
    for step in naming lock todo; do
      case "$step" in
        naming) bash "$GLOBAL_RULES/scripts/check_task_naming.sh" --exit >/dev/null 2>&1 ;;
        lock) bash "$GLOBAL_RULES/scripts/physical_lock.sh" status >/dev/null 2>&1 ;;
        todo) bash "$GLOBAL_RULES/scripts/todo_gate.sh" check >/dev/null 2>&1 ;;
      esac
      code=$?
      [ "$code" -eq 0 ] || failed=$((failed + 1))
      printf '  %s %s（退出码 %s）\n' "$([ "$code" -eq 0 ] && echo ✅ || echo ❌)" "$step" "$code"
      log_run "$step" "$code"
    done
    echo "📦 工程：$PROJECT_ROOT"
    echo "🧭 全局规则：$GLOBAL_RULES"
    echo "$([ "$failed" -eq 0 ] && echo '🎉 机制入口全绿' || echo "❌ 入口异常 $failed 项")"
    exit "$failed"
    ;;
  path)
    echo "$GLOBAL_RULES"
    ;;
  *)
    echo "用法：$0 {check|lock|todo|naming|version|scope|render|selfcheck|path}" >&2
    exit 2
    ;;
esac
