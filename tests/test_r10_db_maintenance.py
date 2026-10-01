"""R10 批次（v5.5.0）回归：REQ-052 非破坏性数据库归档/体检。

原则：
1. 全部用例只操作**临时库**，绝不触碰产品库 `data/stock_database.db`（用例末尾会显式断言其哈希未变）；
2. 断言真实行为（真实 SQLite 文件、真实进程调用 CLI），不 mock 被测实现；
3. 唯一使用 patch 的用例是为了验证「源库在归档期间被写入」时的诚实报告分支，
   该分支无法在单进程内确定性触发（需要并发写入），故只替换哈希读取顺序。
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts import db_maintenance as dbm  # noqa: E402

PRODUCT_DB = os.path.join(BASE_DIR, "data", "stock_database.db")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_db(path, stocks=200, quotes=150, delete_ratio=0):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE stocks_master (code TEXT PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE stock_quotes (code TEXT, price REAL)")
    conn.executemany("INSERT INTO stocks_master VALUES (?,?)", [(f"{i:06d}", f"标的{i}") for i in range(stocks)])
    conn.executemany("INSERT INTO stock_quotes VALUES (?,?)", [("600519", 1700.0 + i) for i in range(quotes)])
    conn.commit()
    if delete_ratio:
        conn.execute(f"DELETE FROM stock_quotes WHERE rowid % {delete_ratio} = 0")
        conn.commit()
    conn.close()
    return {"stocks_master": stocks, "stock_quotes": quotes - (quotes // delete_ratio if delete_ratio else 0)}


class DBTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="r10-db-")
        self.src = os.path.join(self.tmp, "src.db")
        self.expected = make_db(self.src, delete_ratio=2)
        self.archive_dir = os.path.join(self.tmp, "arch")
        self.product_hash = sha256_of(PRODUCT_DB) if os.path.isfile(PRODUCT_DB) else None

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        # 红线：任何用例都不得改动产品库
        if self.product_hash is not None:
            self.assertEqual(sha256_of(PRODUCT_DB), self.product_hash,
                             "测试期间产品库 data/stock_database.db 被改动了")


class TestInspect(DBTestCase):
    def test_reports_size_integrity_structure(self):
        info = dbm.inspect_database(self.src)
        self.assertEqual(info["integrity_check"], "ok")
        self.assertEqual(info["quick_check"], "ok")
        self.assertEqual(info["table_count"], 2)
        self.assertEqual(info["table_row_counts"], self.expected)
        self.assertEqual(info["total_rows"], sum(self.expected.values()))
        self.assertGreater(info["size_bytes"], 0)
        self.assertEqual(info["source_sha256"], sha256_of(self.src))

    def test_readonly_connection_rejects_writes(self):
        """安全边界：源库连接必须是只读的，任何写操作都要被 SQLite 拒绝。"""
        conn = dbm._open_readonly(self.src)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM stock_quotes")
        finally:
            conn.close()

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            dbm.inspect_database(os.path.join(self.tmp, "nope.db"))


class TestArchive(DBTestCase):
    def test_archive_is_faithful_and_nondestructive(self):
        before = sha256_of(self.src)
        res = dbm.archive_database(self.src, self.archive_dir, label="unit")
        self.assertEqual(res["status"], "available")
        self.assertTrue(res["source_unchanged"])
        self.assertTrue(res["source_opened_readonly"])
        self.assertEqual(sha256_of(self.src), before, "源库必须逐字节不变")
        self.assertTrue(os.path.isfile(res["archive"]["path"]))
        self.assertEqual(res["archive"]["integrity_check"], "ok")
        self.assertEqual(res["archive"]["total_rows"], sum(self.expected.values()))
        # 归档件应可独立打开并读到同样的行数
        conn = sqlite3.connect(res["archive"]["path"])
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM stocks_master").fetchone()[0],
                             self.expected["stocks_master"])
        finally:
            conn.close()

    def test_manifest_is_written_and_traceable(self):
        res = dbm.archive_database(self.src, self.archive_dir, label="trace")
        self.assertTrue(os.path.isfile(res["manifest"]))
        with open(res["manifest"], encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("generated_at", "source", "archive", "source_sha256_before", "notes", "retention_keep"):
            self.assertIn(key, data)
        self.assertEqual(data["archive"]["sha256"], sha256_of(data["archive"]["path"]))
        self.assertEqual(data["source"]["integrity_check"], "ok")

    def test_compact_copy_is_smaller_and_intact(self):
        res = dbm.archive_database(self.src, self.archive_dir, label="cmp", compact=True)
        compacted = res["compacted"]
        self.assertIsNotNone(compacted)
        # 先删行制造空闲页，紧凑副本应当更小（或至少不更大）
        self.assertLessEqual(compacted["size_bytes"], res["archive"]["size_bytes"])
        self.assertEqual(compacted["integrity_check"], "ok")
        self.assertEqual(compacted["total_rows"], sum(self.expected.values()))
        self.assertEqual(compacted["table_count"], 2)
        self.assertTrue(os.path.isfile(compacted["path"]))
        conn = sqlite3.connect(compacted["path"])
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM stock_quotes").fetchone()[0],
                             self.expected["stock_quotes"])
        finally:
            conn.close()

    def test_second_archive_in_same_second_never_overwrites(self):
        first = dbm.archive_database(self.src, self.archive_dir)
        second = dbm.archive_database(self.src, self.archive_dir)
        self.assertNotEqual(first["archive"]["path"], second["archive"]["path"])
        self.assertTrue(os.path.isfile(first["archive"]["path"]))
        self.assertTrue(os.path.isfile(second["archive"]["path"]))

    def test_keep_zero_never_deletes(self):
        for _ in range(3):
            dbm.archive_database(self.src, self.archive_dir, keep=0)
        dbs = [f for f in os.listdir(self.archive_dir) if f.endswith(".db")]
        self.assertEqual(len(dbs), 3)

    def test_keep_prunes_only_oldest_groups(self):
        paths = [dbm.archive_database(self.src, self.archive_dir, label=f"g{i}")["archive"]["path"] for i in range(3)]
        res = dbm.archive_database(self.src, self.archive_dir, label="g3", keep=2)
        self.assertTrue(res["pruned"], "应当清理超出保留数的旧归档")
        remaining = sorted(f for f in os.listdir(self.archive_dir) if f.endswith(".db"))
        self.assertEqual(len(remaining), 2)
        # 被清理的是最早的组（时间戳+标签字典序最小）
        for path in paths[:1]:
            self.assertFalse(os.path.isfile(path))
        self.assertTrue(os.path.isfile(paths[-1]))
        # manifest 必须与其 db 同组同命运
        self.assertFalse(os.path.isfile(os.path.splitext(os.path.basename(paths[0]))[0] + dbm.MANIFEST_SUFFIX))

    def test_negative_keep_rejected(self):
        with self.assertRaises(ValueError):
            dbm.archive_database(self.src, self.archive_dir, keep=-1)

    def test_source_change_during_backup_is_reported_not_raised(self):
        """运行中的服务端会持续写库：该情形必须如实记录，而不是让归档整体失败。"""
        real_sha = dbm._sha256
        calls = {"n": 0}

        def fake_sha(path, chunk=1 << 20):
            calls["n"] += 1
            return real_sha(path, chunk) if calls["n"] == 1 else "0" * 64

        with mock.patch.object(dbm, "_sha256", side_effect=fake_sha):
            res = dbm.archive_database(self.src, self.archive_dir, label="live")
        self.assertFalse(res["source_unchanged"])
        self.assertEqual(res["source_sha256_after"], "0" * 64)
        self.assertTrue(any("哈希发生变化" in n for n in res["notes"]))
        self.assertEqual(res["archive"]["integrity_check"], "ok")


class TestCLI(DBTestCase):
    def run_cli(self, *args):
        env = dict(os.environ)
        env["DSH_STOCK_DB"] = self.src
        return subprocess.run([sys.executable, "scripts/dsh_stock_cli.py", *args],
                              cwd=BASE_DIR, env=env, capture_output=True, text=True)

    def test_cli_json_output_points_at_the_given_db(self):
        proc = self.run_cli("db-archive", "--db", self.src, "--dir", self.archive_dir, "--label", "cli", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["source"]["path"], os.path.abspath(self.src))
        self.assertEqual(payload["archive"]["integrity_check"], "ok")
        self.assertTrue(os.path.isfile(payload["archive"]["path"]))

    def test_cli_reports_error_for_missing_db(self):
        proc = self.run_cli("db-archive", "--db", os.path.join(self.tmp, "ghost.db"), "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["status"], "error")

    def test_cli_is_listed_in_help(self):
        proc = subprocess.run([sys.executable, "scripts/dsh_stock_cli.py", "--help"],
                              cwd=BASE_DIR, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("db-archive", proc.stdout)


if __name__ == "__main__":
    unittest.main()
