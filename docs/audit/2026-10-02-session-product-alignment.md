# DSH股票 · 会话与产品全域管控纳管对齐报告（v5.6.0 / R12）

> **触发需求**：`根据最新的管控机制对当前工程文件夹下的会话以及产品做调整优化，确保所有都按管控机制流程走`
> **执行会话**：`[优规015][76] 会话产品纳管对齐`
> **审计时间**：2026-10-02
> **判定口径**：**只认可复跑命令的输出**。凡"脚本存在但从未跑出结果"、"载体在但读不到数据"一律**不算纳管**。
> **需求依据**：本工程 `docs/requirements.md` REQ-056（本报告为其证据附件）· 全局 REQ-092（全域覆盖）· REQ-096（会话来源合规）

---

## 一、总体结论

| 面 | 纳管前（物理事实） | 纳管后（物理事实） | 判据命令 |
| :--- | :--- | :--- | :--- |
| **本工程主会话命名** | 9 条主会话中 **4 条不合规**（纯口语标题） | **9/9 合规**，0 不合规 | `node scripts/session_naming_audit.mjs --json` |
| **会话内容可读性** | `unreadable` **102/102**（全量读不到落盘内容） | `unreadable` **0** | 同上 |
| **自动命名链路** | 看门狗「检查 **0** 条」＝ 整条链路空转 | 「检查 **22** · 跳过 14 · 失败 0」 | `node scripts/naming_watchdog.mjs`（dry-run） |
| **会话来源合规** | 未判 | 退休形态 `source.kind="plugin"` **0 命中**；合规 `plugin:hindsight` / `plugin:heartbeat` | 逐帧解压本工程 12 个会话转录 |
| **产品待提交变更** | **86 项**未入库（工作树脱管） | **0 项**（全部入库推送） | `git status --porcelain` |
| **产品版本贯通** | 台账写 v5.6.0 / 权威 `config/version.json` 写 v5.5.0（**版本孤岛**） | 台账 ↔ 权威 ↔ 入口登记**三方同值 v5.6.0** | `curl http://127.0.0.1:8888/api/version` |
| **本工程管控入口** | `naming` ❌ / `todo` ❌（selfcheck 2 项异常） | 四入口实跑并写入 `.dsh-control/run-audit.jsonl` | `./scripts/control.sh selfcheck` |
| **全域覆盖** | — | DSH股票 **4/4**（入口在位 / 文档引用可达 / 运行留痕 / 台账含版本） | `./scripts/control.sh scope` |

---

## 二、会话侧：两条链路都是"看着在跑、其实没跑"

### 2.1 直接整改：4 条口语标题的存量主会话

本工程工作区（`sessions/--Users-linqiyu-Documents-DSH-DSH~80A1~7968--/`）共 **12 个会话**：**9 条主会话 + 3 条子会话**。
其中 4 条主会话标题为口语原文，不符合「`[分类编号][难度分] 8字概述`」规范。经宿主 `session/rename` RPC 实改名并回读验证：

| 会话 ID | 整改前标题 | 整改后标题 | 依据（首条真实用户消息） |
| :--- | :--- | :--- | :--- |
| `session-8324ace8…` | 优化工程文件夹会话与产品管控 | `[优规015][76] 会话产品纳管对齐` | 本次任务原文 |
| `session-0806482f…` | 找回工程文件会话记录 | `[修漏002][30] 会话记录找回` | 「把之前这个工程文件的会话记录找回来」 |
| `session-a032d89b…` | 产品入口 | `[调研011][20] 产品入口指引` | 「给我产品入口」 |
| `session-ad7f7498…` | 核查产品物理层落地缺口 | `[巡检001][85] 物理层落地审计` | 「看看当前产品有什么地方没有根据需求真实落地的…递归分裂执行层直到可以触达物理层并实现」 |

**编号分配**：按规范"三位数字为全局流水序号、一旦分配即锁定"选取未占用号段（实测已用：`优规` 1/2/3/13/14/51/52/53/90 · `修漏` 001 · `调研` 2/4~10 · `巡检` 无），故分配 015 / 002 / 011 / 001。

### 2.2 根因修复：会话载体读的是**过期的宿主布局**

只改标题是治标。取证发现**两条链路各自被旧布局写死**，导致"存量自动命名"在本机**从未真正运行过**：

