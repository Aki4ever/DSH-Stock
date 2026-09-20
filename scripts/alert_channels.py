#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-020: 飞书 / 钉钉 告警通道 (v1)
============================================================
硬性口径：
1. **密钥绝不出现在代码、数据库或日志中**。Webhook 与加签密钥只从
   `config/notify_config.json` 读取（该文件已被 .gitignore 排除），对外只暴露脱敏提示。
2. **未配置即明确报「未配置」**，绝不做任何网络尝试、绝不假装发送成功。
3. 每次下发结果都按真实 HTTP 响应记录到 `alert_dispatch_log`，失败也如实记录。
4. 冷却窗口只由**成功下发**占用；失败不占用冷却，避免一次网络抖动把告警静默吞掉。
5. 本模块只负责「把已经产生的结构化事实送出去」，不产生任何新的判断或预测。
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, BASE_DIR)

CONFIG_PATH = os.path.join(BASE_DIR, "config", "notify_config.json")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config", "notify_config.example.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "cooldown_minutes": 240,
    "max_per_run": 20,
    "timeout_seconds": 8,
    "feishu": {"webhook": "", "secret": ""},
    "dingtalk": {"webhook": "", "secret": ""},
}

CHANNEL_LABELS = {"feishu": "飞书", "dingtalk": "钉钉"}


# ============================================================
# 配置读取（只读文件，绝不写入数据库 / 绝不回显密钥）
# ============================================================

def load_notify_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    """读取告警配置。文件缺失或非法时返回默认（未启用）配置，不抛异常阻断主流程。"""
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if not os.path.exists(path):
        return config
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return config
    if not isinstance(raw, dict):
        return config
    for key in ("enabled", "cooldown_minutes", "max_per_run", "timeout_seconds"):
        if key in raw:
            config[key] = raw[key]
    for channel in ("feishu", "dingtalk"):
        section = raw.get(channel)
        if isinstance(section, dict):
            config[channel] = {
                "webhook": str(section.get("webhook") or "").strip(),
                "secret": str(section.get("secret") or "").strip(),
            }
    return config


def mask_webhook(url: str) -> str:
    """
    把 Webhook 脱敏成可安全展示/落库的形式：只保留主机名与末 4 位，绝不暴露完整令牌。
    """
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or "unknown"
        path = parts.path or ""
        tail = path[-4:] if len(path) >= 4 else ""
        return f"{host}/…{tail}" if tail else host
    except ValueError:
        return "已配置(无法解析)"


