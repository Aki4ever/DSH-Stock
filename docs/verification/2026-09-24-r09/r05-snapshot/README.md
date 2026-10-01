# R05 历史快照脚本的现行运行记录（2026-09-24）

> 目的：把「R05 真机脚本已过时」这一判断从**口头声明**变成**可复核的运行记录**，供台账（`docs/requirements.md` → R05 台账）引用。
> 结论：**该脚本已不能作为现行回归判据**，其个股断言针对的是**已被 REQ-034/035 取代**的旧单面板 UI。

## 运行方式与原始输出

```sh
bash scripts/ensure_server.sh
DSH_CDP_PORT=9408 DSH_SHOT_DIR=docs/verification/2026-09-24-r09/r05-snapshot \
  node docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js
```

| 项 | 实测结果 |
| :--- | :--- |
| 通过 | **9 项**（指数页与接口层断言等现行仍成立的部分） |
| 失败 | **11 项**，全部集中在**已被取代的旧个股口径**：`REQ-027 个股周期 Tab`（Tab 集合已重构为双维度双图）、`REQ-029 kline20/60/120/180/all 默认根数`（视窗模型已改为下限 30 根 / 上限＝全部可用根数） |
| 终止 | 脚本在后续步骤抛 `TypeError: Cannot read properties of null (reading 'dispatchEvent')` 并中断 —— 它操作的是旧单面板时代的 DOM 元素（如个股周期 Tab 容器），该元素在当前双面板设计下已不存在 |
| 产物 | 仅 `01-preset-20-60-all.png`（崩溃前截图） |

**这不是产品回归**：脚本文件头自 R06 起即声明其为 R05 历史快照、个股断言建立在已被取代的旧口径上。现行回归判据为：

```sh
node tests/browser_r06_verify.js   # 39/39 PASS（REQ-034/035/036）
node tests/browser_r07_verify.js   # 44/44 PASS（REQ-037~040）
node tests/browser_r08_verify.js   # 40/40 PASS（REQ-041~045）
node tests/browser_r09_verify.js   # 28/28 PASS（REQ-046~048）
```

## 处置建议（未擅自实施）

`docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js` 的**指数页与接口层**断言仍具参考价值（本轮 9 项通过即来自此）。若要彻底消除误读风险，建议二选一（需产品方确认，本批未动）：

1. ~~移入 `docs/verification/2026-09-20-r05/` 作为归档证据、从 `tests/` 移出~~ **已于 2026-09-24 执行**（现路径 `docs/verification/2026-09-20-r05/browser_r05_verify.snapshot.js`，`tests/` 下已不存在该文件，不会再被误当回归门禁）；
2. 若日后仍需要 R05 的指数页回归，建议按 REQ-034/035 现行口径**重写**一份独立脚本（未实施）。
