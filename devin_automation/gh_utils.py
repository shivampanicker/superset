"""Minimal GitHub REST helpers used by the automation.

Uses requests + a token from the environment (GITHUB_TOKEN in Actions, or
`GH_TOKEN=$(gh auth token)` locally). Only the few endpoints we need.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import requests

from . import config

_SESSION = requests.Session()


def _headers() -> dict[str, str]:
    if not config.GITHUB_TOKEN:
        raise RuntimeError("No GitHub token (set GITHUB_TOKEN or GH_TOKEN).")
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _url(path: str, repo: Optional[str] = None) -> str:
    return f"{config.GITHUB_API}/repos/{repo or config.REPO}{path}"


def _check(resp: requests.Response) -> Any:
    if resp.status_code >= 300:
        raise RuntimeError(f"GitHub {resp.request.method} {resp.url} "
                           f"-> {resp.status_code}: {resp.text}")
    return resp.json() if resp.text else {}


def get_issue(number: int, repo: Optional[str] = None) -> dict[str, Any]:
    return _check(_SESSION.get(_url(f"/issues/{number}", repo), headers=_headers(),
                               timeout=30))


def list_issues_by_label(label: str, repo: Optional[str] = None) -> list[dict[str, Any]]:
    """All open issues carrying `label` (PRs are filtered out)."""
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = _SESSION.get(
            _url("/issues", repo), headers=_headers(),
            params={"labels": label, "state": "open", "per_page": 100, "page": page},
            timeout=30,
        )
        batch = _check(resp)
        out.extend(i for i in batch if "pull_request" not in i)
        if len(batch) < 100:
            break
        page += 1
    return out


def list_issues_with_any_label(labels: list[str], repo: Optional[str] = None) -> list[dict[str, Any]]:
    """Open OR closed issues carrying any of `labels`, de-duplicated by number."""
    seen: dict[int, dict[str, Any]] = {}
    for lbl in labels:
        page = 1
        while True:
            resp = _SESSION.get(
                _url("/issues", repo), headers=_headers(),
                params={"labels": lbl, "state": "all", "per_page": 100, "page": page},
                timeout=30,
            )
            batch = _check(resp)
            for i in batch:
                if "pull_request" not in i:
                    seen[i["number"]] = i
            if len(batch) < 100:
                break
            page += 1
    return list(seen.values())


def add_comment(number: int, body: str, repo: Optional[str] = None) -> dict[str, Any]:
    return _check(_SESSION.post(_url(f"/issues/{number}/comments", repo),
                                headers=_headers(), json={"body": body}, timeout=30))


def list_comments(number: int, repo: Optional[str] = None) -> list[dict[str, Any]]:
    return _check(_SESSION.get(_url(f"/issues/{number}/comments", repo),
                               headers=_headers(), params={"per_page": 100}, timeout=30))


def add_labels(number: int, labels: list[str], repo: Optional[str] = None) -> None:
    _check(_SESSION.post(_url(f"/issues/{number}/labels", repo),
                         headers=_headers(), json={"labels": labels}, timeout=30))


def remove_label(number: int, label: str, repo: Optional[str] = None) -> None:
    resp = _SESSION.delete(_url(f"/issues/{number}/labels/{label}", repo),
                           headers=_headers(), timeout=30)
    if resp.status_code not in (200, 404):  # 404 = label already absent
        _check(resp)


def set_lifecycle(number: int, target: str, repo: Optional[str] = None) -> None:
    """Move an issue to exactly one lifecycle label, clearing the others."""
    for lbl in config.LIFECYCLE_LABELS:
        if lbl != target:
            remove_label(number, lbl, repo)
    add_labels(number, [target], repo)


# --- session-marker helpers -------------------------------------------------
_MARKER_RE = re.compile(r"<!--\s*" + config.SESSION_MARKER + r":([^|]+)\|([^>]*?)\s*-->")


def session_marker(session_id: str, url: str) -> str:
    return f"<!-- {config.SESSION_MARKER}:{session_id}|{url} -->"


def extract_session(comments: list[dict[str, Any]]) -> Optional[tuple[str, str]]:
    """Return (session_id, url) from the most recent tracking comment, if any."""
    for c in reversed(comments):
        m = _MARKER_RE.search(c.get("body", ""))
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None