def channel_status(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """对外暴露的通道状态：只有是否配置 + 脱敏提示，永不含密钥。"""
    config = config or load_notify_config()
    out = []
    for channel, label in CHANNEL_LABELS.items():
        section = config.get(channel) or {}
        webhook = section.get("webhook") or ""
        out.append({
            "channel": channel,
            "label": label,
            "configured": bool(webhook),
            "signed": bool(section.get("secret")),
            "target_hint": mask_webhook(webhook),
        })
    return out


# ============================================================
# 加签
# ============================================================

def feishu_signature(secret: str, timestamp: int) -> str:
    """飞书自定义机器人加签：以 `{timestamp}\\n{secret}` 为签名字符串做 HMAC-SHA256 后 base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def dingtalk_signature(secret: str, timestamp: int) -> str:
    """钉钉自定义机器人加签：以 `{timestamp}\\n{secret}` 做 HMAC-SHA256 后 base64 + urlencode。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


# ============================================================
# 下发
# ============================================================

def _post_json(url: str, payload: Dict[str, Any], timeout: int) -> Tuple[bool, Optional[int], str]:
    """返回 (是否成功, HTTP 状态码, 错误说明)。所有分支都返回真实结果，不猜测。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        return False, exc.code, f"HTTP {exc.code} {detail}".strip()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, None, f"网络或地址异常: {exc}"

    if status != 200:
        return False, status, f"HTTP {status} {raw[:200]}".strip()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return False, status, f"响应非 JSON: {raw[:120]}"
    # 两家的成功码语义不同，必须分别按官方约定判定，不能只看 HTTP 200
    code = parsed.get("code", parsed.get("StatusCode", parsed.get("errcode")))
    if code in (0, "0"):
        return True, status, ""
    return False, status, f"业务返回失败码 {code}: {str(parsed.get('msg') or parsed.get('errmsg') or parsed)[:160]}"


def send_message(text: str, channel: str, config: Optional[Dict[str, Any]] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    """
    向指定通道发送纯文本告警。
    dry_run=True 时只做配置与签名校验并返回将要发送的内容，不产生任何网络请求。
    """
    config = config or load_notify_config()
    label = CHANNEL_LABELS.get(channel)
    if label is None:
        return {"channel": channel, "ok": False, "sent": False, "reason": f"未知通道 {channel}"}
    section = config.get(channel) or {}
    webhook = (section.get("webhook") or "").strip()
    secret = (section.get("secret") or "").strip()
    hint = mask_webhook(webhook)

    if not webhook:
        return {"channel": channel, "label": label, "ok": False, "sent": False,
                "configured": False, "target_hint": "",
                "reason": f"{label} 未配置 Webhook，未发送任何请求；请在 config/notify_config.json 中填写（该文件不入库、不入版本控制）"}
    if not webhook.startswith("https://"):
        return {"channel": channel, "label": label, "ok": False, "sent": False,
                "configured": True, "target_hint": hint,
                "reason": f"{label} Webhook 必须为 https 地址，已拒绝发送以防令牌明文外泄"}

    url = webhook
    payload: Dict[str, Any]
    timestamp = int(time.time())
    if channel == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
        if secret:
            payload["timestamp"] = str(timestamp)
            payload["sign"] = feishu_signature(secret, timestamp)
    else:
        payload = {"msgtype": "text", "text": {"content": text}}
        if secret:
            url = f"{webhook}&timestamp={timestamp}&sign={dingtalk_signature(secret, timestamp)}"

    if dry_run:
        return {"channel": channel, "label": label, "ok": True, "sent": False, "dry_run": True,
                "configured": True, "target_hint": hint, "signed": bool(secret),
                "reason": f"{label} 配置与签名校验通过；dry-run 未实际发送",
                "preview": text[:400]}

    timeout = int(config.get("timeout_seconds") or 8)
    ok, status_code, error = _post_json(url, payload, timeout)
    return {"channel": channel, "label": label, "ok": ok, "sent": True, "configured": True,
            "target_hint": hint, "status_code": status_code,
            "reason": "" if ok else error}


def dispatch(text: str, channels: Optional[List[str]] = None,
             config: Optional[Dict[str, Any]] = None, dry_run: bool = False) -> List[Dict[str, Any]]:
    """向多个通道下发同一条告警，逐个返回真实结果。"""
    config = config or load_notify_config()
    targets = channels or [c for c in CHANNEL_LABELS if (config.get(c) or {}).get("webhook")]
    if not targets:
        return [{"channel": "-", "ok": False, "sent": False, "configured": False,
                 "reason": "未配置任何告警通道，未发送任何请求"}]
    return [send_message(text, channel, config, dry_run) for channel in targets]


# ============================================================
# 告警文案（只陈述结构化事实，不含任何预测或收益承诺）
# ============================================================

def format_hit_alert(hit: Dict[str, Any]) -> str:
    sign = "🟢 买点" if hit.get("side") == "buy" else "🔴 卖点"
    lines = [
        f"【DSH 策略告警】{hit.get('strategy_name') or hit.get('strategy')}",
        f"{sign} {hit.get('signal_type')} {hit.get('name') or ''} {hit.get('code')}",
    ]
    if hit.get("period"):
        lines.append(f"周期：{'日线' if hit['period'] == 'daily' else hit['period']}")
    if hit.get("close") is not None:
        lines.append(f"现价：{hit['close']}")
    if hit.get("pivot_zg") is not None:
        lines.append(f"中枢上沿 ZG：{hit['pivot_zg']}")
    if hit.get("volume_ratio") is not None:
        lines.append(f"成交量 / {hit.get('volume_window') or 'N'}日均量：{hit['volume_ratio']} 倍")
    if hit.get("reason"):
        lines.append(f"依据：{hit['reason']}")
    if hit.get("entry_price") is not None and hit.get("stop_price") is not None:
        lines.append(f"结构入场 {hit['entry_price']} / 结构止损 {hit['stop_price']}"
                     f"（结构距离 {hit.get('risk_pct')}%）")
    if hit.get("actionable"):
        lines.append(f"建议股数（2%风险预算）：{hit.get('suggested_shares')}")
    else:
        lines.append(f"不可执行：{hit.get('risk_budget_note') or '未给出建议仓位'}")
    lines.append(f"规则版本：{hit.get('rule_version')}")
    lines.append("以上为结构化事实与资金管理参数，不构成投资建议，不承诺收益。")
    return "\n".join(lines)


def alert_key_of(hit: Dict[str, Any]) -> str:
    """告警去重键：同策略同证券同信号类型同周期同一交易日只告警一次（冷却期内）。"""
    return "|".join([
        str(hit.get("strategy") or ""), str(hit.get("code") or ""),
        str(hit.get("signal_type") or ""), str(hit.get("period") or ""),
        str(hit.get("trade_date") or ""),
    ])


def notify_hits(hits: List[Dict[str, Any]], channels: Optional[List[str]] = None,
                config: Optional[Dict[str, Any]] = None, dry_run: bool = False,
                force: bool = False) -> Dict[str, Any]:
    """
    按冷却窗口批量下发命中告警，并把每次真实结果落库。
    只对 actionable=True 的命中下发；不可执行信号不推送，避免制造无用的交易指令。
    """
    from scripts import stock_db

    config = config or load_notify_config()
    if not config.get("enabled") and not dry_run:
        return {"enabled": False, "sent": 0, "skipped": 0, "results": [],
                "reason": "告警总开关未启用（config/notify_config.json 的 enabled=false），未发送任何请求"}

    cooldown = int(config.get("cooldown_minutes") or 0)
    max_per_run = int(config.get("max_per_run") or 20)
    results: List[Dict[str, Any]] = []
    sent = skipped = 0

    candidates = [h for h in hits if h.get("actionable")]
    non_actionable = len(hits) - len(candidates)

    for hit in candidates[:max_per_run]:
        key = alert_key_of(hit)
        text = format_hit_alert(hit)
        for result in dispatch(text, channels, config, dry_run):
            channel = result.get("channel", "-")
            if not force and not dry_run and channel in CHANNEL_LABELS:
                remaining = stock_db.alert_cooldown_remaining(key, channel, cooldown)
                if remaining > 0:
                    skipped += 1
                    results.append(dict(result, ok=False, sent=False,
                                        reason=f"冷却中，剩余 {remaining} 分钟，本次跳过（同一结构不重复告警）"))
                    continue
            if not dry_run and channel in CHANNEL_LABELS:
                stock_db.record_alert_dispatch(
                    key, channel, bool(result.get("ok")), result.get("status_code"),
                    result.get("target_hint") or "", result.get("reason") or "")
            if result.get("ok") and result.get("sent"):
                sent += 1
            results.append(result)

    overflow = max(0, len(candidates) - max_per_run)
    return {
        "enabled": bool(config.get("enabled")),
        "dry_run": bool(dry_run),
        "candidate_count": len(candidates),
        "non_actionable_skipped": non_actionable,
        "sent": sent,
        "skipped": skipped,
        "overflow": overflow,
        "cooldown_minutes": cooldown,
        "results": results,
        "reason": "" if candidates else "本轮无满足可执行条件的命中，未发送任何告警",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="REQ-020 飞书/钉钉告警通道自检")
    parser.add_argument("--send", default="", help="发送一条自定义测试文本；省略则只做配置自检")
    parser.add_argument("--channel", default="", help="只对指定通道操作 (feishu|dingtalk)")
    parser.add_argument("--dry-run", action="store_true", help="只校验配置与签名，不产生网络请求")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = load_notify_config()
    channels = [args.channel] if args.channel else None
    if args.send:
        outcome = dispatch(args.send, channels, config, dry_run=args.dry_run)
    else:
        outcome = channel_status(config)

    if args.json:
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0
    if args.send:
        for item in outcome:
            mark = "✅" if item.get("ok") else "❌"
            print(f"{mark} {item.get('label') or item.get('channel')}: {item.get('reason') or '发送成功'}")
    else:
        print(f"配置文件: {CONFIG_PATH} ({'存在' if os.path.exists(CONFIG_PATH) else '不存在，可参考 ' + EXAMPLE_PATH})")
        print(f"总开关 enabled = {config.get('enabled')}")
        print(f"冷却窗口 = {config.get('cooldown_minutes')} 分钟 / 单轮上限 = {config.get('max_per_run')} 条")
        for item in outcome:
            state = "已配置" if item["configured"] else "未配置"
            sign = "（含加签）" if item["signed"] else ""
            print(f"  {item['label']}: {state}{sign} {item['target_hint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
