# 界面索引（本轮受影响范围）

当前需求REQ-008/009 v1；产品v4.4.0；2026-09-19。本索引仅记录本轮变更的两张页面，其他页面未重新截图，不作为全项目UI已验收证明。实现状态：本地已验收。源码基线f8b53aa工作区修改，精确散列见 [源码指纹](../verification/2026-09-19-fix/source-fingerprints.json)。

| ID | 名称与入口 | 需求 | 本轮能力/关系 | 验证截图 |
|---|---|---|---|---|
| UI-STOCK-LIST | 股票列表，8888首页 | REQ-009 v1 | 增持/减持股东姓名列、披露期、来源、AND筛选；点击详情进入UI-STOCK-DETAIL | [真实页面](../verification/2026-09-19-fix/screenshots/holder-columns.jpg) |
| UI-STOCK-DETAIL | 股票详情，从列表进入 | REQ-008/009 v1 | 证券身份、全历史、窗口与刷新、股东行为；返回UI-STOCK-LIST | [真实页面](../verification/2026-09-19-fix/screenshots/maotai-history.jpg) |

本轮均为首次建立截图记录；截取最终源码运行页面，无缺失截图冒充最新结果。页面、源码、viewport和截图散列绑定于 [截图清单](../verification/2026-09-19-fix/screenshots.json)。[只读页面总览](../ui-overview/index.html)从这两条记录派生，不是产品入口。

离线总览自动打开验收：浏览器URL安全策略拒绝file://；未换路径绕过，交互验证unknown。产品8888页面和上表截图已经实际读回。
