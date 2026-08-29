---
title: GitHub REST API — Commits, Get Commit, and Compare Endpoints
source_url: https://docs.github.com/en/rest/commits/commits
publisher: GitHub
retrieved: 2026-08-25
domain: git-github-integration
doc_type: official-docs
relevance: These are the exact endpoints Ouroboros uses to detect new commits by polling and to pull per-commit and cross-range diffs.
---

## Summary

Three endpoints cover Ouroboros's commit-detection and diff-pulling needs: list commits (filterable by branch, path, author, and `since`/`until` timestamps), get a single commit (returns per-file diff data including `patch` text), and compare two commits (`base...head`, returning ahead/behind status, the commit range, and changed files). Diffs are also available as raw `diff`/`patch` bodies via custom `Accept` media types. Both single-commit and compare responses truncate the `files` list at 300 entries per page, which large commits will exceed.

## Key knowledge

- **List commits**: `GET /repos/{owner}/{repo}/commits`
  - Query params: `sha` (SHA or branch to start listing from; default: repo's default branch), `path` (only commits touching this file path), `author`, `committer` (GitHub login or email), `since` / `until` (ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`; timestamps must fall between 1970-01-01 and 2099-12-31), `per_page` (max 100, default 30), `page` (default 1).
  - Response: array of commit objects with `sha`, `url`, `html_url`, `node_id`, nested `commit` object (`message`, `author`, `committer`, `tree`), and `verification` (signature status).
  - Status codes: 200, 400, 404, 409, 500. (409 Conflict is returned for an empty repository — poll loops must tolerate it.)
- **Get a commit**: `GET /repos/{owner}/{repo}/commits/{ref}`
  - `ref` = commit SHA, branch (`heads/BRANCH_NAME`), or tag (`tags/TAG_NAME`).
  - Response includes `stats` (`additions`, `deletions`, `total`) and a `files` array: `filename`, `status` (enum: `added`, `removed`, `modified`, `renamed`, `copied`, `changed`, `unchanged`), `additions`, `deletions`, `changes`, `patch` (unified-diff hunk text), `blob_url`, `raw_url`, `contents_url`.
  - Pagination of files: "If there are more than 300 files in the commit diff and the default JSON media type is requested, the response will include pagination link headers for the remaining files, up to a limit of 3000 files." Use `per_page`/`page` on this endpoint to walk files.
  - Media types via `Accept`: `application/vnd.github.diff` (raw diff), `application/vnd.github.patch` (email-style patch), `application/vnd.github.sha` (bare SHA-1).
  - Status codes: 200, 404, 409, 422, 500, 503.
- **Compare two commits**: `GET /repos/{owner}/{repo}/compare/{basehead}`
  - `basehead` format: `BASE...HEAD` (three dots); cross-fork within the same network: `USERNAME:BASE...USERNAME:HEAD`.
  - Response fields: `status` (enum: `diverged`, `ahead`, `behind`, `identical`), `ahead_by`, `behind_by`, `total_commits`, `commits` (array of commit objects), `files` (array of diff entries), `base_commit`, `merge_base_commit`, plus `url`, `html_url`, `permalink_url`, `diff_url`, `patch_url`.
  - Limits: without paging params the commit list is capped at **250 commits**; with pagination the changed-files list appears only on the **first page** and includes at most **300 changed files for the entire comparison** — beyond that, fetch per-commit diffs instead.
  - Also supports `application/vnd.github.diff` and `.patch` media types.
- **Related endpoints**: `GET /repos/{owner}/{repo}/commits/{commit_sha}/branches-where-head` (branches whose head is this commit); `GET /repos/{owner}/{repo}/commits/{commit_sha}/pulls` (PRs containing the commit).
- **Headers**: `Authorization: Bearer <TOKEN>` and `Accept: application/vnd.github+json` are the standard request headers.

## Notable quotes

> "When calling this endpoint without any paging parameter (per_page or page), the returned list is limited to 250 commits." — GitHub Docs

> "The list of changed files is only shown on the first page of results, and it includes up to 300 changed files for the entire comparison." — GitHub Docs

## Application to Ouroboros

The runner's polling mode calls `GET /repos/{owner}/{repo}/commits?sha=<branch>&since=<last_seen>` to detect new work, then either `GET /compare/{last_seen_sha}...{new_head}` for the whole delta or per-commit `GET /commits/{sha}` when the Inquisitor needs each commit's individual `patch` hunks. For large commits the Inspector must handle the 300-file page cap (paginate the get-commit endpoint, or request `application/vnd.github.diff` for the raw diff in one body). The `files[].status` enum and `patch` field names should be mirrored exactly in the internal diff model; `compare.status == "identical"` is the cheap no-op signal for a poll tick.
