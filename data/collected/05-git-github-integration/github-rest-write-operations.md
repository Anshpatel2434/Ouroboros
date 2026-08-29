---
title: GitHub REST API Write Operations — Issues, PRs, Review Comments, Refs, Statuses, Check Runs
source_url: https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28
publisher: GitHub
retrieved: 2026-08-26
domain: git-github-integration
doc_type: official-docs
relevance: Ouroboros's backend opens issues, fix-up PRs, and PR review comments, creates quarantine branches via the refs API, and reports verdicts via commit statuses — these are the exact endpoints and payloads.
---

## Summary

Five REST write surfaces cover everything Ouroboros pushes back to GitHub: creating issues (`POST /repos/{owner}/{repo}/issues`), creating pull requests (`POST /repos/{owner}/{repo}/pulls`), attaching review comments to specific diff lines (`POST /repos/{owner}/{repo}/pulls/{pull_number}/comments`), creating branches through the low-level git refs API (`POST /repos/{owner}/{repo}/git/refs`), and reporting per-commit results via commit statuses (`POST /repos/{owner}/{repo}/statuses/{sha}`). Check runs offer richer per-line annotations but their write API is restricted to GitHub Apps, so a PAT-authenticated backend must use commit statuses instead. All content-creating endpoints are subject to secondary rate limits, so writes should be serialized with ≥1s spacing. (Supplementary sources: docs.github.com REST pages for pulls, pull comments, git refs, commit statuses, and check runs.)

## Key knowledge

### Create an issue

- `POST /repos/{owner}/{repo}/issues` — 201 Created; also 400/403/404/410 (issues disabled)/422/503.
- Body: `title` (required, string or integer), `body` (string), `assignees` (array of logins), `milestone` (number), `labels` (array), `type` (issue type name). `assignees`, `milestone`, `labels`, `type` are **silently dropped** if the caller lacks push access to the repo.
- "Creating content too quickly using this endpoint may result in secondary rate limiting."

### Create a pull request

- `POST /repos/{owner}/{repo}/pulls` — 201 Created; 403/422 on failure.
- Body: `title` (required unless `issue` given), `head` (required — branch containing changes; cross-repo form is `username:branch`), `base` (required — branch to merge into), `body`, `draft` (boolean), `maintainer_can_modify` (boolean), `head_repo` (needed for cross-repo PRs when both repos are in the same organization), `issue` (integer — converts an existing issue into a PR; substitutes for `title`).

### PR review comments (diff-anchored)

- Create: `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments` — 201; 403/422.
- Body: `body` (required), `commit_id` (required — SHA the comment applies to), `path` (required — file path relative to repo root), `line` (integer — required unless `subject_type: file`), `side` (`LEFT` for deletions / `RIGHT` for additions and context), multi-line ranges via `start_line` + `start_side` together with `line` + `side`, `subject_type` (`line` or `file`), `in_reply_to` (comment id).
- `position` parameter is deprecated ("closing down") — use `line`.
- Reply shortcut: `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies` with only `body`.

### Create a branch (git refs API)

- Create: `POST /repos/{owner}/{repo}/git/refs` — 201; 409/422.
  - Body: `ref` (required — **fully qualified**, e.g. `refs/heads/quarantine/abc123`; short names are rejected) and `sha` (required — commit SHA the ref points at). This is how a branch is created server-side without a clone.
- Get: `GET /repos/{owner}/{repo}/git/ref/{ref}` (note singular `ref` in path) — 200/404.
- Update: `PATCH /repos/{owner}/{repo}/git/refs/{ref}` with `sha` (required) and `force` (boolean, default `false` — when false, only fast-forward updates are accepted).
- Delete: `DELETE /repos/{owner}/{repo}/git/refs/{ref}` — 204; 422 includes attempts to delete the default branch.

### Commit statuses

- Create: `POST /repos/{owner}/{repo}/statuses/{sha}` — 201. Requires push access.
- Body: `state` (required — exactly one of `error`, `failure`, `pending`, `success`), `target_url` (link to details), `description` (short summary), `context` (label distinguishing this status from others; default `default`).
- Hard limit: "there is a limit of 1000 statuses per sha and context within a repository" — attempts beyond that fail.
- Read back: `GET /repos/{owner}/{repo}/commits/{ref}/statuses` (paginated, newest first) and combined rollup `GET /repos/{owner}/{repo}/commits/{ref}/status` (combined state = `failure` if any context errors/fails, `pending` if none exist or any pending, `success` if all succeed).

### Check runs (GitHub Apps only)

- Create: `POST /repos/{owner}/{repo}/check-runs` — 201.
- "Write permission for the REST API to interact with checks is only available to GitHub Apps." Fine-grained PATs and OAuth tokens cannot create check runs — this matches the fine-grained-PAT doc's Checks API limitation.
- Body (for reference if Ouroboros ever ships a GitHub App): `name` (required), `head_sha` (required), `status` (`queued` | `in_progress` | `completed`), `conclusion` (`action_required` | `cancelled` | `failure` | `neutral` | `success` | `skipped` | `stale` | `timed_out`), `started_at` / `completed_at` (ISO 8601), `details_url`, `external_id`, `output` object (`title` + `summary` required, `text`, `annotations` array — max 50 per request, fields `path`, `start_line`, `end_line`, `start_column`, `end_column`, `annotation_level`, `message`, `title`, `raw_details`).
- GitHub limits check runs with the same name to 1000 per check suite.

### Write etiquette (applies to all of the above)

- Serialize mutating calls; wait at least one second between `POST`/`PATCH`/`PUT`/`DELETE` requests; honor `retry-after` on secondary-rate-limit responses.

## Notable quotes

> "Write permission for the REST API to interact with checks is only available to GitHub Apps." — GitHub Docs

> "Creating content too quickly using this endpoint may result in secondary rate limiting." — GitHub Docs

> "The name of the fully qualified reference (ie: refs/heads/master)." — GitHub Docs, on the `ref` body parameter

## Application to Ouroboros

The quarantine flow is: resolve the offending commit SHA → `POST /git/refs` with `ref: refs/heads/<quarantine-branch>` and that `sha` (no clone needed) → push fix-up commits → `POST /pulls` with `head` = quarantine branch, `base` = original branch. The Inquisitor files findings with `POST /issues` (remembering that `labels`/`assignees` silently no-op without push access), and the Inspector anchors line-level feedback using PR review comments with `commit_id` + `path` + `line`/`side` (never the deprecated `position`). Verdicts on each commit go through commit statuses with a stable `context` like `ouroboros/inspector` — check runs are off the table under PAT auth, so the richer annotation model is documented only for a future GitHub App migration. The runner must throttle these writes (≥1s apart, no concurrency) to stay under secondary rate limits.
