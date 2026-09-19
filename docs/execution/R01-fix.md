# R01 行情股东修复：实施与回归记录

目标：修复不同股票K线数据污染/串图风险和历史截断，增加真实增减持股东列及AND筛选。对应REQ-008/009 v1；前版v4.3.0，本版v4.4.0。本轮用户“实施”授权本地可逆实现与验证，无Git提交/推送。

| 稳定节点 | 工作 | 证据 |
|---|---|---|
| R01:FIX01 | 两次最小复现、代码/缓存/源接口定位 | [复现](../verification/2026-09-19-fix/reproduction.json) |
| R01:FIX02 | 可信日线缓存、完整分页、刷新与隔离、竞态防护 | [原入口抽验](../verification/2026-09-19-fix/live-entry.json) |
| R01:FIX03 | 实际增减持来源、名单与筛选、相同统计口径 | [联合筛选](../verification/2026-09-19-fix/http-filters.json) |
| R01:FIX04 | 隔离测试、浏览器核验、原入口升级及回退 | [43项测试](../verification/2026-09-19-fix/full-suite.log)、[页面验证](../verification/2026-09-19-fix/ui-verification.json) |

执行前提：Python 3.9+、Node（前端单测）、本地股票底册；公网只请求腾讯证券与东方财富公开数据。首查证券获取来源全部历史，以后5分钟可信缓存；不批量声称已抓完全部4601只股票。股东行为首次获取近一年全市场披露记录，以后缓存1小时；明示公告窗、来源和失败状态。两个维度都不补造缺失值。

验证命令：

```sh
python3 -m unittest tests.test_verified_market_data -v
node tests/test_detail_requests.js
node --check web/app.js
python3 scripts/dsh_stock_cli.py history sh600519 --json
python3 scripts/dsh_stock_cli.py holder-actions sh600519 --days 365 --json
```

完整原有测试在 `/tmp/dsh-fix-r01/regression` 副本执行，避免覆盖原reports。网络异常/重复分页/超5000条/身份错误/同时请求/股东双向/零记录/未获取/AND筛选/先筛后分页均覆盖。浏览器验证上市历史、不同股票图形、60天窗口、空日期范围、缺失成交额、近90天、双向股东行为、版本及控制台。

产品入口：http://127.0.0.1:8888/；旧版回退：http://127.0.0.1:8890/。旧服务PID6427经命令行身份核验后发送SIGTERM，只重启本地项目服务；新PID见 [激活回执](../verification/2026-09-19-fix/activation.json)。没有使用按端口强杀脚本。

恢复：原文件及SQLite一致性副本位于 `/tmp/dsh-fix-r01/before`，独立旧版服务继续可访问。新可信缓存使用新表，旧日线表保留。若要恢复源码，先对照原文件指纹和最新用户修改，不能直接覆盖全部工作区。机器重启或临时目录清理后，临时回退服务需重新启动，不承诺长期托管。

已知边界：来源完整仅代表分页读取至空页，不能证明交易所逐日历史绝无遗漏；首次请求依赖外部来源，失败会标记partial/unavailable或stale。默认不复权；来源未给成交额则明确未提供。股票底册缺失的证券不在列表中，本轮未扩展市场范围。其他旧股东派生指标、财报等基线问题未在本轮修复。

治理与用量：原生Goal未请求，未创建；本轮阶段通过[只读实时面板](../verification/2026-09-19-fix/progress.html)显示并已实际浏览器读回。旧基线的原生预览unknown保留，未重复派发。Token精确计量unknown（无本执行原生计量）；最终墙钟时长记录于交付回执。唯一需求Owner manage-requirements；辅助使用task-preflight、confirm-before-coding、manage-problem-log、github、cli-creator、select-mcp-tool、computer-use-coordinator、sync-requirements-ui-index、deliver-latest-product-entry和track-task-progress。

补充：离线UI总览的file://自动打开被浏览器安全策略拦截，未绕过；其交互验收unknown，不影响已验证的实际产品页面。
