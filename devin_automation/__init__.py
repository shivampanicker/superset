"""Event-driven Devin remediation pipeline for this fork.

Modules:
    devin_client  - thin client for the Devin v1 API (real + mock).
    gh_utils      - GitHub REST helpers (issues, labels, comments).
    dispatch      - issue labeled `devin-fix` -> create a Devin session.
    poll          - poll active sessions -> update labels / link PRs.
    report        - join issues + sessions -> observability metrics.
"""

__all__ = ["devin_client", "gh_utils", "dispatch", "poll", "report", "config"]
