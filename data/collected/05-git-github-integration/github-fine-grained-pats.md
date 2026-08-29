---
title: Managing Your Personal Access Tokens (Fine-Grained PATs)
source_url: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
publisher: GitHub
retrieved: 2026-08-25
domain: git-github-integration
doc_type: official-docs
relevance: Ouroboros authenticates its hosted backend with a user-supplied fine-grained PAT; this defines the scopes, repo selection, expiration, and limitations we must design around.
---

## Summary

Fine-grained personal access tokens are GitHub's recommended replacement for classic PATs. Each token is bound to a single resource owner (one user or one organization), can be limited to specific repositories, and carries granular per-area permissions (e.g. Contents, Issues, Pull requests) at read/write/admin levels instead of coarse classic scopes. Expiration defaults to 30 days, is configurable up to 366 days (or infinite unless a policy forbids it), and organizations can require admin approval before a token gains access. Several APIs and access patterns remain unsupported by fine-grained tokens, which matters when choosing which GitHub features Ouroboros can rely on.

## Key knowledge

- **Resource owner binding**: "Each token is limited to access resources owned by a single user or organization." A token cannot span multiple orgs; one Ouroboros PAT covers exactly one user's or one org's repos.
- **Repository access options** at creation: `All repositories`, `Public repositories`, or `Only select repositories` (explicit repo picker). Regardless of choice, fine-grained tokens "always include read-only access to all public repositories on GitHub."
- **Permission model**: permissions are assigned per area at levels **read**, **write**, or **admin** (not every permission supports every level).
  - Repository permissions include: `Contents`, `Pull requests`, `Issues`, `Actions`, `Deployments`, `Secrets`, `Workflows` (write-only).
  - Account permissions include: GPG keys, SSH keys, Email addresses, Followers, Starring, Watching.
  - Organization permissions include: Members, Secrets, Administration, Custom roles, Projects.
  - Docs guidance: "choose the minimal permissions necessary for your needs."
- **Expiration**: default 30 days; maximum configurable 366 days; infinite lifetimes allowed but may be blocked by an org/enterprise maximum-lifetime policy. GitHub "automatically removes personal access tokens that haven't been used in a year."
- **Org approval flow**: if the org requires approval, the token is marked `pending` until an org administrator reviews it; while pending it can only read public resources. Org owners' own tokens are auto-approved.
- **Creation path (UI)**: Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token; fields: `Token name` (max 40 chars), `Expiration`, optional `Description`, `Resource owner`, `Repository access`, `Permissions`.
- **Known limitations of fine-grained PATs** (classic PAT or GitHub App needed instead):
  - Cannot contribute to public repos where the owner is not a member/collaborator.
  - Cannot act as an outside/repository collaborator on another owner's repos.
  - Cannot access multiple organizations with one token.
  - Cannot access Packages.
  - Cannot call the Checks API ("Using fine-grained personal access token to call the Checks API" is unsupported) — Ouroboros must use commit statuses or issues instead of check runs when authenticating with a fine-grained PAT.
  - Cannot access user-account-owned Projects.
- **Git-over-HTTPS**: when prompted for a password during clone/push over HTTPS, supply the token "instead of your password."
- **Security recommendations**: treat tokens like passwords; store as secrets (Actions/Codespaces) rather than hardcoding; inside GitHub Actions prefer the built-in `GITHUB_TOKEN`; consider GitHub CLI or Git Credential Manager as alternatives.

## Notable quotes

> "GitHub recommends that you use fine-grained personal access tokens instead of personal access tokens (classic) whenever possible." — GitHub Docs

> "Each token is limited to access resources owned by a single user or organization." — GitHub Docs

> "Treat your access tokens like passwords." — GitHub Docs

## Application to Ouroboros

The hosted backend's onboarding flow must instruct users to mint a fine-grained PAT with `Only select repositories` scoped to the monitored repo(s) and exactly the permissions the runner needs: `Contents` (read for diffs, write for quarantine branches and fix-up commits), `Issues` (write, for Inquisitor-opened issues), `Pull requests` (write, for fix-up PRs and Inspector PR comments), and `Metadata` (implicit read). Because fine-grained PATs cannot call the Checks API, the Inspector must report via commit statuses, issues, or PR comments — never check runs. Token expiry (30-day default) means the backend needs expiry detection and re-auth prompts; org-owned repos may leave the token `pending` until an admin approves it, which the backend should surface as a distinct onboarding state.
