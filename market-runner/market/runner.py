"""Fetch the Binance prices of one job for the Cloudflare Worker (cloudflare/core.js).

Binance blocks Cloudflare, so the Worker hands this part to GitHub Actions: it asks for the job,
fetches the prices here and posts them back. The Worker does the rest (other sources, thresholds,
saving) and hands back the pushes, which go out from here because ntfy.sh limits messages per
sender IP and Cloudflare's IPs are shared; the runner then reports which ones arrived.

Usage (in the workflow):
    JOB=<id> python -m market.runner [--core URL]  # default: env CORE_URL; claims the job with the run's OIDC token
    python -m market.runner --preview          # test push of current prices, started on GitHub (OIDC too)

This repo and its run logs are public: stdout gets counts only. The full log (prices, push titles) goes to the
Worker with the result and is kept there. The morning brief does not use this repo: it calls the Worker directly.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import http, sources

# The Worker's address is not kept in this public repo: it comes from the repository variable CORE_URL.
DEFAULT_CORE = os.environ.get("CORE_URL", "")


def fetch_all(requests: dict, log=print) -> dict:
    """{id: {source, params}} -> {"prices": {id: {side: price}}, "errors": {id: message}, "notes": [...]}"""
    def one(item):
        aid, req = item
        try:
            return aid, sources.fetch(req["source"], req.get("params") or {}), None
        except Exception as e:  # noqa: BLE001
            return aid, None, f"{type(e).__name__}: {e}"[:300]

    out = {"prices": {}, "errors": {}, "notes": []}

    def note(n):  # lone P2P ads: kept by the Worker in D1 table notes
        out["notes"].append(n)
        log(f"NOTE {n['kind']}: {n.get('summary', '')}")
    sources.NOTE = note
    with ThreadPoolExecutor(max_workers=8) as pool:
        for aid, prices, err in pool.map(one, requests.items()):
            if err:
                out["errors"][aid] = err
                log(f"[{aid}] ERROR: {err}")
            else:
                out["prices"][aid] = prices
                log(f"[{aid}] {prices}")
    return out


def send_pushes(target: dict, pushes: list, log=print) -> list:
    """Send each push to ntfy (one retry); returns [{"ok", "error"}] in order."""
    headers = {"Authorization": f"Bearer {target['token']}"} if target.get("token") else {}
    out = []
    for p in pushes:
        payload = {"topic": target["topic"], "message": p["message"], "priority": p.get("priority", 4),
                   "tags": p.get("tags") or []}
        if p.get("title"):
            payload["title"] = p["title"]
        err = None
        for attempt in range(2):
            try:
                if not target.get("topic"):
                    raise ValueError("no ntfy topic")
                http.post_json(target["url"], payload, headers=headers)
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"[:300]
                if attempt == 0:
                    time.sleep(3)
        log(f"push {len(out) + 1}/{len(pushes)}: {'sent' if not err else 'FAILED: ' + err}")  # no text: public log
        out.append({"ok": err is None, "error": err or ""})
    return out


def deliver(core: str, headers: dict, reply: dict) -> int:
    """Send the pushes the Worker handed back and report the outcome; returns the job's exit code."""
    if not reply.get("pushes"):
        return 0 if reply.get("code") == 0 else 1
    sent = send_pushes(reply["ntfy"], reply["pushes"])
    r = http.post_json(f"{core}/runner/delivered", {"sent": sent}, headers=headers, timeout=60)
    print(f"Worker: code {r.get('code')}")
    return 0 if r.get("code") == 0 else 1


def oidc_headers() -> dict:
    """The run's GitHub OIDC token, which proves to the Worker that the call comes from this repo on main."""
    req = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=market-cron"
    tok = http.get_json(req, headers={"Authorization": f"Bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"})["value"]
    return {"Authorization": f"Bearer {tok}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default=DEFAULT_CORE, required=not DEFAULT_CORE)
    ap.add_argument("--preview", action="store_true", help="open a preview job on the Worker and run it")
    args = ap.parse_args(argv)
    core = args.core.rstrip("/")
    if args.preview:
        j = http.post_json(f"{core}/runner/preview", {}, headers=oidc_headers())
        job_id, token = j["id"], j["token"]
    else:  # the token is not in the (public) inputs: claim it with the run's OIDC token, once per job
        j = http.post_json(f"{core}/runner/claim", {"job": os.environ["JOB"]}, headers=oidc_headers())
        job_id, token = j["id"], j["token"]
    headers = {"Authorization": f"Bearer {job_id}.{token}"}
    if os.environ.get("GITHUB_RUN_ID"):
        headers["X-Run-Url"] = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                                f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    job = http.get_json(f"{core}/runner/job", headers=headers)
    print(f"Job {job['id']} ({job['mode']}): {len(job['requests'])} assets")
    lines = []
    result = fetch_all(job["requests"], log=lines.append)  # full log to the Worker only
    print(f"{len(result['prices'])} prices, {len(result['errors'])} errors")
    # the Worker now fetches the other sources, checks, notifies and saves: allow it some time
    r = http.post_json(f"{core}/runner/result", {**result, "log": "\n".join(lines)}, headers=headers, timeout=120)
    return deliver(core, headers, r)


if __name__ == "__main__":
    sys.exit(main())
