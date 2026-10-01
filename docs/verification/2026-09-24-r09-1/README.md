# R09.1 补丁批次验证证据（v5.4.1 · 2026-09-24）

> 本批是承接 R09（v5.4.0）的**收口补丁**：把 R09 台账「遗留说明」中逐条登记的四项一次性实施完毕。
> 本目录只登记本批**新增**证据；功能截图与报告复用各批次原目录（见「证据落点」），不重复造图。

## 1. 门禁结果（本批全量重跑）

| 门禁 | 命令 | 结果 |
| :--- | :--- | :--- |
| Python 单元/接口测试 | `DSH_DISABLE_BACKGROUND=1 python3 -m unittest discover -s tests -p "test_*.py"` | **246 项 PASS**（本批新增 `test_r09_1_ops_defaults.py` 18 项） |
| 前端静态回归（6 套） | `node tests/test_chart_integrity.js` 等 6 套 | **6 / 6 PASS**（`test_r09_subplot_header.js` 增补 REQ-037 修订断言） |
| R09 真机验收 | `DSH_CDP_PORT=9453 node tests/browser_r09_verify.js` | **28 / 28 PASS**，控制台错误 0 |
| R08 真机回归 | `DSH_CDP_PORT=9452 node tests/browser_r08_verify.js` | **40 / 40 PASS**，控制台错误 0 |
| R07 真机回归 | `DSH_CDP_PORT=9441 node tests/browser_r07_verify.js` | **44 / 44 PASS** |
| R06 真机回归 | `DSH_CDP_PORT=9440 node tests/browser_r06_verify.js` | **39 / 39 PASS** |
| 服务端健康 | `curl -s http://127.0.0.1:8888/api/status` | running · **v5.4.1** · 监听 **127.0.0.1:8888**（仅回环） |
| 数据安全 | —— | **零数据库写入 / 零迁移 / 零重建** |

## 2. 四项实现的真机／真实文件证据

| 需求 | 证据 | 判定依据 |
| :--- | :--- | :--- |
| REQ-037 修订（首屏副图档位统一） | `ops-evidence.txt`、R07 报告 | 首屏左（当日分时）＝`副图：成交额`、右（K线）＝`副图：成交额`，与唯一「幅图联动」控件高亮一致；手动切换后两图同步且不被颗粒度切换改写（R07 断言 + `test_r09_subplot_header.js` 静态断言） |
| REQ-049（默认仅回环） | `live-entry.json` · `ops-evidence.txt` | `lsof` → `TCP 127.0.0.1:8888 (LISTEN)`（此前 `*:8888`）；`resolve_bind_host` 三级优先级实测：默认 `127.0.0.1`、`--host 0.0.0.0`、`DSH_STOCK_HOST=0.0.0.0` 均按预期；全部真机脚本走回环不受影响 |
| REQ-050（日志轮转） | `ops-evidence.txt` | 以 `DSH_STOCK_LOG_MAX_KB=1` 真实触发：`🗂️ 日志已轮转：server.log → server.log.1（原大小 2052KB ≥ 1KB）`，`watchdog.log` 同步轮转；历史份数上限 3 |
| REQ-051（R05 快照归档） | `tests/` 目录 + 归档件 | `tests/browser_r05_verify.js` 不存在；归档件 `docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js` 保留「历史快照说明」头部（`test_r09_1_ops_defaults.py` 断言） |

## 3. 证据落点

| 内容 | 位置 |
| :--- | :--- |
| R06 报告与截图（本批重跑） | `docs/verification/2026-09-23-r06/` |
| R07 报告与截图（本批重跑，含首屏新口径截图） | `docs/verification/2026-09-23-r07/` |
| R08 报告与截图（本批重跑） | `docs/verification/2026-09-23-r08/` |
| R09 报告与截图（本批重跑） | `docs/verification/2026-09-24-r09/` |
| Web 入口原样回读 | 本目录 `live-entry.json` |
| CLI 入口原样输出 | 本目录 `cli-status.txt` |
| 运维加固实测（回环绑定 + 日志轮转） | 本目录 `ops-evidence.txt` |
| 源指纹（config/ + scripts/ + web/ 共 61 个文件） | 本目录 `source-fingerprints.json` |

## 4. 本批发现并如实登记的口径观察项（未擅自改产品）

**当日分时「成交额」副图表头在存在缺量额分时点时降级为一句兜底说明**：收盘后 15:00 快照行的 `volume=0 / amount_yi=null`（仅 `cumulative_amount_yi`），使成交额口径的「完整性」判据不成立，表头不再输出 5 项统计概要，而显示 `当前来源未提供完整量额`（**不以部分数据拼总和**，符合红线）。

- 现状：**诚实优先**，不构成错误数据；R09 真机断言已按「两种合法口径」双分支接受（5 项统计 或 该兜底说明），并强制要求标题唯一、零重叠、不越界。
- 可选一行级改良（**未实施，待产品方决定**）：把 `volume === 0 && amount_yi == null` 的收盘快照行视作「无成交」而不计入完整性判据；成交量口径目前对同一行的处理是计入（最小值为 0 手），两者取舍属产品语义。
