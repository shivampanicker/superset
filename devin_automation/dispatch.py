"""Dispatch: an issue was labeled `devin-fix` -> start a Devin remediation session.

Triggered by the `devin-remediate` workflow (issues: [labeled]) or run manually:

    GH_TOKEN=$(gh auth token) python -m devin_automation.dispatch --issue 1

Steps:
    1. read the issue,
    2. build a precise remediation prompt,
    3. create a Devin session (idempotent, ACU-capped, structured output),
    4. post a tracking comment carrying the session id + URL,
    5. move the issue to the `devin-working` lifecycle label.
"""

from __future__ import annotations

import argparse
import sys

from . import config, devin_client, gh_utils

# Schema we ask Devin to return so poll/report get clean machine-readable data.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "pr_url": {"type": "string", "description": "URL of the opened pull request"},
        "summary": {"type": "string", "description": "What was changed and why"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}


def build_prompt(issue: dict, repo: str) -> str:
    number = issue["number"]
    title = issue["title"]
    body = (issue.get("body") or "").strip()
    return f"""You are remediating a code issue in the GitHub repository `{repo}`.

# Issue #{number}: {title}

{body}

# Your task
1. Clone `{repo}` (default branch) and create a new branch named `devin/issue-{number}-fix`.
2. Implement ONLY the change described in the issue above. Do not refactor or
   reformat unrelated code.
3. Run the relevant linters/tests for the files you touch and make sure they pass
   (use `pre-commit run --files <changed files>` and the pytest paths named in the
   issue's acceptance criteria). Fix anything your change broke.
4. Commit with a clear message and open a pull request **against `{repo}`**.
   The PR description MUST contain the line `Closes #{number}` so the issue is
   linked and auto-closed on merge.
5. When finished, return the structured output: the opened PR url (`pr_url`), a
   short `summary`, and the list of `files_changed`.

If the change cannot be made safely (e.g. it would break behavior and you cannot
resolve it), stop and explain the blocker in your summary instead of opening a PR.
"""


def dispatch_issue(number: int, repo: str | None = None) -> dict:
    repo = repo or config.REPO
    issue = gh_utils.get_issue(number, repo)
    labels = {lbl["name"] for lbl in issue.get("labels", [])}
    if config.LABEL_WORKING in labels:
        print(f"[dispatch] issue #{number} already {config.LABEL_WORKING}; skipping.")
        return {"skipped": True}

    prompt = build_prompt(issue, repo)
    session = devin_client.create_session(
        prompt,
        title=f"Remediate #{number}: {issue['title'][:80]}",
        tags=[config.LABEL_TRIGGER, f"issue-{number}", f"repo-{repo}"],
        idempotent=True,
        structured_output_schema=OUTPUT_SCHEMA,
    )
    sid = session["session_id"]
    url = session.get("url", "")
    print(f"[dispatch] issue #{number} -> session {sid} ({url})")

    comment = (
        f"🤖 **Devin remediation started.**\n\n"
        f"- Session: [`{sid}`]({url})\n"
        f"- Triggered by label `{config.LABEL_TRIGGER}`\n"
        f"- Devin will open a PR with `Closes #{number}` when finished.\n\n"
        f"{gh_utils.session_marker(sid, url)}"
    )
    gh_utils.add_comment(number, comment, repo)
    gh_utils.set_lifecycle(number, config.LABEL_WORKING, repo)
    return {"session_id": sid, "url": url}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dispatch a Devin session for an issue.")
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--repo", default=None)
    args = ap.parse_args(argv)
    try:
        dispatch_issue(args.issue, args.repo)
    except Exception as exc:  # surface a clean failure in the Actions log
        print(f"[dispatch] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
