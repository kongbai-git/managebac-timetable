"""Failure / status notifications.

Supports the common "push to WeChat" channels plus a generic webhook. All
credentials come from environment variables — never hard-coded.

Channels (pick one by setting the matching env var):
- Server酱 (ServerChan): NOTIFY_SERVERCHAN_SENDKEY   -> push to 微信服务号
- PushPlus:              NOTIFY_PUSHPLUS_TOKEN       -> push to 微信
- 企业微信群机器人:      NOTIFY_WECHAT_WEBHOOK       -> 企业微信 group robot
- Generic webhook:       NOTIFY_WEBHOOK_URL          -> POST JSON {title, content}
"""
from __future__ import annotations

import json
import logging
import sys
from urllib import request, parse

log = logging.getLogger("notify")


def _post_json(url: str, payload: dict, timeout: int = 30) -> str:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _serverchan(sendkey: str, title: str, content: str) -> str:
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = parse.urlencode({"title": title, "desp": content}).encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    with request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def _pushplus(token: str, title: str, content: str) -> str:
    return _post_json(
        "https://www.pushplus.plus/send",
        {"token": token, "title": title, "content": content, "template": "txt"},
    )


def _wechat_robot(webhook: str, title: str, content: str) -> str:
    return _post_json(
        webhook,
        {"msgtype": "text", "text": {"content": f"{title}\n{content}"}},
    )


def _generic_webhook(url: str, title: str, content: str) -> str:
    return _post_json(url, {"title": title, "content": content})


def notify(cfg, title: str, content: str, level: str = "info") -> bool:
    """Send a notification using whichever channel is configured. Returns True
    if a channel was configured and the send did not raise."""
    sent = False
    try:
        if cfg.notify_serverchan_sendkey:
            _serverchan(cfg.notify_serverchan_sendkey, title, content)
            sent = True
            log.info("ServerChan notification sent.")
        elif cfg.notify_pushplus_token:
            _pushplus(cfg.notify_pushplus_token, title, content)
            sent = True
            log.info("PushPlus notification sent.")
        elif cfg.notify_wechat_webhook:
            _wechat_robot(cfg.notify_wechat_webhook, title, content)
            sent = True
            log.info("WeChat Work robot notification sent.")
        elif cfg.notify_webhook_url:
            _generic_webhook(cfg.notify_webhook_url, title, content)
            sent = True
            log.info("Webhook notification sent.")
        else:
            log.info("No notification channel configured; skipping.")
    except Exception as exc:  # noqa: BLE001
        # A notification failure must not crash the whole job.
        log.warning("Notification failed (non-fatal): %s", exc)
        sent = False
    return sent


def notify_failure(cfg, error: Exception) -> None:
    notify(
        cfg,
        title="ManageBac Timetable sync FAILED",
        content=f"Run failed with: {error!r}",
        level="error",
    )


if __name__ == "__main__":
    # Sanity check when run directly.
    from . import config as cfgmod
    c = cfgmod.load_config()
    notify(c, "test title", "test body", "info")
    print("done", file=sys.stderr)
