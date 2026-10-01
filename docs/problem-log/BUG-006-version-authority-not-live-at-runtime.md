# BUG-006：发布新版本后接口仍返回旧版本，页面徽标/标题与 `config/version.json` 不一致

| 字段 | 内容 |
| :--- | :--- |
| 编号 | BUG-006 |
| 发现时间 | 2026-09-24（R10 批次，v5.5.0 发版过程中） |
| 严重级别 | 中（不产生错误数据，但**版本单一权威在运行期失效**，会误导验收与线上排查） |
| 状态 | 已修复（v5.5.0，需求 REQ-054） |
| 影响版本 | ≤ v5.4.1 |
| 修复版本 | v5.5.0 |

## 1. 现象（真实复现）

R10 批次把 `config/version.json` 从 `v5.4.1` 升到 `v5.5.0` 后，**未重启**服务端：

```console
$ python3 -c "import json;print(json.load(open('config/version.json'))['version'])"
v5.5.0
$ curl -s http://127.0.0.1:8888/api/version | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])"
v5.4.1                       # ← 权威文件已是 v5.5.0，接口仍返回旧值
```

真机页面同时暴露该不一致（headless Chrome 实测页面标题）：

```
✅ 页面加载成功 — 【v5.4.1】A股多维量化筛选器 - DSH Stock Web
```

即：`web/index.html` 里的徽标静态文本已是 `v5.5.0`，但 app.js 启动时用 `/api/version` 的返回值**覆写**徽标与标题，于是整页又显示回 `v5.4.1`。

## 2. 根因

`scripts/stock_web_server.py` 在**模块导入时**读一次版本文件并缓存进常量：

```python
VERSION_INFO = load_version_info()
APP_VERSION = VERSION_INFO.get("version", "v1.2.0")
...
self._send_json(200, {"version": APP_VERSION, "info": VERSION_INFO})   # /api/version
```

`APP_VERSION` 是进程级不可变值，所以：

1. 版本文件改动对运行中的服务端**不可见**，必须手工重启（或等看门狗拉起）才生效；
2. 期间产品处于**自相矛盾**状态：磁盘上的唯一权威是 v5.5.0，而接口/徽标/标题是 v5.4.1；
3. 更隐蔽的是，验收脚本若同时读取页面与接口做一致性比对，会因为**两边都是旧值**而"通过"，
   从而漏掉真实版本 —— 本次即由「真机页面标题 vs 版本文件」的交叉核对才发现。

## 3. 修复（REQ-054）

`config/version.json` 作为唯一权威，必须在**运行期即时生效**：

```python
_VERSION_CACHE = {"stamp": None, "info": VERSION_INFO}

def current_version_info() -> dict:
    stat = os.stat(VERSION_FILE)
    stamp = (stat.st_mtime_ns, stat.st_size)          # 以 mtime+size 作为失效判据
    if _VERSION_CACHE["stamp"] != stamp:
        _VERSION_CACHE["info"] = load_version_info()
        _VERSION_CACHE["stamp"] = stamp
    return _VERSION_CACHE["info"]

def current_version() -> str:
    return current_version_info().get("version", APP_VERSION)
```

所有对外暴露版本的响应（`/api/version`、`/api/status`、`/api/filter_schema`、导出包、大盘/宏观接口）与启动横幅一律改为 `current_version()`；
`APP_VERSION` 仅保留为进程启动日志的初始值。文件不存在或 JSON 损坏时回退到上一次已知值，**不抛异常**（版本查询不得导致服务不可用）。

## 4. 修复后实测（本机真实实例，未重启进程）

```console
$ curl -s http://127.0.0.1:8888/api/version | ...    # 重启后加载新代码
v5.5.0
$ # 就地改写 config/version.json 的 description（进程不动）
$ sleep 0.3; curl -s http://127.0.0.1:8888/api/version | ...
改写后接口描述: （热生效探针）R10 批次（v5.5.0，工程加固，无行情口
$ curl -s http://127.0.0.1:8888/api/status | ...
status 版本: v5.5.0 | 状态: running
```

## 5. 回归防线

- `tests/test_r10_version_authority.py`（6 项）：改动后无需重启即生效、未改动时复用缓存、文件缺失/JSON 损坏时回退不崩、以及「对外响应不得再引用 `APP_VERSION`」的静态契约。
- 真机套件中的版本断言一律写成「页面徽标 **与** `/api/version` 一致」（不写死版本号），确保此类不一致今后要么被版本文件驱动、要么直接判红。

## 6. 经验（已并入交接文档）

> **凡是「唯一权威文件」，都要验证它在运行期即时生效**，而不只是在启动时被读到。
> 发版流程里请固定做一次三方交叉核对：权威文件 / 接口 / 真实页面，三者必须同值。
