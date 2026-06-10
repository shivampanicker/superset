"""Thin client for the Devin v1 API.

Endpoints used (https://docs.devin.ai/api-reference):
    POST /v1/sessions            -> create a session         -> {session_id, url}
    GET  /v1/sessions/{id}       -> session detail/status     -> {status_enum, pull_request, structured_output, ...}

Set DEVIN_MOCK=1 to exercise the whole pipeline without spending ACUs; the mock
returns deterministic responses (override the reported status with
DEVIN_MOCK_STATUS and the PR url with DEVIN_MOCK_PR).
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests

from . import config

TERMINAL_OK = {"finished", "resumed"}
TERMINAL_BAD = {"blocked", "expired"}


class DevinError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not config.DEVIN_API_KEY:
        raise DevinError("DEVIN_API_KEY is not set (and DEVIN_MOCK is off).")
    return {
        "Authorization": f"Bearer {config.DEVIN_API_KEY}",
        "Content-Type": "application/json",
    }


def create_session(
    prompt: str,
    *,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    idempotent: bool = True,
    structured_output_schema: Optional[dict[str, Any]] = None,
    session_secrets: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Create a Devin session and return at least {session_id, url}."""
    if config.DEVIN_MOCK:
        return _mock_create(prompt, title, tags)

    body: dict[str, Any] = {
        "prompt": prompt,
        "idempotent": idempotent,
        "max_acu_limit": config.DEVIN_MAX_ACU,
    }
    if title:
        body["title"] = title
    if tags:
        body["tags"] = tags
    if structured_output_schema:
        body["structured_output_schema"] = structured_output_schema
    if session_secrets:
        body["session_secrets"] = session_secrets

    resp = requests.post(
        f"{config.DEVIN_BASE}/sessions", headers=_headers(), json=body, timeout=60
    )
    if resp.status_code >= 300:
        raise DevinError(f"create_session failed {resp.status_code}: {resp.text}")
    return resp.json()


def get_session(session_id: str) -> dict[str, Any]:
    """Fetch session detail. Returns the raw Devin payload."""
    if config.DEVIN_MOCK:
        return _mock_get(session_id)

    resp = requests.get(
        f"{config.DEVIN_BASE}/sessions/{session_id}", headers=_headers(), timeout=60
    )
    if resp.status_code >= 300:
        raise DevinError(f"get_session failed {resp.status_code}: {resp.text}")
    return resp.json()


def pr_url(session: dict[str, Any]) -> Optional[str]:
    """Extract the PR url from a session payload, tolerating shape variations."""
    pr = session.get("pull_request")
    if isinstance(pr, dict):
        return pr.get("url")
    if isinstance(pr, str):
        return pr
    out = session.get("structured_output")
    if isinstance(out, dict):
        return out.get("pr_url") or out.get("pull_request_url")
    return None


# --- Mock -------------------------------------------------------------------
def _mock_create(prompt, title, tags) -> dict[str, Any]:
    issue = "x"
    for t in tags or []:
        if t.startswith("issue-"):
            issue = t.split("-", 1)[1]
    sid = f"devin-mock-{issue}"
    return {"session_id": sid, "url": f"https://app.devin.ai/sessions/{sid}",
            "is_new_session": True}


def _mock_get(session_id: str) -> dict[str, Any]:
    status = os.environ.get("DEVIN_MOCK_STATUS", "finished")
    issue = session_id.rsplit("-", 1)[-1]
    out: dict[str, Any] = {
        "session_id": session_id,
        "status_enum": status,
        "created_at": "2026-06-10T00:00:00Z",
        "updated_at": "2026-06-10T00:05:00Z",
        "structured_output": {
            "summary": "Replaced deprecated datetime.utcnow() with datetime.now(timezone.utc).",
            "files_changed": ["superset/utils/dates.py", "superset/utils/cache.py"],
        },
    }
    if status in TERMINAL_OK:
        pr = os.environ.get(
            "DEVIN_MOCK_PR", f"https://github.com/{config.REPO}/pull/{issue}00"
        )
        out["pull_request"] = {"url": pr}
    elif status in TERMINAL_BAD:
        out["structured_output"]["summary"] = "Blocked: could not determine safe fix."
    return out


if __name__ == "__main__":  # tiny manual smoke test
    s = create_session("hello", title="t", tags=["issue-1"])
    print(json.dumps(s, indent=2))
    print(json.dumps(get_session(s["session_id"]), indent=2))
