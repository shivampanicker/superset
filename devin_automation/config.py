"""Centralised configuration + shared constants for the Devin automation.

Everything is driven by environment variables so the same code runs unchanged
locally (export the vars) and inside GitHub Actions (provided by the runner /
repo secrets).
"""

from __future__ import annotations

import os

# --- GitHub -----------------------------------------------------------------
GITHUB_API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
# In Actions this is "owner/repo"; locally pass --repo or set GITHUB_REPOSITORY.
REPO = os.environ.get("GITHUB_REPOSITORY", "shivampanicker/superset")
# GITHUB_TOKEN is injected by Actions; locally use `GH_TOKEN=$(gh auth token)`.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")

# --- Devin ------------------------------------------------------------------
DEVIN_BASE = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai/v1")
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")
# Cap each session's compute so a runaway task can't burn unbounded ACUs.
DEVIN_MAX_ACU = int(os.environ.get("DEVIN_MAX_ACU", "10"))
# When truthy, devin_client returns canned responses instead of calling the API.
DEVIN_MOCK = os.environ.get("DEVIN_MOCK", "").lower() in ("1", "true", "yes")

# --- Lifecycle labels (GitHub is the state store) ---------------------------
LABEL_TRIGGER = "devin-fix"
LABEL_WORKING = "devin-working"
LABEL_DONE = "devin-done"
LABEL_BLOCKED = "devin-blocked"
CATEGORY_LABELS = {"dependencies", "security", "code-quality"}
LIFECYCLE_LABELS = [LABEL_TRIGGER, LABEL_WORKING, LABEL_DONE, LABEL_BLOCKED]

# Machine-readable marker embedded in the tracking comment so poll/report can
# recover the Devin session id (and URL) from an issue without a side database.
SESSION_MARKER = "devin-session"  # rendered as <!-- devin-session:<id>|<url> -->