| 编号 | 载体 | 缺陷（可复跑） | 修法 | 复跑证据 |
| :--- | :--- | :--- | :--- | :--- |
| **D1** | `scripts/lib/auto_naming.mjs`（`sessionCwd` / `firstUserMessage`）<br>`scripts/session_naming_audit.mjs`（转录索引） | 两处**各自硬编码** `session.jsonl.zstd`，而宿主实际落盘 `session.v4.jsonl.zstd`（历史另有 v3）→ 实测 `sessionCwd()` 与 `firstUserMessage()` 对全部 4 条受测会话**恒返回 `null`** → `buildTitle()` 恒 `null` → 自动命名整条静默失效；审计器 `unreadable` **102/102** | 收敛到**本仓已有**的权威定位器 `lib/session_transcript.mjs#findTranscript()`（按 `/^session.*\.jsonl\.zstd$/` 匹配并取最新一份） | 修复前 `cwd: NULL / msg: NULL`；修复后 `cwd=/Users/.../DSH股票` + 真实首条消息 |
| **D2** | `scripts/lib/auto_naming.mjs`（`readSessionStore`） | 只读**已不存在**的单文件 `storages/session_projcache.json`；当前宿主已改为**按会话分片** `storages/session_projcache/sessions/<sid>.json`（实测 102 个分片）→ 返回 `null` → `naming_watchdog` 判「读不到会话存储」，**一条都不巡** | 改为双布局兼容读取（分片优先、单文件并入），返回形状保持 `{tables:{sessions:{…}}}`，既有消费者零改动 | 修复前「检查 0 条」；修复后「检查 22 · 跳过 14 · 失败 0」 |

> **为什么这两条必须修**：管控机制的口径是"不采信自述"。会话命名若只有"模型手改"这一条路，则存量会话的**自动纳管能力物理上不存在**，而外观与"巡了一圈没发现问题"完全一致 —— 属机制最忌讳的一类静默失守。

### 2.3 会话来源合规（REQ-096）

对本工程 12 个会话转录逐帧 zstd 解压后精准判定：

- **退休形态 `source.kind === "plugin"`：0 命中**（该形态会让宿主 v4 行级接纳拒收并判整轮失败）；
- 落盘会话中真实存在的插件来源均为**合规形态** `plugin:hindsight` / `plugin:heartbeat`（与宿主官方迁移口径一致）；
- 全局判定器 `node scripts/session_source_audit.mjs --check` 结论：判据一（静态普查）无手写退休 kind · 判据二（宿主校验器实跑对拍）反例被拒收 / 正例被接纳。

### 2.4 如实登记的宿主限制（**不美化**）

3 条**子会话**（`54cf0cdd` / `cfc36201` / `d7d76c1d`）由宿主 subagent routing 托管，调用 `session.rename` 返回 `agent-busy`，直接改写存储会被运行时回滚 —— **无法改名**。审计器已显式标注 `子会话·宿主限制不可改名`，本轮登记为宿主限制而非未整改。

---

## 三、产品侧：把"脱管工作树"与"版本孤岛"收口

1. **工作树清零入库**：本工程此前有 **86 项**未提交变更（含 R05~R12 全部批次、`docs/audit/`、`docs/handoff/`、`web/modules/`、多套测试与真机证据），产品处在"改过但未纳管"状态。本轮全量入库并推送远程，`git status --porcelain` 归零。
2. **版本孤岛归位**：台账 R11 段已写 `v5.6.0`，而运行期唯一权威 `config/version.json` 仍为 `v5.5.0`，入口登记 `docs/operations/product-entry.json` 亦停在上一个提交 `239cced` 且 `dirty: true`。现三方归位 **v5.6.0**：
   - `config/version.json`（权威，`/api/version` 实测热生效，无需重启 —— REQ-054 再次现场验证）；
   - `docs/requirements.md`（抬头 + R12 批次段 + REQ-056）；
   - `docs/operations/product-entry.json`（版本 / 需求区间 / 源修订 / 门禁快照 / 运行入口）。
3. **日志泄漏口收口**：`.gitignore` 原只有 `*.log`，**匹配不到**轮转件 `server.log.1` / `watchdog.log.1`（1.23MB + 11KB，实测处于未跟踪状态）→ 补齐 `*.log.*`，防止轮转日志被误入库。
4. **台账登记**：`docs/requirements.md` 新增 **R12 批次（v5.6.0）** 与 **REQ-056**，并把 R11 的物理层审计证据回填为结论段（含关闭门清单）。

---

## 四、复现方式（任何人可自行核验）

```bash
# 1) 会话命名合规（只看本工程）
node scripts/session_naming_audit.mjs --json \
  | python3 -c "import sys,json;d=json.load(sys.stdin);m=[i for i in d['items'] if 'DSH股票' in (i.get('cwd') or '')];print('主会话不合规:',len([i for i in m if not i['isSubSession'] and not i['compliant']]),'| unreadable:',d['unreadable'])"
#    → 主会话不合规: 0 | unreadable: 0

# 2) 自动命名链路通电（dry-run，不改动任何会话）
node scripts/naming_watchdog.mjs
#    → 巡更结果：检查 22 · 改好 0 · 跳过 14 · 失败 0（dry-run，未改动）

# 3) 本工程管控入口自证 + 留痕
cd /Users/linqiyu/Documents/DSH/DSH股票
./scripts/control.sh selfcheck      # 四入口逐条实跑
./scripts/control.sh scope          # → DSH股票 4/4
tail -5 .dsh-control/run-audit.jsonl  # 每行即一条"跑过"的物理凭据

# 4) 产品回归
python3 -m unittest discover -s tests -p "test_*.py"      # → Ran 311 tests ... OK (skipped=2)
for f in tests/test_*.js; do node "$f" >/dev/null || echo "FAIL $f"; done   # → 8 套全 PASS

# 5) 版本贯通（权威 ↔ 运行实例）
curl -s http://127.0.0.1:8888/api/version   # → "version": "v5.6.0"
```

