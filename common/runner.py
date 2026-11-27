"""Run one job of a Worker: claim it, ask what to fetch, fetch it here, post the answers back.

Some providers refuse Cloudflare, so a Worker hands their part to GitHub Actions. Each provider package
(binance/, bls/) passes its sources module to ``main``; the Worker decides everything else.

Usage (a provider's __main__, in its workflow):
    python -m <provider> [--core URL]   # default: env CORE_URL; no JOB: claims a new job with the run's OIDC
                                        # token (skipped when the Worker says so)
    JOB=<id> python -m <provider>       # a job the Worker made: claims that job
    python -m <provider> --preview      # asks the Worker for a preview job (OIDC too)

The run proves itself with its GitHub OIDC token, whose audience is the Worker's URL. This repo and its run
logs are public: stdout gets counts only. The full log goes to the Worker with the result and is kept there.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

from . import http


class SourceError(Exception):
    pass


def first_ok(attempts):
    """Run callables in order, return the first success; raise with all errors."""
    errors = []
    for name, fn in attempts:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {e}")
    raise SourceError(" | ".join(errors))


def fetch_all(sources: ModuleType, requests: dict, log=print) -> dict:
    """{id: {source, params}} -> {"prices": {id: {key: number}}, "errors": {id: message}, "notes": [...]}

    ``sources.SOURCES`` maps a source name to ``fn(**params) -> dict``; a module with ``NOTE`` gets it set to a
    hook that collects notes for the Worker."""
    out = {"prices": {}, "errors": {}, "notes": []}

    def one(item):
        aid, req = item
        fn = sources.SOURCES.get(req.get("source"))
        try:
            if not fn:
                raise SourceError(f"unknown source {req.get('source')!r}")
            return aid, fn(**(req.get("params") or {})), None
        except Exception as e:  # noqa: BLE001
            return aid, None, f"{type(e).__name__}: {e}"[:300]

    def note(n):
        out["notes"].append(n)
        log(f"NOTE {n['kind']}: {n.get('summary', '')}")
    if hasattr(sources, "NOTE"):
        sources.NOTE = note
    with ThreadPoolExecutor(max_workers=8) as pool:
        for aid, got, err in pool.map(one, requests.items()):
            if err:
                out["errors"][aid] = err
                log(f"[{aid}] ERROR: {err}")
            else:
                out["prices"][aid] = got
                log(f"[{aid}] {got}")
    return out


def skipped(err: urllib.error.HTTPError) -> bool:
    """True when the Worker refused the claim with code "skip"."""
    try:
        return json.loads(err.read()).get("code") == "skip"
    except (ValueError, AttributeError):
        return False


def main(sources: ModuleType, argv=None) -> int:
    default = os.environ.get("CORE_URL", "")  # the Worker's address: a repository variable, never in this repo
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default=default, required=not default)
    ap.add_argument("--preview", action="store_true", help="open a preview job on the Worker and run it")
    args = ap.parse_args(argv)
    core = http.base_url(args.core)
    if not core:
        print("::error::CORE_URL must look like https://worker.example.com")
        return 1
    claim = http.auth(core, http.oidc_token(core))
    if args.preview:
        j = http.post_json(f"{core}/runner/preview", {}, headers=claim)
    else:  # the token is not in the (public) inputs: claim it with the run's OIDC token, once per job
        try:
            j = http.post_json(f"{core}/runner/claim", {"job": os.environ.get("JOB", "")}, headers=claim)
        except urllib.error.HTTPError as e:
            if e.code == 409 and skipped(e):
                print("Skipped: the Worker has nothing for this run")
                return 0
            raise
    headers = http.auth(core, f"{j['id']}.{j['token']}")
    job = http.get_json(f"{core}/runner/job", headers=headers)
    print(f"Job {job['id']} ({job['mode']}): {len(job['requests'])} requests")
    lines = []
    result = fetch_all(sources, job["requests"], log=lines.append)  # full log to the Worker only
    print(f"{len(result['prices'])} answers, {len(result['errors'])} errors")
    # the Worker may do more work before it answers: allow it some time
    r = http.post_json(f"{core}/runner/result", {**result, "log": "\n".join(lines)}, headers=headers, timeout=120)
    print(f"Worker: code {r.get('code')}")
    return 0 if r.get("code") == 0 else 1


if __name__ == "__main__":
    sys.exit("run a provider package instead, e.g. python -m binance")
