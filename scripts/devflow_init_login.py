"""Interactive login that writes ~/.devflow/cloud-credentials.json (0600).

Prompts for the DevFlow Portal URL and an API key, smokes the connection
against GET /v1/healthz, then persists the credentials. Healthz is
unauthenticated by design: this validates URL + reachability only. A
malformed key surfaces on the first authenticated call (401).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import IO

import httpx

CREDS_PATH = Path.home() / ".devflow" / "cloud-credentials.json"
DEFAULT_URL = "https://devflow.vinicius.xyz"


def _prompt(prompt: str, stdin: IO[str]) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = stdin.readline()
    if not line:
        raise SystemExit("aborted")
    return line.strip()


def login(*, stdin: IO[str] | None = None) -> None:
    src = stdin if stdin is not None else sys.stdin
    url = _prompt(f"DevFlow URL [{DEFAULT_URL}]: ", src) or DEFAULT_URL
    url = url.rstrip("/")
    key = _prompt("API key: ", src)
    if not key:
        raise SystemExit("api key is required")

    try:
        r = httpx.get(
            f"{url}/v1/healthz",
            headers={"X-DevFlow-Key": key},
            timeout=10.0,
        )
        r.raise_for_status()
    except Exception as e:
        raise SystemExit(f"smoke test failed: {e}")

    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"remote_url": url, "api_key": key}
    CREDS_PATH.write_text(json.dumps(payload, indent=2))
    os.chmod(CREDS_PATH, 0o600)
    print(f"wrote {CREDS_PATH}")


if __name__ == "__main__":
    login()
