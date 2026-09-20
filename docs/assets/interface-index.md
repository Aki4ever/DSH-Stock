# 界面索引 · v4.5.0

直接前版 v4.4.0；2026-09-20；Git a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565，未提交工作区。以下7个受影响页面均已在8888实际打开核验并截图，属于本地技术验收，用户验收待确认。完整[来源与限制](../baselines/2026-09-20/data-sources.md)、[技术证据](../verification/2026-09-20-r02/README.md)、[源码指纹](../verification/2026-09-20-r02/source-fingerprints.json)。

| ID | 名称/入口 | 需求 | 能力及关系 | 实际截图 |
|---|---|---|---|---|
| UI-STOCK-LIST | 股票列表；首页 | REQ-009/012 | 股东行为选择同时增减持，171个匹配，增持和减持姓名列；导航至UI-STOCK-DETAIL | [更新截图](003-r02/stock-list.jpg) |
| UI-STOCK-DETAIL | 股票详情与缠论；股票列表→详情 | REQ-008/009/010/012 | 茅台120根显示窗口，完整历史计算五类图层，图例独立开关；导航至UI-STOCK-LIST | [更新截图](003-r02/chanlun.jpg) |
| UI-SHAREHOLDERS | 股东研究；顶部股东研究 | REQ-011/012 | 个人分类、19866个姓名、398页，概览范围独立于当前页；导航至UI-STOCK-DETAIL | [新增截图](003-r02/shareholders.jpg) |
| UI-DASHBOARD | 行情快照仪表盘；顶部仪表盘 | REQ-012 | 实际行情快照与缺失维度；跨日区间显示未覆盖；导航至UI-STOCK-LIST | [新增截图](003-r02/dashboard.jpg) |
| UI-MACRO | 宏观环境；顶部宏观环境 | REQ-012 | 新闻/评分无可核验数据时明确未获取；导航至UI-STOCK-LIST | [新增截图](003-r02/macro.jpg) |
| UI-INDEX | 指数行情；顶部指数→上证指数详情 | REQ-012 | 上证指数60天日K；成交额缺失不估造，SVG无NaN；导航至UI-STOCK-LIST | [新增截图](003-r02/index.jpg) |
| UI-DATA-CENTER | 数据中心；顶部数据中心 | REQ-012 | 100/100真实行情采集审计；旧日志数据未核验；批次仅用于追溯；导航至UI-STOCK-LIST | [新增截图](003-r02/data-center.jpg) |

共享状态为已完成，验收证据见链接；不将自动技术验收冒充用户接受。全部新截图来自当前v4.5.0实际页面，viewport1280×720；没有复用过期图片。新旧指纹、时间、状态和源码关系见下面规范数据（总览从此派生）。

[交互总览](../ui-overview/index.html)是派生文档入口，产品入口为8888。图片、节点、关系、链接及静态结构已核验；Codex原生文件预览只返回queued，离线总览的原生交互读回为unknown，不作为已验收原生页面。

