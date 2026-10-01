#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-020 / R11 物理层补强：告警真实下发链路端到端验证（不依赖任何外部账号）。

背景（为什么需要本测试）：
    既有 `tests/test_r03_screener_alerts.py` 验证的是「签名算法、脱敏、冷却、dry-run 零网络」等
    逻辑层语义；产品真实下发到飞书/钉钉需要一个**外部 Webhook 账号**，本机不可得，因此
    「HTTP POST 真的发出去、对方真的收到、成功码真的被判成功、流水真的落库」这一段长期
    只有逻辑证据、没有物理证据。本测试用**本机回环 HTTPS 接收器**充当 Webhook 对端，
    把该链路在物理层跑通，且不触碰产品数据库、不写产品配置、不发任何外网请求。

物理层触达（本测试断言的事实）：
    1. 真实 socket：127.0.0.1:<port> 上真的有 TLS 握手 + HTTP POST 到达；
    2. 真实报文：接收器解析到的 JSON body 与产品构造的一致（msg_type/text 或 msgtype/text）；
    3. 真实加签：接收器用独立实现的 HMAC 算法校验，签名必须与自己算出的逐字节相等；
    4. 真实成功码：接收器返回 HTTP 200 + 业务码 0，产品必须判 ok=True；返回业务失败码时
       产品必须判 ok=False 并带出对方错误信息（不能只看 HTTP 200）；
    5. 真实失败路径：接收器返回 500 或非 JSON 时，产品必须如实报错，不得假装成功。

仅使用 Python 标准库（与产品零依赖口径一致）。
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts import alert_channels  # noqa: E402
from scripts import stock_db  # noqa: E402


