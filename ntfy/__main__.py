"""Send the family service's queued ntfy notes (ntfy.sh refuses Cloudflare's shared addresses, so the service
starts the workflow ntfy.yml instead).

Usage (in the workflow):
    JOB=<id> SERVICE_URL=https://service.example.com python -m ntfy

The run proves itself with its GitHub OIDC token (this repo, main, this workflow), claims the job, takes the
notes, sends them to ntfy.sh and reports which arrived. The log is public: it prints counts only, never a topic
or a note's text.
"""
from __future__ import annotations

import os
import re
import sys
import time

from common import http

NTFY = "https://ntfy.sh/"


def send(note: dict) -> bool:
    payload = {"topic": note["topic"], "title": note["title"], "message": note["text"]}
    if note.get("link"):
        payload["click"] = note["link"]
    for attempt in range(2):
        try:
            http.post_json(NTFY, payload, timeout=15)
            return True
        except Exception as e:  # noqa: BLE001 (no message: it could carry the topic)
            print(f"  a send failed: {type(e).__name__} {getattr(e, 'code', '')}")
            if attempt == 0:
                time.sleep(3)
    return False


def main() -> int:
    job = os.environ.get("JOB", "")
    service = http.base_url(os.environ.get("SERVICE_URL", ""))
    if not re.fullmatch(r"[\w-]{1,64}", job) or not service:
        print("::error::bad job id or SERVICE_URL")
        return 1

    def call(path: str, body: dict, token: str) -> dict:
        return http.post_json(f"{service}{path}", body, headers=http.auth(service, token), timeout=30)

    # The run's OIDC token (audience service-push), then the job's key: once per job, once per token.
    try:
        claim = call("/push/claim", {"job": job}, http.oidc_token("service-push"))
    except Exception as e:  # noqa: BLE001
        print(f"claim refused: {type(e).__name__} {getattr(e, 'code', '')}")
        return 1
    key = f"{claim['id']}.{claim['token']}"

    arrived_total = failed_total = 0
    for round_ in range(40):  # one run drains the queue: notes come in rounds until none is left
        notes = call("/push/notes", {}, key)["notes"]
        if not notes:
            break
        arrived, failed = [], []
        for n in notes:
            (arrived if send(n) else failed).append(n["id"])
        call("/push/report", {"arrived": arrived, "failed": failed}, key)
        arrived_total += len(arrived)
        failed_total += len(failed)
        print(f"round {round_ + 1}: {len(arrived)} arrived, {len(failed)} failed")
    print(f"done: {arrived_total} arrived, {failed_total} failed")
    return 1 if failed_total else 0


if __name__ == "__main__":
    sys.exit(main())
