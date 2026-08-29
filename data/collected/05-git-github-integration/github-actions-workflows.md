---
title: GitHub Actions — push/pull_request Triggers, Secrets, GITHUB_TOKEN Permissions, External Calls
source_url: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
publisher: GitHub
retrieved: 2026-08-26
domain: git-github-integration
doc_type: official-docs
relevance: Generated harness repos ship a GitHub Actions workflow that runs on push/PR and calls the Ouroboros backend; this covers trigger filters, secret handling, and the GITHUB_TOKEN permission/recursion model.
---

## Summary

A workflow's `on:` block selects triggering events; `push` and `pull_request` both support `branches`/`paths` filters, and `pull_request` additionally filters by activity `types` (defaulting to `opened`, `synchronize`, `reopened`). Every job receives an automatically minted `GITHUB_TOKEN` — a GitHub App installation token scoped to the repo — whose per-scope access is controlled by the `permissions` key; specifying any scope sets all unspecified scopes to `none`. Events caused by `GITHUB_TOKEN` deliberately do not spawn new workflow runs, which prevents recursion but means bot-pushed commits need a PAT if they must retrigger CI. Secrets exist at organization, repository, and environment level, are referenced as `${{ secrets.NAME }}`, are redacted from logs, and are withheld from fork-triggered runs — the standard channel for calling an external service (like the Ouroboros backend) with a credential. (Supplementary sources: docs.github.com pages on GITHUB_TOKEN, workflow-syntax `permissions`, and using secrets.)

## Key knowledge

### Triggers

- `push`:
  - Filters: `branches`, `branches-ignore`, `tags`, `tags-ignore`, `paths`, `paths-ignore` (branches/tags filters take glob patterns like `releases/**`).
  - Run context: `GITHUB_SHA` = tip commit pushed to the ref; `GITHUB_REF` = the updated ref.
  - Not created when more than 5,000 branches are pushed at once, or for tags when more than three tags are pushed at once (same limits as the webhook).
  - Example:
    ```yaml
    on:
      push:
        branches: ['main', 'releases/**']
        paths: ['**.js']
    ```
- `pull_request`:
  - `types` default: `opened`, `synchronize`, `reopened`; other activity types include `closed`, `edited`, `labeled`, `unlabeled`, `assigned`, `unassigned`, `locked`, `unlocked`, `review_requested`, `review_request_removed`, `ready_for_review`, `auto_merge_enabled`, `auto_merge_disabled`.
  - Filters: `branches`/`branches-ignore` match the **base** (target) branch; `paths`/`paths-ignore` match changed files; filter on the head branch via `github.head_ref` in `if:` conditions.
  - Run context: `GITHUB_REF` = `refs/pull/<PR_NUMBER>/merge`; `GITHUB_SHA` = the last **merge commit** on that merge branch — the real head commit is `github.event.pull_request.head.sha`.
  - Workflows will not run on `pull_request` activity if the PR has a merge conflict (no merge commit can be built).
- Other triggers worth knowing: `workflow_dispatch` (manual/API), `repository_dispatch` (external POST), `schedule` (cron).

### GITHUB_TOKEN model

- Minted per job as a GitHub App installation access token, scoped to the workflow's repository; access via `${{ secrets.GITHUB_TOKEN }}` or the `github.token` context (actions can read `github.token` even when not explicitly passed).
- Lifetime: tied to the job — GitHub-hosted runner jobs cap at 6 hours; on self-hosted runners the token is valid for at most 24 hours even though jobs may run up to 5 days (use a PAT for longer).
- Recursion guard: "events triggered by the `GITHUB_TOKEN` will not create a new workflow run", with exceptions `workflow_dispatch` and `repository_dispatch`; additionally, PRs created/updated by a workflow's `GITHUB_TOKEN` produce `pull_request` runs that require approval. To have bot-generated pushes/PRs trigger CI normally, authenticate with a PAT or GitHub App token instead.
- `permissions` key — settable at workflow top level or per job (`jobs.<job_id>.permissions`):
  ```yaml
  permissions:
    contents: read
    issues: write
    pull-requests: write
    statuses: write
  ```
  - Scope names include: `actions`, `attestations`, `checks`, `contents`, `deployments`, `discussions`, `id-token`, `issues`, `packages`, `pages`, `pull-requests`, `security-events`, `statuses`, `vulnerability-alerts` (each `read`/`write`/`none`; `id-token` is `write`/`none`).
  - Shorthands: `permissions: read-all`, `permissions: write-all`, `permissions: {}` (disable all).
  - Rule: "If you specify the access for any of these permissions, all of those that are not specified are set to `none`."
  - Repo/org settings choose the default (permissive vs restricted) when no `permissions` key is present; least-privilege is the documented recommendation.

### Secrets

- Three levels: organization (shareable across repos with access policies), repository, environment. Collision precedence: environment > repository > organization.
- Naming: alphanumeric + underscores only, case-insensitive, must not start with `GITHUB_`.
- Limits: 48 KB per secret; up to 100 secrets each at org, repo, and environment level.
- Reference syntax: `${{ secrets.SECRET_NAME }}` — typically mapped into a step's `env:` or passed as `with:` input; secrets cannot be referenced directly in `if:` conditionals.
- Redacted from logs automatically (but transformations like Base64 defeat redaction).
- Fork safety: "Secrets are not passed to the runner when a workflow is triggered from a forked repository" (except `GITHUB_TOKEN`); also not auto-passed to reusable workflows and unavailable to Dependabot-triggered runs.
- CLI management: `gh secret set SECRET_NAME`, `gh secret list`, `gh secret set --env ENV_NAME SECRET_NAME`, `gh secret set --org ORG_NAME SECRET_NAME --visibility all`.

### Calling external services from a workflow

- Pattern: store the service credential as a repo/org secret, expose it to a step via `env:`, and call the service with `curl`/SDK in a `run:` step. Fork-triggered `pull_request` runs won't have the secret, so external calls must degrade gracefully there (or use `pull_request_target` with extreme caution).

## Notable quotes

> "When you use the repository's `GITHUB_TOKEN` to perform tasks, events triggered by the `GITHUB_TOKEN` will not create a new workflow run." — GitHub Docs

> "If you specify the access for any of these permissions, all of those that are not specified are set to `none`." — GitHub Docs

> "Secrets are not passed to the runner when a workflow is triggered from a forked repository." — GitHub Docs

## Application to Ouroboros

The Generator emits a workflow triggered `on: push` (all branches, so quarantine branches are covered) and `on: pull_request` (default types suffice for fix-up PRs), with an explicit least-privilege block like `permissions: {contents: read, statuses: write}` — remembering that naming any scope zeroes the rest. The workflow reports to the hosted backend with an `OUROBOROS_TOKEN` repository secret set during onboarding (`gh secret set OUROBOROS_TOKEN`), mapped into `env:` for a `curl` step; the harness must tolerate the secret's absence on fork PRs. Two recursion facts shape the fix-up flow: pushes made with the workflow's own `GITHUB_TOKEN` won't retrigger CI, so the backend's fix-up commits — pushed with the user's PAT — **will** trigger workflows, and the runner must therefore tag its own commits (e.g. commit-message trailer) to avoid an Inquisitor → fix-up → Inquisitor loop. In `pull_request` runs the Inspector must evaluate `github.event.pull_request.head.sha`, not `GITHUB_SHA` (a synthetic merge commit).
