# BUG-001 K线缓存污染与切换串图风险

状态：已解决（本地验收）。首次/最近：2026-09-19。任务：R01。需求：REQ-008 v1。提交：待提交。

预期：每只股票显示自身真实日线，切换后旧请求不能覆盖当前股票。
实际：只读SQLite连续两次发现茅台、农业银行、工商银行各29条旧缓存，起点2026-08-01（周六）；茅台首日开盘仅3.5元。详情只在缓存为空时请求真实来源，所以旧数据被永久沿用。前端没有取消旧请求或校验响应证券身份；通过乱序响应可复现旧请求覆盖新股票。

环境：macOS，Python 3.9.6；基线提交 f8b53aa9dd5985c0cdaf4463922a0c2fc336e1b7；原工作区未提交修改已保留。本地服务原版本v4.3.0。

最小复现：只读查询 `SELECT code,count(*),min(date),max(date),min(close),max(close) FROM stock_daily_kline GROUP BY code`。修复前两次结果见 [复现证据](../verification/2026-09-19-fix/reproduction.json)。用户描述“所有股票图形完全相同”未逐一穷举证明；已确认旧数据污染和请求竞态两条可复现错误链路。

方案：新建带来源、代码、版本、覆盖状态的可信缓存，保留旧表用于回退和审计；旧表不参与产品K线。对每个证券串行刷新并原子提交；刷新失败保留完整可信缓存并标记stale。前端请求序号、AbortController和证券身份校验；开始加载及关闭时清除旧图状态。删除未调用的日期硬编码模拟K线函数，防止以后误用。

修改：market_history.py、history_service.py、stock_web_server.py、web/app.js。
验证：tests/test_verified_market_data.py，tests/test_detail_requests.js，以及三证券真实接口和浏览器。
回退：`/tmp/dsh-fix-r01/before`保存原脚本、页面、配置和SQLite一致性副本；旧版入口记录于交付说明。不得直接覆盖恢复用户数据。
预防：旧缓存污染、乱序响应、代码不匹配、并发同标的抓取和断网stale均有自动回归。
