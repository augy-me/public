"""Tiny HTTP helpers on top of urllib (no third-party deps), shared by every package of this repo.

Also the pieces each runner uses to talk to a Worker: the run's GitHub OIDC token, a cleaned https base
URL and the auth headers (Bearer token plus Origin, as the Workers refuse changes from another origin).
"""
from __future__ import annotations

import json
import os
import urllib.parse
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


def _json(raw: bytes):
    return json.loads(raw) if raw else {}


def get_json(url: str, **kw):
    return _json(request(url, **kw))


def post_json(url: str, payload: dict, **kw):
    headers = {"Content-Type": "application/json"}
    headers.update(kw.pop("headers", {}) or {})
    body = json.dumps(payload).encode()
    return _json(request(url, method="POST", data=body, headers=headers, **kw))


def base_url(raw: str) -> str:
    """A Worker's https base URL without the trailing slash, or "" if it is not one. A pasted variable can
    carry spaces, quotes or invisible characters ("unknown url type: https")."""
    url = "".join(c for c in raw if "!" <= c <= "~" and c not in "\"'<>").rstrip("/")
    return url if url.startswith("https://") else ""


def auth(base: str, token: str) -> dict:
    """Headers for a call to the Worker at ``base``: the token and the Origin it checks."""
    return {"Authorization": f"Bearer {token}", "Origin": base}


def oidc_token(audience: str) -> str:
    """The run's GitHub OIDC token, which proves to a Worker that the call comes from this repo on main."""
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(audience, safe="")
    return get_json(url, headers={"Authorization": f"Bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"})["value"]
