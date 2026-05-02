"""Verdict-JSON extraction from Claude CLI subprocess stdout.

Three-layer parser that tolerates:
  - Clean verdict JSON (legacy callers + unit tests that pass raw model JSON)
  - CLI envelope: {"type":"result", "result": "...", ...}
  - Inner payload wrapped in markdown fences (```json ... ```)
  - Prose before or after the JSON (model hallucinated a preamble/postamble)

Returns None only when every layer fails — callers treat that as parse_fail
and can retry or record forensics.
"""
from __future__ import annotations

import json
import re


def find_balanced_json(s: str) -> str | None:
    """Return the first balanced top-level {...} block in s, or None.

    Scans character by character, tracking brace depth and string state
    (including escaped quotes) so braces inside JSON string values do not
    confuse the depth counter. Used as the last parser fallback when the
    model emits prose around the JSON.
    """
    start = None
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    return s[start:i + 1]
    return None


def extract_verdict_dict(stdout: str) -> dict | None:
    """Three-layer extraction of the verdict JSON from subprocess stdout.

    L1: parse stdout as JSON. If it's the CLI envelope
        ({"type": "result", "result": "...", ...}), take `.result` as the
        inner payload. If it's already a verdict-shaped dict, return it.
    L2: strip leading/trailing markdown fence (``` or ```json ... ```)
        from the inner payload and retry json.loads.
    L3: balanced-brace scan on the inner payload to pull out the first
        top-level {...} block and parse that.
    """
    if not stdout or not stdout.strip():
        return None

    inner: str = stdout

    # L1: envelope unwrap or direct-verdict shortcut
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        if parsed.get("type") == "result" and "result" in parsed:
            inner = str(parsed.get("result") or "")
        else:
            return parsed

    if not inner or not inner.strip():
        return None

    # L2: fence strip
    stripped = re.sub(r"^```(?:json)?\s*", "", inner.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # L3: balanced-brace scan
    block = find_balanced_json(inner)
    if block is not None:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None


def envelope_inner(stdout: str) -> str:
    """Return the inner `.result` string if stdout is an envelope, else stdout.

    Used by the evaluator to preserve the *model's* raw JSON string on
    `raw_response` rather than the CLI envelope wrapper.
    """
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return stdout
    if (
        isinstance(parsed, dict)
        and parsed.get("type") == "result"
        and "result" in parsed
    ):
        return str(parsed.get("result") or stdout)
    return stdout