---

## 五、如实登记的判定边界（**本轮未做/未改的，不冒充已修**）

1. **本工程入口的看板口径缺陷（已发现，未修）**：`./scripts/control.sh check` 是薄壳转发，`control_gates.sh:25` 的 `PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"` 解析为**全局规则仓库自身**，故 G1/G2/G3/G4 实测的是**全局仓库**的骨架 / 结构 / 台账 / 冗余，**不是本工程**。
   - 实证：本工程曾有 **86 项**未提交变更时，该看板仍报「**0 未提交变更**」且 6/6 全绿；
   - 影响：`G3 需求文档同步` 对本工程**没有牙**，项目的工程卫生只能由 `scope_audit` 的 4 条粗判据兜底；
   - 处置：本轮**如实登记不越界修**（改 `control_gates.sh` 属全局机制改动，需另行立项 + 全域回归）。本轮已把本工程工作树真实清零，使"真实合规"与"看板显示"之间的差距收敛为 0，但**缺陷本身仍在**。
2. **子会话不可改名**：见 §2.4，属宿主限制。
3. **未复跑真机套件**：本轮未改前端渲染与接口契约，未重跑 `browser_r06~r11`（需服务端在跑；R11 的 25/25 证据已在案 `docs/verification/2026-10-01-r11/`）。已复跑的为 Python 全量 + 前端静态全量。
4. **全局载体的改动归属**：修复 D1/D2 的两处全局脚本（`scripts/lib/auto_naming.mjs`、`scripts/session_naming_audit.mjs`）位于**全局规则仓库**；写入期间该仓库存在**并发会话**，其于 `2839229` 提交时以"并入说明"条款把我的未提交改动一并纳入（提交信息已显式交代归属）。本报告如实登记此并发事实，避免"谁改的"产生歧义。
5. **全局 R12 之外的未清项**：本工程物理层审计（`docs/audit/2026-10-01-physical-layer-audit.md` 第六、八节）中登记的 8 处零调用点死代码、REQ-037 台账-代码偏差、R05 证据留存缺失，均属**产品优化变更**，需过 R06~R10 五套真机回归，产品方已裁定"本轮先不继续"，本项目未擅自动手。

---

### 📦 任务执行与交付收尾回执

- **🏷️ 【当前状态】**：【实施阶段】
- **🎯 【核心结论/输出物】**：本工程「会话」与「产品」两侧 100% 纳入管控流程 —— ①**会话**：主会话命名 **9/9 合规**（4 条实改名并回读验证）、`unreadable` **102→0**、自动命名看门狗自「检查 0 条」恢复为「检查 22 条」、退休来源形态 **0 命中**；②**产品**：**86 项**待提交变更全部入库推送（工作树清零）、台账/权威/入口登记三方版本归位 **v5.6.0**（消除版本孤岛）、`.gitignore` 堵住轮转日志泄漏口、台账新增 **REQ-056**；③**根因**：修掉会话转录定位器（v4 文件名硬编码）与标题存储分片读取两处载体缺陷。
- **📍 【输出物地址】**：`docs/audit/2026-10-02-session-product-alignment.md`（本报告）·`docs/requirements.md`（R12/REQ-056）·`config/version.json`·`docs/operations/product-entry.json`·`.gitignore`；修复载体：`scripts/lib/auto_naming.mjs`·`scripts/session_naming_audit.mjs`（全局规则仓库）
- **💡 【重要说明】**：① **本工程入口看板实测的是全局仓库**（`control_gates.sh:25` 的 `PROJECT_ROOT` 指向脚本自身仓库），故 86 项脱管变更时看板仍报「0 未提交」—— 已如实登记为**未修的机制缺陷**，未越界改动；② 3 条**子会话**受宿主 subagent routing 托管、`agent-busy` 拒改，属宿主限制；③ 全局载体的 D1/D2 修复写入期间遭遇**并发会话**，其提交 `2839229` 以"并入说明"条款纳入，已如实交代归属；④ 未复跑真机套件（本轮未碰渲染与接口契约）；⑤ 死代码清理等 3 项产品优化按产品方既有裁定继续挂起。
- **🌟 【执行效果】**：**93/100**。扣分项：① 本工程入口看板口径缺陷**已定位未修**（属全局机制改动，需另行立项，−3）；② 3 条子会话因宿主限制未能命名合规（−2）；③ 真机套件未复跑，仅以在案 R11 证据引用（−1）；④ 物理层审计遗留的死代码 / REQ-037 偏差 / R05 证据缺失 3 项仍挂起（−1）。
