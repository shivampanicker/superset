# Event-Driven Devin Remediation Pipeline

An automation that turns **GitHub issues into merged-ready pull requests** using the
[Devin API](https://docs.devin.ai/api-reference). Label an issue `devin-fix`, and a
Devin session is launched to fix it, open a PR, and report back — with a live
observability report for engineering leadership.

> Built on a fork of [`apache/superset`](https://github.com/apache/superset). Issues,
> sessions, and PRs all live in this fork; upstream is never touched.

## Architecture

```
                         ┌──────────────────────────────────────────────┐
   label issue           │  GitHub Actions: devin-remediate.yml          │
   `devin-fix`  ───────► │  (on: issues[labeled] / workflow_dispatch)    │
                         │    └─ devin_automation.dispatch               │
                         │         • build prompt from the issue         │
                         │         • POST /v1/sessions  (Devin)          │
                         │         • comment session URL + marker        │
                         │         • relabel  devin-fix → devin-working  │
                         └──────────────────────────────────────────────┘
                                              │  Devin works, opens a PR
                                              ▼
                         ┌──────────────────────────────────────────────┐
   every 15 min  ──────► │  GitHub Actions: devin-poll.yml               │
   (+ on demand)         │  (on: schedule / workflow_dispatch)           │
                         │    └─ devin_automation.poll                   │
                         │         • GET /v1/sessions/{id}  (Devin)      │
                         │         • finished+PR → devin-done (link PR)  │
                         │         • blocked     → devin-blocked         │
                         │    └─ devin_automation.report                 │
                         │         • REPORT.md + report.json + job summary│
                         └──────────────────────────────────────────────┘
```

**GitHub is the state store.** No database: the issue's lifecycle label is its
status, and a hidden marker in the tracking comment (`<!-- devin-session:<id>|<url> -->`)
lets any run recover the Devin session id.

| Label | Meaning |
|---|---|
| `devin-fix` | Queued — labeling this **triggers** remediation |
| `devin-working` | Devin session in flight |
| `devin-done` | Devin opened a PR (`Closes #N`) |
| `devin-blocked` | Session blocked/failed without a PR |

## Components (`devin_automation/`)

| File | Role |
|---|---|
| `config.py` | Env-driven config + label/marker constants |
| `devin_client.py` | Devin v1 client (`create_session`, `get_session`) + `DEVIN_MOCK` |
| `gh_utils.py` | GitHub REST helpers (issues, labels, comments, marker parsing) |
| `dispatch.py` | Issue → Devin session (the event handler) |
| `poll.py` | Session → label/PR updates (the observability loop) |
| `report.py` | Metrics → `REPORT.md`, `report.json`, Actions job summary |

## Setup

1. **Secret:** add `DEVIN_API_KEY` (a Devin `apk_*` service key) under
   *repo → Settings → Secrets and variables → Actions*. `GITHUB_TOKEN` is provided
   automatically.
2. **Connect Devin to GitHub** (app.devin.ai → Integrations) so Devin can push to
   this fork and open PRs.
3. Push this code to the fork (workflows live in `.github/workflows/`).

## Run it

**Event-driven (the real path):**
```bash
gh issue edit <N> --repo <owner>/superset --add-label devin-fix
```
…the `devin-remediate` workflow fires automatically.

**On demand:**
```bash
gh workflow run devin-remediate.yml -f issue=<N>   # dispatch one issue
gh workflow run devin-poll.yml                      # refresh status + report
```

**Locally (no Actions):**
```bash
export GH_TOKEN=$(gh auth token)
export GITHUB_REPOSITORY=<owner>/superset
export DEVIN_API_KEY=apk_...
python -m devin_automation.dispatch --issue <N>
python -m devin_automation.poll
```

**Mock mode (no ACUs, full pipeline):**
```bash
export DEVIN_MOCK=1                 # canned Devin responses
# DEVIN_MOCK_STATUS=blocked         # optionally force a status
python -m devin_automation.dispatch --issue <N>
python -m devin_automation.poll
```

## Observability — "how do I know it's working?"

Each poll run produces:
- **`REPORT.md`** (committed to the repo): metrics table + per-issue status, session
  links, PR links, time-to-PR — a durable, linkable artifact.
- **Actions job summary**: the same report rendered in the run's summary tab.
- **`report.json`**: structured metrics uploaded as a build artifact.

Metrics: issues tracked, queued/working/done/blocked counts, sessions dispatched,
PRs opened, **success rate** (done ÷ terminal), and **avg time issue→PR**.
