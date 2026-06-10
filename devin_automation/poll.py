"""Poll: advance every in-flight Devin session and update issue state.

Triggered by the `devin-poll` workflow (cron + manual) or run directly:

    GH_TOKEN=$(gh auth token) python -m devin_automation.poll

For each issue labeled `devin-working` it recovers the session id from the
tracking comment, asks Devin for status, and:
    finished + PR  -> comment the PR link, move to `devin-done`
    blocked/expired-> comment the blocker, move to `devin-blocked`
    otherwise      -> leave as `devin-working`
Then it regenerates the observability report.
"""

from __future__ import annotations

import sys

from . import config, devin_client, gh_utils, report


def poll_once(repo: str | None = None) -> list[dict]:
    repo = repo or config.REPO
    working = gh_utils.list_issues_by_label(config.LABEL_WORKING, repo)
    print(f"[poll] {len(working)} issue(s) in '{config.LABEL_WORKING}'")
    results = []

    for issue in working:
        number = issue["number"]
        found = gh_utils.extract_session(gh_utils.list_comments(number, repo))
        if not found:
            print(f"[poll] issue #{number}: no session marker; skipping")
            continue
        sid, _url = found
        try:
            session = devin_client.get_session(sid)
        except Exception as exc:
            print(f"[poll] issue #{number}: get_session({sid}) failed: {exc}")
            continue

        status = session.get("status_enum", "unknown")
        pr = devin_client.pr_url(session)
        print(f"[poll] issue #{number}: session {sid} status={status} pr={pr}")

        if status in devin_client.TERMINAL_OK and pr:
            gh_utils.add_comment(
                number,
                f"✅ **Devin finished.** Pull request: {pr}\n\n"
                f"Moving issue to `{config.LABEL_DONE}`.",
                repo,
            )
            gh_utils.set_lifecycle(number, config.LABEL_DONE, repo)
        elif status in devin_client.TERMINAL_BAD:
            out = session.get("structured_output") or {}
            reason = out.get("summary", "Session ended without a PR.")
            gh_utils.add_comment(
                number,
                f"⛔ **Devin blocked** (status `{status}`): {reason}\n\n"
                f"Moving issue to `{config.LABEL_BLOCKED}`.",
                repo,
            )
            gh_utils.set_lifecycle(number, config.LABEL_BLOCKED, repo)
        # else: still working -> leave untouched
        results.append({"issue": number, "status": status, "pr": pr})

    report.generate(repo)
    return results


def main(argv: list[str] | None = None) -> int:
    try:
        poll_once()
    except Exception as exc:
        print(f"[poll] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
