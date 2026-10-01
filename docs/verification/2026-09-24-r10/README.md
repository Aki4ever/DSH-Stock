# R10 批次验证证据（v5.5.0 · 2026-09-24）

> 批次需求：**REQ-052**（本地数据库非破坏性归档与体检）、**REQ-053**（前端模块化拆分第一步）、**REQ-054**（版本单一权威运行期即时生效 / BUG-006 修复）
> 交付版本：`v5.5.0`（`config/version.json` 为唯一版本权威，且**运行期即时生效**）
> 验证对象：本机真实运行实例 `http://127.0.0.1:8888/` + 真实产品库 `data/stock_database.db`（未做任何写入/迁移）

## 1. 门禁结果

| 门禁 | 命令 | 结果 |
| :--- | :--- | :--- |
| Python 单元/接口测试 | `DSH_DISABLE_BACKGROUND=1 python3 -m unittest discover -s tests -p "test_*.py"` | **266 项 PASS**（本批新增 `test_r10_db_maintenance.py` 14 项、`test_r10_version_authority.py` 6 项） |
| 前端静态回归（7 套） | 6 套既有 + `test_r10_module_split.js` | **7 / 7 PASS**（新增模块契约套件：迁出唯一性 / 纯函数约束 / 脚本顺序 / 行为黄金值） |
| R10 真机验收 | `DSH_CDP_PORT=9490 node tests/browser_r10_verify.js` | **15 / 15 PASS**，控制台错误 0，截图 `01-util-module-live-page.png` |
| R09 真机回归 | `DSH_CDP_PORT=9495 node tests/browser_r09_verify.js` | **28 / 28 PASS**，页面标题实测 `【v5.5.0】` |
| R08 真机回归 | `DSH_CDP_PORT=9494 node tests/browser_r08_verify.js` | **40 / 40 PASS** |
| R07 真机回归 | `DSH_CDP_PORT=9492 node tests/browser_r07_verify.js` | **44 / 44 PASS** |
| R06 真机回归 | `DSH_CDP_PORT=9491 node tests/browser_r06_verify.js` | **39 / 39 PASS** |
| 数据安全 | —— | **零写入 / 零迁移 / 零重建**（归档为只读快照） |

## 2. 三项需求的关键证据

### REQ-052 数据库非破坏性归档（真实产品库实测）
- 源库体检：`60,362,752 B`（14737 页 × 4096B，空闲页 561）· 13 张表 · 28,575 行 · `integrity_check=ok` · `quick_check=ok` · `journal_mode=wal`。
- 归档结果：完整副本 **57.57 MB**（`integrity_check=ok`，**逐表行数与源库一致**）+ 紧凑副本 **54.92 MB**（`VACUUM INTO`，省 2.65 MB）。
- 安全边界：源库以 `file:...?mode=ro` 打开（单测断言写操作必被拒绝）；归档前后源库 SHA-256 一致；归档期间与之后 `/api/status` 均为 running。
- 可追溯：每个归档生成同名 `.manifest.json`（源库哈希/大小/逐表行数/完整性/说明/保留策略）。
- 默认只增不删；`--keep N` 才清理，且只清理本工具命名规则内的文件（含其 manifest 与紧凑副本同组同命运）。

### REQ-053 前端模块化拆分第一步
- `web/app.js` **8756 → 8612 行**；新增 `web/modules/util.js`（167 行，10 个纯函数）。
- 真机实测：`/web/modules/util.js` HTTP 200 + `application/javascript`；脚本顺序 `modules/util.js?v=5.5.0 → app.js?v=5.5.0`；10 个函数在页面窗口全部可用且可真实调用（`estimateSvgTextWidth('副图：成交额',10)=61.95`、`layoutSubplotHeader rows=1`）。
- 拆分后真实个股日K副图表头照常渲染：`副图：成交额（含估算：均价×成交量）` · 统计项 5 个；控制台零错误。
- 静态契约：迁出函数在合并源码中恰好声明 1 次；util.js 无 DOM/状态访问、顶层无副作用语句；测试装载统一走 `tests/load_web_sources.js`（与页面同构）。

### REQ-054 版本权威运行期即时生效（BUG-006）
- 修复前真机复现：权威文件 `v5.5.0` / 接口 `v5.4.1` / 页面标题 `【v5.4.1】`（详见 `docs/problem-log/BUG-006-*.md`）。
- 修复后：重启加载新代码 → `/api/version` = `v5.5.0`；**就地改写 `config/version.json` 描述、进程不动**，0.3 秒后接口即返回新描述（`ops-evidence.txt` 原样记录）；`/api/status.version` 同步；R09/R08 真机页面标题实测 `【v5.5.0】`。

## 3. 本目录文件

| 文件 | 说明 |
| :--- | :--- |
| `browser-report.json` | R10 真机 15 项逐条结果 |
| `01-util-module-live-page.png` | 拆分后真实页面（含个股日K副图表头）截图 |
| `live-entry.json` | Web 入口原样回读（v5.5.0 / 回环绑定 / 页面标题） |
| `ops-evidence.txt` | 归档 CLI 原样输出、归档目录清单、版本热生效实测、脚本顺序 |
| `source-fingerprints.json` | 本批源指纹（`config/`+`scripts/`+`web/` 共 63 个文件 SHA-256 + git revision） |

## 4. 遗留（如实登记）

- 拆分**只完成第一步**：`web/app.js` 仍 8612 行、`scripts/stock_web_server.py` 1826 行；后续每切一块都必须过 R06~R10 五套真机回归。
- 产品库不做 VACUUM/重建（红线）；紧凑副本仅供离线使用，需要滚动保留请显式 `--keep N`。
- 鉴权仍未实现（局域网暴露风险由 REQ-049 的回环绑定收敛）。