# ---------------------------------------------------------------------------
# 本机回环 HTTPS 接收器（Webhook 对端替身）
# ---------------------------------------------------------------------------
class _Receiver(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    received: list = []
    next_body = {"code": 0, "msg": "ok"}
    next_status = 200
    next_raw = None

    def log_message(self, *args):  # 静默：测试输出只由断言构成
        return

    def do_POST(self):  # noqa: N802 (stdlib 命名)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = None
        _Receiver.received.append({"path": self.path, "headers": dict(self.headers), "raw": raw,
                                   "payload": payload})
        status = _Receiver.next_status
        if _Receiver.next_raw is not None:
            body = _Receiver.next_raw
        else:
            body = json.dumps(_Receiver.next_body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _make_self_signed_cert(dirpath: str) -> tuple[str, str]:
    """用系统 openssl 生成一张仅用于 127.0.0.1 的临时自签证书。"""
    key = os.path.join(dirpath, "key.pem")
    crt = os.path.join(dirpath, "cert.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", key, "-out", crt, "-days", "1",
         "-subj", "/CN=127.0.0.1",
         "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    return key, crt


class _ProbeBase(unittest.TestCase):
    """公共夹具：启动回环 HTTPS 接收器、注入自签证书信任、提供测试用 notify 配置。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        key, crt = _make_self_signed_cert(cls.tmp.name)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        cls.httpd.socket = ctx.wrap_socket(cls.httpd.socket, server_side=True)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        _Receiver.received.clear()
        _Receiver.next_body = {"code": 0, "msg": "ok"}
        _Receiver.next_status = 200
        _Receiver.next_raw = None
        self.secret = "test-secret-物理层"
        self.config = {
            "enabled": True,
            "timeout_seconds": 8,
            "cooldown_minutes": 240,
            "max_per_run": 20,
            "feishu": {"webhook": f"https://127.0.0.1:{self.port}/open-apis/bot/v2/hook/abc1234",
                       "secret": self.secret},
            "dingtalk": {"webhook": f"https://127.0.0.1:{self.port}/robot/send?access_token=def5678",
                         "secret": self.secret},
        }

    @contextlib.contextmanager
    def _trusted(self):
        """
        仅在本调用期间，把 urllib 的全局 opener 换成「不校验自签证书」的那一个。

        为什么必须换 opener，而不是只改 `ssl._create_default_https_context`：
        `urllib.request.urlopen` 在**首次调用**时会构建并缓存一个全局 opener
        （`urllib.request._opener`），其中的 `HTTPSHandler` 已把默认 HTTPS 上下文固定在
        实例里。此后即使再改 `ssl._create_default_https_context` 也不会生效 —— 全量
        `unittest discover` 中前面 231 个用例已触发过首次调用，这正是只改 ssl 模块属性
        的写法在生产代码里仍走证书校验的原因（实测 CERTIFICATE_VERIFY_FAILED）。

        因此这里显式换掉全局 opener，用完立刻还原：
        - **产品代码 `scripts/alert_channels.py` 一字未改**，仍走它自己的
          `urllib.request.urlopen(url)` 真实 HTTPS POST 路径；
        - 仅「是否信任自签证书」这一项被本测试替换（本机回环接收器用临时自签证书），
          生产环境证书校验行为不受影响 —— 两个 opener 的唯一差别就是这一项。
        """
        import urllib.request
        original_opener = urllib.request._opener
        ctx = ssl._create_unverified_context()
        handler = urllib.request.HTTPSHandler(context=ctx)
        urllib.request.install_opener(urllib.request.build_opener(
            urllib.request.ProxyHandler(), handler))
        try:
            yield
        finally:
            if original_opener is None:
                urllib.request._opener = None
            else:
                urllib.request.install_opener(original_opener)


class NotifyEndToEndTest(_ProbeBase):
    """物理层：真实 TLS + 真实 HTTP POST + 真实签名核对 + 真实成功码判定。"""

    # -- 1. 真实 socket 到达 + 报文形态 ------------------------------------
    def test_01_feishu_really_reaches_socket(self):
        with self._trusted():
            result = alert_channels.send_message("R11 物理层探针 / 飞书", "feishu", self.config)
        self.assertTrue(result["ok"], msg=str(result))
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(len(_Receiver.received), 1, "接收器必须真的收到一次 POST")
        got = _Receiver.received[0]
        self.assertEqual(got["payload"]["msg_type"], "text")
        self.assertIn("R11 物理层探针", got["payload"]["content"]["text"])
        self.assertTrue(got["headers"].get("Content-Type", "").startswith("application/json"))

    def test_02_dingtalk_really_reaches_socket(self):
        with self._trusted():
            result = alert_channels.send_message("R11 物理层探针 / 钉钉", "dingtalk", self.config)
        self.assertTrue(result["ok"], msg=str(result))
        self.assertEqual(len(_Receiver.received), 1)
        got = _Receiver.received[0]
        self.assertEqual(got["payload"]["msgtype"], "text")
        self.assertIn("R11 物理层探针", got["payload"]["text"]["content"])

    # -- 2. 真实加签：接收器独立复算，必须逐字节一致 ------------------------
    def test_03_feishu_signature_verified_by_receiver(self):
        with self._trusted():
            alert_channels.send_message("签名核对", "feishu", self.config)
        payload = _Receiver.received[0]["payload"]
        ts, sign = payload["timestamp"], payload["sign"]
        expect = base64.b64encode(
            hmac.new(f"{ts}\n{self.secret}".encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        self.assertEqual(sign, expect)
        self.assertAlmostEqual(int(ts), int(time.time()), delta=30)

    def test_04_dingtalk_signature_verified_by_receiver(self):
        with self._trusted():
            alert_channels.send_message("签名核对", "dingtalk", self.config)
        got = _Receiver.received[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(got["path"]).query)
        ts, sign = query["timestamp"][0], query["sign"][0]
        expect = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"), f"{ts}\n{self.secret}".encode("utf-8"),
                     digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        # 产品侧做了 urlencode；parse_qs 已解码，二者必须相等
        self.assertEqual(sign, expect)

    # -- 3. 真实成功码判定：HTTP 200 但业务失败码必须判失败 ------------------
    def test_05_http200_with_business_error_code_is_failure(self):
        _Receiver.next_body = {"code": 19021, "msg": "sign match fail"}
        with self._trusted():
            result = alert_channels.send_message("失败码", "feishu", self.config)
        self.assertFalse(result["ok"])
        self.assertIn("19021", result["reason"])
        self.assertEqual(result["status_code"], 200)

    def test_06_http500_is_failure(self):
        _Receiver.next_status = 500
        _Receiver.next_body = {"code": 0}
        with self._trusted():
            result = alert_channels.send_message("HTTP 500", "feishu", self.config)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 500)

    def test_07_non_json_response_is_failure(self):
        _Receiver.next_raw = b"<html>502 Bad Gateway</html>"
        with self._trusted():
            result = alert_channels.send_message("非 JSON", "dingtalk", self.config)
        self.assertFalse(result["ok"])
        self.assertIn("非 JSON", result["reason"])

    # -- 4. 真实多通道 fan-out ---------------------------------------------
    def test_08_dispatch_fans_out_to_both_channels(self):
        with self._trusted():
            out = alert_channels.dispatch("R11 双通道", None, self.config)
        self.assertEqual({i["channel"] for i in out}, {"feishu", "dingtalk"})
        self.assertTrue(all(i["ok"] for i in out), msg=str(out))
        self.assertEqual(len(_Receiver.received), 2)

    # -- 5. 未配置 / 非 https 时不得产生任何网络请求 ------------------------
    def test_09_unconfigured_makes_zero_requests(self):
        cfg = {"enabled": True, "feishu": {"webhook": "", "secret": ""},
               "dingtalk": {"webhook": "", "secret": ""}}
        out = alert_channels.dispatch("不该发出去", None, cfg)
        self.assertFalse(any(i["ok"] for i in out))
        self.assertEqual(len(_Receiver.received), 0)

    def test_10_plain_http_rejected_before_any_request(self):
        cfg = {"enabled": True,
               "feishu": {"webhook": f"http://127.0.0.1:{self.port}/x", "secret": ""},
               "dingtalk": {"webhook": "", "secret": ""}}
        out = alert_channels.dispatch("明文不该发出去", ["feishu"], cfg)
        self.assertFalse(out[0]["ok"])
        self.assertIn("https", out[0]["reason"])
        self.assertEqual(len(_Receiver.received), 0)


class NotifyPipelinePhysicalTest(_ProbeBase):
    """
    物理层：命中 → notify_hits → 真实 HTTPS 下发 → 真实 SQLite 流水落库 + 冷却语义。

    本用例把产品库替换为临时库（mock.patch stock_db.DB_PATH），因此对真实产品库零写入。
    """

    def setUp(self):
        super().setUp()
        self.tmpdb = tempfile.TemporaryDirectory()
        self.db_file = os.path.join(self.tmpdb.name, "probe.db")
        self._patch = mock.patch.object(stock_db, "DB_PATH", self.db_file)
        self._patch.start()
        stock_db.init_db()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self.tmpdb.cleanup)

    def _hit(self, **over):
        hit = {
            "strategy": "dip-divergence-breakout", "strategy_name": "底背驰 + 放量突破中枢",
            "code": "sh600519", "name": "贵州茅台", "signal_type": "3B", "side": "buy",
            "period": "daily", "trade_date": "2026-09-30", "close": 1243.88,
            "pivot_zg": 1200.0, "volume_ratio": 1.83, "volume_window": 20,
            "entry_price": 1205.0, "stop_price": 1190.0, "risk_pct": 1.24,
            "actionable": True, "suggested_shares": 800,
            "reason": "放量突破笔中枢上沿",
        }
        hit.update(over)
        return hit

    def _rows(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM alert_dispatch_log ORDER BY id;")]
        finally:
            conn.close()

    def _notify(self, hits, channels=None, **kw):
        with self._trusted():
            return alert_channels.notify_hits(hits, channels, self.config, **kw)

    def test_11_full_pipeline_sends_and_persists(self):
        out = self._notify([self._hit()], ["feishu"])
        self.assertEqual(out["sent"], 1, msg=str(out))
        # 物理事实 1：接收器真的收到了这一次 POST
        self.assertEqual(len(_Receiver.received), 1)
        body = _Receiver.received[0]["payload"]
        self.assertIn("贵州茅台", body["content"]["text"])
        self.assertIn("3B", body["content"]["text"])
        # 物理事实 2：流水真的写进了 SQLite 文件（不是内存、不是日志字符串）
        rows = self._rows()
        self.assertEqual(len(rows), 1, msg=str(rows))
        self.assertEqual(rows[0]["channel"], "feishu")
        self.assertEqual(rows[0]["ok"], 1)
        self.assertEqual(rows[0]["status_code"], 200)
        self.assertEqual(rows[0]["alert_key"],
                         "dip-divergence-breakout|sh600519|3B|daily|2026-09-30")
        # 物理事实 3：落库的是脱敏提示，令牌明文绝不入库
        self.assertIn("127.0.0.1", rows[0]["target_hint"])
        self.assertNotIn("abc1234", json.dumps(rows, ensure_ascii=False))

    def test_12_cooldown_makes_zero_network_requests(self):
        """
        冷却期内的第二次呼叫：**零网络请求**（冷却判定已前移到 dispatch 之前）。

        该断言是行为变更的物理证据：修复前 `notify_hits` 先 `dispatch()` 再判冷却，
        接收器会真的收到第二次 POST；修复后冷却命中直接 `continue`，接收器不得再有新请求。
        """
        self._notify([self._hit()], ["feishu"])
        self.assertEqual(len(_Receiver.received), 1)
        again = self._notify([self._hit()], ["feishu"])
        self.assertEqual(again["skipped"], 1)
        self.assertEqual(again["sent"], 0)
        self.assertIn("冷却中", again["results"][0]["reason"])
        self.assertEqual(len(self._rows()), 1, "冷却跳过不得新增流水")
        self.assertEqual(len(_Receiver.received), 1,
                         "冷却期内不得产生任何新的网络请求（修复前此处为 2）")

    def test_13_force_bypasses_cooldown(self):
        self._notify([self._hit()], ["feishu"])
        forced = self._notify([self._hit()], ["feishu"], force=True)
        self.assertEqual(forced["sent"], 1)
        self.assertEqual(len(_Receiver.received), 2)
        self.assertEqual(len(self._rows()), 2)

    def test_14_non_actionable_hit_never_sends(self):
        out = self._notify([self._hit(actionable=False)], ["feishu"])
        self.assertEqual(out["sent"], 0)
        self.assertEqual(out["non_actionable_skipped"], 1)
        self.assertEqual(len(_Receiver.received), 0)
        self.assertEqual(len(self._rows()), 0)

    def test_15_failed_send_is_persisted_but_does_not_block_retry(self):
        _Receiver.next_body = {"code": 19021, "msg": "sign match fail"}
        first = self._notify([self._hit()], ["feishu"])
        self.assertEqual(first["sent"], 0)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ok"], 0)
        self.assertIn("19021", rows[0]["error"])
        # 失败不占用冷却：对端恢复后必须能立刻重试
        _Receiver.next_body = {"code": 0, "msg": "ok"}
        second = self._notify([self._hit()], ["feishu"])
        self.assertEqual(second["sent"], 1, msg=str(second))
        self.assertEqual(len(_Receiver.received), 2)
        self.assertEqual([r["ok"] for r in self._rows()], [0, 1])

    def test_16_disabled_switch_makes_zero_requests_and_zero_rows(self):
        out = alert_channels.notify_hits([self._hit()], ["feishu"], dict(self.config, enabled=False))
        self.assertFalse(out["enabled"])
        self.assertEqual(len(_Receiver.received), 0)
        self.assertEqual(len(self._rows()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
