"""Report: join issues + Devin sessions into observability metrics.

Answers "how would an engineering leader know this is working?" by emitting:
    - a metrics summary + per-issue table to the Actions job summary
      ($GITHUB_STEP_SUMMARY) and stdout,
    - REPORT.md   (durable, linkable markdown artifact committed to the repo),
    - report.json (structured data for any downstream tooling).

State is derived entirely from GitHub: lifecycle labels give status, and the
tracking/PR comments give session ids, PR links, and timestamps for throughput.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Optional

from . import config, gh_utils

_PR_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")


def _status_from_labels(labels: set[str]) -> str:
    for lbl in (config.LABEL_DONE, config.LABEL_BLOCKED,
                config.LABEL_WORKING, config.LABEL_TRIGGER):
        if lbl in labels:
            return lbl
    return "untracked"


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _collect(repo: str) -> list[dict[str, Any]]:
    issues = gh_utils.list_issues_with_any_label(
        config.LIFECYCLE_LABELS + sorted(config.CATEGORY_LABELS), repo
    )
    rows: list[dict[str, Any]] = []
    for issue in issues:
        number = issue["number"]
        labels = {lbl["name"] for lbl in issue.get("labels", [])}
        status = _status_from_labels(labels)
        category = next((c for c in config.CATEGORY_LABELS if c in labels), "-")

        session_id = session_url = pr = None
        dispatched_at = finished_at = None
        comments = gh_utils.list_comments(number, repo)
        marker = gh_utils.extract_session(comments)
        if marker:
            session_id, session_url = marker
        for c in comments:
            body = c.get("body", "")
            # latest session-start marker = when the winning session was dispatched
            if config.SESSION_MARKER in body:
                dispatched_at = _parse_ts(c.get("created_at"))
            # first comment carrying a real PR url = the PR-opened event
            m = _PR_RE.search(body)
            if m and pr is None:
                pr = m.group(0)
                finished_at = _parse_ts(c.get("created_at"))

        ttp = None
        if dispatched_at and finished_at:
            ttp = round((finished_at - dispatched_at).total_seconds() / 60.0, 1)

        rows.append({
            "number": number,
            "title": issue["title"],
            "category": category,
            "status": status,
            "session_id": session_id,
            "session_url": session_url,
            "pr_url": pr,
            "time_to_pr_min": ttp,
        })
    return sorted(rows, key=lambda r: r["number"])


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    done = by_status.get(config.LABEL_DONE, 0)
    blocked = by_status.get(config.LABEL_BLOCKED, 0)
    working = by_status.get(config.LABEL_WORKING, 0)
    queued = by_status.get(config.LABEL_TRIGGER, 0)
    dispatched = sum(1 for r in rows if r["session_id"])
    terminal = done + blocked
    prs = [r for r in rows if r["pr_url"]]
    ttps = [r["time_to_pr_min"] for r in rows if r["time_to_pr_min"] is not None]
    return {
        "total_tracked": len(rows),
        "queued": queued,
        "working": working,
        "done": done,
        "blocked": blocked,
        "sessions_dispatched": dispatched,
        "prs_opened": len(prs),
        "success_rate_pct": round(100 * done / terminal, 1) if terminal else None,
        "avg_time_to_pr_min": round(sum(ttps) / len(ttps), 1) if ttps else None,
    }


def _emoji(status: str) -> str:
    return {config.LABEL_DONE: "✅", config.LABEL_BLOCKED: "⛔",
            config.LABEL_WORKING: "⏳", config.LABEL_TRIGGER: "🆕"}.get(status, "•")


def render_markdown(rows, m, repo) -> str:
    sr = f"{m['success_rate_pct']}%" if m["success_rate_pct"] is not None else "n/a"
    avg = f"{m['avg_time_to_pr_min']} min" if m["avg_time_to_pr_min"] is not None else "n/a"
    lines = [
        f"# 🤖 Devin Remediation Report — `{repo}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Issues tracked | **{m['total_tracked']}** |",
        f"| 🆕 Queued (`devin-fix`) | {m['queued']} |",
        f"| ⏳ Working | {m['working']} |",
        f"| ✅ Done (PR opened) | {m['done']} |",
        f"| ⛔ Blocked | {m['blocked']} |",
        f"| Sessions dispatched | {m['sessions_dispatched']} |",
        f"| PRs opened | {m['prs_opened']} |",
        f"| **Success rate** (done / terminal) | **{sr}** |",
        f"| Avg time issue→PR | {avg} |",
        "",
        "## Per-issue status",
        "",
        "| # | Issue | Category | Status | Session | PR | Time→PR |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        link = f"[#{r['number']}](https://github.com/{repo}/issues/{r['number']})"
        sess = f"[session]({r['session_url']})" if r["session_url"] else "—"
        pr = f"[PR]({r['pr_url']})" if r["pr_url"] else "—"
        ttp = f"{r['time_to_pr_min']} min" if r["time_to_pr_min"] is not None else "—"
        title = r["title"] if len(r["title"]) <= 60 else r["title"][:57] + "…"
        lines.append(
            f"| {link} | {title} | {r['category']} | "
            f"{_emoji(r['status'])} {r['status']} | {sess} | {pr} | {ttp} |"
        )
    lines += ["", "_Generated by `devin_automation.report`. "
              "State is derived from GitHub issue labels + comments._"]
    return "\n".join(lines)


def generate(repo: str | None = None) -> dict[str, Any]:
    repo = repo or config.REPO
    rows = _collect(repo)
    m = _metrics(rows)
    md = render_markdown(rows, m, repo)

    print(md)
    payload = {"repo": repo, "metrics": m, "issues": rows}

    # durable artifacts (written into the repo working dir)
    with open("REPORT.md", "w", encoding="utf-8") as fh:
        fh.write(md + "\n")
    with open("report.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    # Actions job summary
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return payload


if __name__ == "__main__":
    generate()
