# 真实历史与股东行为 CLI

REQ-008/009的核心自动化入口，复用网页同一可信缓存。读取会在缺失/过期时请求公开来源并写入本地缓存；不进行交易或外部写入。

```sh
python3 scripts/dsh_stock_cli.py history sh600519 --json
python3 scripts/dsh_stock_cli.py history sz000001 --refresh --include-bars --json
python3 scripts/dsh_stock_cli.py holder-actions sh600519 --days 365 --json
python3 scripts/dsh_stock_cli.py holder-actions --days 90 --refresh --json
```

输出均为JSON；exit 0完整来源数据，exit 1部分/过期/不可用，exit 2无效参数或运行错误。`DSH_STOCK_DB=/absolute/path/review.db`支持隔离验证。默认返回元数据，历史加`--include-bars`才包含全量数组；股东不传code时输出全市场覆盖摘要。

必需：真实历史与股东行为已覆盖。后续：旧quote/analyze/chart/report命令遗留Mock行为未在本次扩展，不能作为本轮真实数据验收入口。交互画线属于网页功能，不强行包装CLI。