```json
[
  {
    "id": "UI-STOCK-LIST",
    "name": "股票列表",
    "module": "股票列表",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-009/012",
    "entry": "首页",
    "parent": null,
    "relations": [
      "UI-STOCK-DETAIL"
    ],
    "capability": "股东行为选择同时增减持，171个匹配，增持和减持姓名列",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/stock-list.jpg",
    "screenshot_sha256": "e0f32e94689557f39e9825229a35c64f1fe81a5def783469889889c110d2fdfa",
    "captured_at": "2026-09-20T06:49:59.022739+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "075ff450a2c0dc34e3a0f5f4e15bb5d1cc222553ffbb184f6dc30cc5301100f6",
    "previous_fingerprint": "3a6ec6e079a3889b1e093452acebbba453bb3dd32cc0ae45c3d3fb2e8b5f18de",
    "decision": "更新截图"
  },
  {
    "id": "UI-STOCK-DETAIL",
    "name": "股票详情与缠论",
    "module": "股票详情与缠论",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-008/009/010/012",
    "entry": "股票列表→详情",
    "parent": null,
    "relations": [
      "UI-STOCK-LIST"
    ],
    "capability": "茅台120根显示窗口，完整历史计算五类图层，图例独立开关",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/chanlun.jpg",
    "screenshot_sha256": "2fdd315dcd98bf8814c233ca384f96163af890fcc94119260bbe39d3940ac8f3",
    "captured_at": "2026-09-20T06:50:03.070975+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "a7a0cac359157b2dad855438ebb1a19bce30a590edeeaadc8102dc30d80678fa",
    "previous_fingerprint": "f020218f6b62eef239d7781952d244ff92ba755a075d764358be6f39dd41bc58",
    "decision": "更新截图"
  },
  {
    "id": "UI-SHAREHOLDERS",
    "name": "股东研究",
    "module": "股东研究",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-011/012",
    "entry": "顶部股东研究",
    "parent": null,
    "relations": [
      "UI-STOCK-DETAIL"
    ],
    "capability": "个人分类、19866个姓名、398页，概览范围独立于当前页",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/shareholders.jpg",
    "screenshot_sha256": "25a9f7125d5b226f7f148b170869aa7f461dc6eb2281b76ea462cfec25f631fd",
    "captured_at": "2026-09-20T06:49:39.394692+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "ad139487bc40743a5f2d790c462d14a052afd92e2bce136640f77c83b3e362d0",
    "previous_fingerprint": null,
    "decision": "新增截图"
  },
  {
    "id": "UI-DASHBOARD",
    "name": "行情快照仪表盘",
    "module": "行情快照仪表盘",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-012",
    "entry": "顶部仪表盘",
    "parent": null,
    "relations": [
      "UI-STOCK-LIST"
    ],
    "capability": "实际行情快照与缺失维度；跨日区间显示未覆盖",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/dashboard.jpg",
    "screenshot_sha256": "5aa983aa7e1e2dc6072e6bdf07bef12995127543bba89e031011de3d1c2f3e95",
    "captured_at": "2026-09-20T06:49:08.317565+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "89a1716c624b4ca17f49869c0120faab6b6d7c348a84bb20119110da7b3ac3be",
    "previous_fingerprint": null,
    "decision": "新增截图"
  },
  {
    "id": "UI-MACRO",
    "name": "宏观环境",
    "module": "宏观环境",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-012",
    "entry": "顶部宏观环境",
    "parent": null,
    "relations": [
      "UI-STOCK-LIST"
    ],
    "capability": "新闻/评分无可核验数据时明确未获取",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/macro.jpg",
    "screenshot_sha256": "18ce90f05f7f8e7abbae05418ece8be8661d7dddbf5bd9c8138087fc42052056",
    "captured_at": "2026-09-20T06:49:07.979937+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "379de2bb28104bf4da3d303cf18c1313f307e3971ef9d13839a23e2134cb96ff",
    "previous_fingerprint": null,
    "decision": "新增截图"
  },
  {
    "id": "UI-INDEX",
    "name": "指数行情",
    "module": "指数行情",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-012",
    "entry": "顶部指数→上证指数详情",
    "parent": null,
    "relations": [
      "UI-STOCK-LIST"
    ],
    "capability": "上证指数60天日K；成交额缺失不估造，SVG无NaN",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/index.jpg",
    "screenshot_sha256": "fad444fbb4c5fa64d22bd24a021ecf817431c80ad4c6e45b116eb5e1cc8e070c",
    "captured_at": "2026-09-20T06:49:38.199259+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "eb0cf3b39711f23da20a77d696c50fbbd6311df0a94b72bfa408f2eef2a2189d",
    "previous_fingerprint": null,
    "decision": "新增截图"
  },
  {
    "id": "UI-DATA-CENTER",
    "name": "数据中心",
    "module": "数据中心",
    "type": "页面",
    "status": "已完成（本地技术验收）",
    "requirements": "REQ-012",
    "entry": "顶部数据中心",
    "parent": null,
    "relations": [
      "UI-STOCK-LIST"
    ],
    "capability": "100/100真实行情采集审计；旧日志数据未核验；批次仅用于追溯",
    "remaining": "用户验收/生产发布未执行；数据缺失范围见来源清单",
    "layout": "深色顶部导航、分组控制与表格或SVG图表",
    "screenshot": "../assets/003-r02/data-center.jpg",
    "screenshot_sha256": "d952dd44d7d192bc78058557df1add261a290ced14b5ec4ec7ff720dab89b3fc",
    "captured_at": "2026-09-20T06:49:07.666206+00:00",
    "viewport": [
      1280,
      720
    ],
    "source_revision": "a0cd26fe9d4d5fb9d12c921e344a0c2e67f7b565",
    "version": "v4.5.0",
    "input_fingerprint": "973e797a3492925feac728933d5d7d567560f5b0dc5e08778c6ce53738f5cc20",
    "previous_fingerprint": null,
    "decision": "新增截图"
  }
]
```
