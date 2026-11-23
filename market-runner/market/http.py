"""Tiny HTTP helpers on top of urllib (no third-party deps)."""
from __future__ import annotations

import json
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def request(url: str, *, method: str = "GET", data: bytes | None = None,
            headers: dict | None = None, timeout: int = 20) -> bytes:
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url: str, **kw):
    return json.loads(request(url, **kw))


def post_json(url: str, payload: dict, **kw):
    headers = {"Content-Type": "application/json"}
    headers.update(kw.pop("headers", {}) or {})
    body = json.dumps(payload).encode()
    return json.loads(request(url, method="POST", data=body, headers=headers, **kw))

