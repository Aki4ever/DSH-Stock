# DSH股票 · 项目级管控约束

> 本文件在本工程会话中被自动注入。
> 遵循全局规则权威法典，本工程 100% 纳入 DSH 全域管控机制与底层物理锁管辖。

---


<!-- DSH-CONTROL-SCOPE:BEGIN（由 scripts/backfill_scope.mjs 生成，勿手改本段） -->
## 〇、管控机制接入（REQ-092 · 全域同权，存量与新增一律生效）

> 本段由全局规则仓库的 `scripts/backfill_scope.mjs` 生成；**引用均为真实存在的路径**，
> 判定器 `node /Users/linqiyu/Documents/DSH/全局规则/scripts/scope_audit.mjs --check` 会逐条验证其可达性。

本工程受 **DSH 全域管控机制** 与 **底层物理锁 Agent (Physical Lock Agent)** 约束，与主控仓库同权。
开工第一动作与每次改动前的必跑项，统一走本工程入口 `./scripts/control.sh`（薄壳，转发全局规则，不复制判定逻辑）：

| 动作 | 本工程入口命令 | 全局规则权威载体（绝对路径，真实存在） |
| :--- | :--- | :--- |
| 首动改名（S05） | `./scripts/control.sh naming` | `/Users/linqiyu/Documents/DSH/全局规则/scripts/name_me.sh` |
| 累积门禁 G0~G4 | `./scripts/control.sh check` | `/Users/linqiyu/Documents/DSH/全局规则/scripts/control_gates.sh` |
| 底层物理锁阶梯 | `./scripts/control.sh lock` | `/Users/linqiyu/Documents/DSH/全局规则/scripts/physical_lock.sh` |
| S07 待办常显 | `./scripts/control.sh todo` | `/Users/linqiyu/Documents/DSH/全局规则/scripts/todo_gate.sh` |
| 需求版本贯通 | `./scripts/control.sh version` | `/Users/linqiyu/Documents/DSH/全局规则/scripts/req_version_audit.mjs` |
| 全域覆盖审计 | `./scripts/control.sh scope` | `/Users/linqiyu/Documents/DSH/全局规则/scripts/scope_audit.mjs` |
| 四入口自证 | `./scripts/control.sh selfcheck` | —（本工程内置，逐条实跑并写留痕） |

- **运行留痕**：每次调用都会追加一行到本工程 `.dsh-control/run-audit.jsonl`；
  "本工程到底跑没跑过管控"以该文件与会话转录为唯一依据，**不认自述**。
- **改名规范**：三段式 `[分类编号][难度分] 8字概述`，规范唯一权威源为
  `/Users/linqiyu/Documents/DSH/全局规则/knowledge/common/task_naming_spec.md`；本工程需求台账 `docs/requirements.md` 记录实施版本与需求版本。
<!-- DSH-CONTROL-SCOPE:END -->
## 一、开工前置：管控机制与物理锁强制执行

本工程受 **DSH 全局管控机制** 与 **底层物理锁 Agent (Physical Lock Agent)** 约束。
物理锁看守单向严格工序链：**必须完成上一步才可以执行下一步**，任何跳步工具调用将被底层物理拦截拒止。

任何改动型动作之前，必须执行：
1. **首动改名**：第一步调用全局改名工具锁定会话标题（三段式「[分类编号][难度分] 8字概述」）；
2. **查需求台账**：查阅 `docs/requirements.md` 确认需求依据与当前版本；
3. **查安全红线**：禁止越权删除与越界破坏。

---

## 二、文末固定五联装视觉强化交付收尾铁律

任务完成或输出汇报时，输出的最末尾处必须且只能包含以下 5 项固定总结结构（带大号图标与加粗）：

```markdown
---

### 📦 任务执行与交付收尾回执

- **🏷️ 【当前状态】**：明确标注【规划阶段】还是【实施阶段】
- **🎯 【核心结论/输出物】**：有输出物就给具体输出物说明，没有输出物就给核心结论
- **📍 【输出物地址】**：如果有输出物就要给物理文件路径（行内代码格式），没有输出物填「无」
- **💡 【重要说明】**：对执行过程中遇到的问题、踩坑、潜伏风险或连带产生的非预期/连带改动进行透明显式说明
- **🌟 【执行效果】**：必须给出 0~100 分量化审计打分及扣分项，方便审计和回溯总结
```

---

## 三、极简高信噪比原则
与任务不相关的少说，没有问到的不要说，只有很相关并且比较重要的才说，坚决剔除无关冗余客套。
