# R02 项目基线 · v4.5.0 · 2026-09-20

当前工程是 Python 标准库 HTTP/API + SQLite + 原生HTML/JS/SVG 的本地股票工具，并有CLI、采集器、指标与报告引擎。没有构建打包步骤。主要模块：`stock_web_server.py` 接口和服务，`stock_db.py` 存储，`verified_*` 来源与缓存，`chanlun_analysis.py` 五类形态，`web/` 页面。

直接前版 v4.4.0；Git基线 `a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565`，本次结果是未提交工作区。原先的增减持联合筛选改动及 `docs/knowledge/` 并行文档保留。没有远端提交或生产发布。

## 恢复资产

开工前源码与数据库已持久保存在 `data/backups/r02-v4.4.0/`（本地忽略目录），原始归档也保留于 `/tmp/dsh-r02/before/`；其清单与散列另存[before-manifest.json](before-manifest.json)。可运行回退副本及启动命令见[回退记录](rollback.json)。回退使用独立代码目录和数据库，切勿直接覆盖当前工作区；保留新可信缓存。

v4.5.0 实现源码和SQLite一致性副本已保存到 `data/backups/r02-v4.5.0/`，见[本版恢复清单](current-snapshot.json)。

当前源码和数据库快照的散列见[本版源码指纹](../../verification/2026-09-20-r02/source-fingerprints.json)。数据库会随合法采集变化，散列仅代表交付时点。

## 后续修改基准

1. 先读唯一[需求台账](../../requirements.md)，复用REQ/UI编号。
2. 真实输入和算法规则分开：股东“姓名数”不等于“账户户数”；笔背离不等于完整趋势背驰；当前快照不等于历史区间。
3. 缺数据保留null/状态；测试样例只在tests和临时数据库，不落生产库。
4. 用58项Python回归、两组JavaScript验证及实际UI读回检查变更。
5. 来源、接口和前端契约保持一致，版本改变后更新产品入口与受影响截图。

本版[技术验收](../../verification/2026-09-20-r02/README.md)、[来源覆盖](data-sources.md)、[问题复盘](../../problem-log/BUG-003-synthetic-data.md)。未覆盖项为来源尚缺的字段和生产/真机验收，不能从本地测试推断已完成。
