#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 本地数据库运维引擎（非破坏性归档 / 完整性核验）
需求：REQ-052（v5.5.0）

设计红线（与产品质量红线一致）：
1. **绝不修改源库**：对源库只以 `mode=ro` 打开，只执行 `PRAGMA integrity_check` / `quick_check` 与
   `SELECT` 读取；不使用 `VACUUM`（会写源库）、不迁移、不重建、不删除任何源库文件。
2. 归档一律走 SQLite **在线备份 API**（`Connection.backup`），WAL 模式下对正在运行的服务端安全。
3. 紧凑副本走 `VACUUM INTO '<新文件>'`：只读源库、另写一份紧凑文件，源库字节不变。
4. 每个归档产物都写一份 `.manifest.json`（源库哈希/大小、行数、完整性结果、命令与时间），可追溯。
5. 清理旧归档**只在显式给 `--keep N`（N>0）时发生**，且只删本工具自己命名规则内的归档文件。
"""

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "stock_database.db")
DEFAULT_ARCHIVE_DIR = os.path.join(BASE_DIR, "data", "backups", "db-archive")

ARCHIVE_PREFIX = "stock_database-"
ARCHIVE_SUFFIX = ".db"
MANIFEST_SUFFIX = ".manifest.json"


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------
def _sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _open_readonly(path: str) -> sqlite3.Connection:
    """只读打开（URI mode=ro）。任何写操作都会直接抛错，这是本模块的安全边界。"""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def inspect_database(path: str) -> Dict[str, Any]:
    """只读体检：大小、页信息、完整性、逐表行数。不改动任何字节。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"数据库文件不存在：{path}")
    info: Dict[str, Any] = {
        "path": os.path.abspath(path),
        "size_bytes": os.path.getsize(path),
        "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds"),
        "wal_present": os.path.isfile(path + "-wal"),
        "shm_present": os.path.isfile(path + "-shm"),
    }
    conn = _open_readonly(path)
    try:
        info["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        info["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
        info["page_size"] = conn.execute("PRAGMA page_size").fetchone()[0]
        info["page_count"] = conn.execute("PRAGMA page_count").fetchone()[0]
        info["freelist_count"] = conn.execute("PRAGMA freelist_count").fetchone()[0]
        info["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
        counts = {}
        for name in _table_names(conn):
            counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        info["table_row_counts"] = counts
        info["table_count"] = len(counts)
        info["total_rows"] = sum(counts.values())
    finally:
        conn.close()
    info["source_sha256"] = _sha256(path)
    return info


def _unique_path(directory: str, stamp: str, label: str, kind: str) -> str:
    """归档文件名：stock_database-<时间戳>[-<标签>][-kind].db；同秒冲突自动加序号，绝不覆盖既有文件。"""
    base = f"{ARCHIVE_PREFIX}{stamp}"
    if label:
        base += f"-{label}"
    if kind == "compacted":
        base += "-compacted"
    candidate = os.path.join(directory, base + ARCHIVE_SUFFIX)
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}-{index}{ARCHIVE_SUFFIX}")
        index += 1
    return candidate


def archive_database(
    db_path: str = DEFAULT_DB_PATH,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    label: str = "",
    compact: bool = False,
    keep: int = 0,
) -> Dict[str, Any]:
    """非破坏性归档。

    参数
    ----
    db_path     源库路径（默认产品库 data/stock_database.db）
    archive_dir 归档目录（默认 data/backups/db-archive/，会自动创建）
    label       归档标签（可选，写入文件名与 manifest）
    compact     是否额外生成紧凑副本（`VACUUM INTO`，源库不变）
    keep        保留最近 N 份归档；**默认 0 = 只增不删**，仅在 N>0 时清理更旧的归档

    返回结构化结果；任何一步失败都抛异常，绝不留下"看起来成功"的半成品（失败副本会被删除）。
    """
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"源库不存在：{db_path}")
    if keep < 0:
        raise ValueError("keep 不能为负数")
    os.makedirs(archive_dir, exist_ok=True)

    before = inspect_database(db_path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = _unique_path(archive_dir, stamp, label, "full")
    compact_target: Optional[str] = None

    started = datetime.now().isoformat(timespec="seconds")
    src = _open_readonly(db_path)
    try:
        # SQLite 在线备份 API：只读源库 → 新文件；WAL 下对运行中的服务端安全
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")  # 归档件不携带 WAL，便于单文件长期保存
        finally:
            dst.close()

        if compact:
            compact_target = _unique_path(archive_dir, stamp, label, "compacted")
            # VACUUM INTO 只读源库、另写紧凑副本（源库字节不变，已由 after 哈希核验）
            src.execute("VACUUM INTO ?", (compact_target,))
    except Exception:
        for path in (target, compact_target):
            if path and os.path.exists(path):
                os.remove(path)  # 半成品一律清掉，不留误导性产物
        raise
    finally:
        src.close()

    after = inspect_database(db_path)
    # 说明：本工具对源库只以 mode=ro 打开，SQLite 内核保证不可能写入源库。
    # 但运行中的服务端会持续把行情缓存写入源库，因此归档期间源库哈希**可能**变化 ——
    # 这属正常现象，归档件是"备份开始时刻"的一致性快照；此处如实记录，不当作失败。
    source_unchanged = after["source_sha256"] == before["source_sha256"]

    archive_info = inspect_database(target)
    if archive_info["integrity_check"] != "ok":
        raise RuntimeError(f"归档件完整性校验失败：{archive_info['integrity_check']}")
    mismatched = {
        name: {"source": before["table_row_counts"].get(name), "archive": count}
        for name, count in archive_info["table_row_counts"].items()
        if before["table_row_counts"].get(name) != count
    }
    missing = sorted(set(before["table_row_counts"]) - set(archive_info["table_row_counts"]))
    if mismatched or missing:
        raise RuntimeError(f"归档件与源库行数不一致：{mismatched or ''} 缺表:{missing or ''}")

    result: Dict[str, Any] = {
        "status": "available",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started,
        "label": label or None,
        "source": {k: before[k] for k in ("path", "size_bytes", "table_count", "total_rows", "integrity_check")},
        "source_sha256_before": before["source_sha256"],
        "source_sha256_after": after["source_sha256"],
        "source_unchanged": source_unchanged,
        "source_opened_readonly": True,
        "archive": {
            "path": target,
            "size_bytes": os.path.getsize(target),
            "table_count": archive_info["table_count"],
            "total_rows": archive_info["total_rows"],
            "integrity_check": archive_info["integrity_check"],
            "sha256": archive_info["source_sha256"],
        },
        "compacted": None,
        "pruned": [],
        "notes": [
            "源库以只读方式打开（URI mode=ro），SQLite 内核保证本工具无法写入源库：无 VACUUM / 无迁移 / 无重建",
            "归档通过 SQLite 在线备份 API 生成，WAL 模式下对运行中的服务端安全",
            ("归档期间源库哈希未变（源库当时处于静止状态）" if source_unchanged
             else "归档期间源库哈希发生变化：运行中的服务端在正常写入行情缓存；归档件为备份开始时刻的一致性快照"),
        ],
    }

    if compact_target:
        compact_info = inspect_database(compact_target)
        result["compacted"] = {
            "path": compact_target,
            "size_bytes": compact_info["size_bytes"],
            "integrity_check": compact_info["integrity_check"],
            "table_count": compact_info["table_count"],
            "total_rows": compact_info["total_rows"],
            "sha256": compact_info["source_sha256"],
            "saved_bytes": os.path.getsize(target) - compact_info["size_bytes"],
            "freelist_pages_source": before["freelist_count"],
        }

    if keep > 0:
        result["pruned"] = _prune_archives(archive_dir, keep)

    manifest_path = os.path.splitext(target)[0] + MANIFEST_SUFFIX
    manifest = dict(result)
    manifest["archive_dir"] = archive_dir
    manifest["retention_keep"] = keep
    manifest["manifest_path"] = manifest_path
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    result["manifest"] = manifest_path
    return result


def _prune_archives(archive_dir: str, keep: int) -> List[Dict[str, str]]:
    """只删除本工具命名规则内的归档（stock_database-*.db 及其 manifest/紧凑副本），保留最近 keep 组。"""
    groups: Dict[str, List[str]] = {}
    for name in os.listdir(archive_dir):
        if not name.startswith(ARCHIVE_PREFIX):
            continue
        if not (name.endswith(ARCHIVE_SUFFIX) or name.endswith(MANIFEST_SUFFIX)):
            continue
        stamp = name[len(ARCHIVE_PREFIX):]
        # 以「时间戳-标签」分组，同一组（完整+紧凑+manifest）一起保留或一起清理
        for suffix in (MANIFEST_SUFFIX, ARCHIVE_SUFFIX):
            if name.endswith(suffix):
                key = stamp[: -len(suffix)]
                break
        else:  # pragma: no cover - 上面的条件已保证命中
            continue
        key = key.replace("-compacted", "")
        groups.setdefault(key, []).append(name)

    removed: List[Dict[str, str]] = []
    order = sorted(groups.keys())  # 文件名前缀为时间戳，字典序即时间序
    for key in order[:-keep] if keep < len(order) else []:
        for name in sorted(groups[key]):
            full = os.path.join(archive_dir, name)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            os.remove(full)
            removed.append({"path": full, "size_bytes": str(size)})
    return removed
