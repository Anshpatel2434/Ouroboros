---
title: Git Worktrees for Parallel Checkouts, and Branch Protection Rule Basics
source_url: https://git-scm.com/docs/git-worktree
publisher: Git (git-scm.com) & GitHub
retrieved: 2026-08-26
domain: git-github-integration
doc_type: reference
relevance: Parallel agent fleets need one checkout per agent without cloning N times — worktrees provide that; branch protection defines what Ouroboros's automated pushes and PRs are allowed to do on guarded branches.
---

## Summary

`git worktree` attaches multiple working trees to a single repository: one main worktree plus any number of linked worktrees, each with its own `HEAD` and index but sharing the object database, refs, and config. This lets several branches be checked out simultaneously from one clone — the natural substrate for a fleet of agents working in parallel — with the hard constraint that the same branch cannot be checked out in two worktrees at once (without `--force`). Linked-worktree metadata lives under `$GIT_DIR/worktrees/<id>` and the worktree's `.git` is a file pointing back at it. On the GitHub side, branch protection rules (matched by `fnmatch` patterns) can require PR reviews, passing status checks, linear history, signed commits, and more before anything lands on a protected branch — rejecting direct pushes and blocking PR merges via both git and the API — with rulesets as the newer, stackable alternative. (Supplementary source: docs.github.com "About protected branches".)

## Key knowledge

### Worktree commands

- `git worktree add [<options>] <path> [<commit-ish>]` — creates a linked worktree at `<path>` checked out at `<commit-ish>` (default: `HEAD`; bare `git worktree add <path>` creates a new branch named after the path basename).
  - `-b <new-branch>` — create branch at `<commit-ish>` and check it out there; `-B` resets the branch if it exists.
  - `--detach` — detached HEAD, no branch association (useful for read-only throwaway checkouts).
  - `--no-checkout` — skip populating files; `--orphan` — empty orphan branch; `--lock [--reason <string>]` — lock immediately; `--guess-remote` — set up tracking from a matching remote branch.
- `git worktree list [-v | --porcelain [-z]]` — enumerate worktrees (porcelain mode for scripting).
- `git worktree lock [--reason <string>] <worktree>` / `git worktree unlock <worktree>` — protect a worktree (e.g. on removable media) from pruning.
- `git worktree move <worktree> <new-path>`; `git worktree remove [-f] <worktree>` (`-f` removes unclean trees; `--force --force` removes locked ones); `git worktree prune [-n] [-v] [--expire <expire>]` — clean up stale metadata; `git worktree repair [<path>…]` — fix links after manual moves.

### Worktree semantics

- Constraint: `add` refuses when `<commit-ish>` is a branch already checked out in another worktree, unless `--force` is given — two agents can never hold the same branch.
- Per-worktree (private): `HEAD`, the index, pseudo-refs directly under `$GIT_DIR`, `refs/bisect/*`, `refs/worktree/*`, `refs/rewritten/*`.
- Shared: everything else under `refs/` (branches, tags), the object database, and repo config — a commit made in one worktree is instantly visible to all others.
- Layout: each linked worktree's `.git` is a **file** containing `gitdir: /path/main/.git/worktrees/<id>`; under `$GIT_DIR/worktrees/<id>/` live that worktree's `HEAD`, `index`, optional `locked` (reason text), and `config.worktree`.
- Per-worktree config requires `git config extensions.worktreeConfig true`; then settings such as `core.sparseCheckout` go in `config.worktree`. Never share `core.worktree` or `core.bare=true` across worktrees.
- Cross-worktree ref addressing: `main-worktree/HEAD`, `worktrees/<name>/HEAD`, `worktrees/<name>/refs/bisect/bad`.
- Config knobs: `worktree.guessRemote`, `worktree.useRelativePaths` (default false — links are absolute, so moving trees manually breaks them; fix with `git worktree repair`).
- Canonical flow: `git worktree add -b emergency-fix ../temp master` → work/commit in `../temp` → `git worktree remove ../temp`.

### Branch protection rules (GitHub)

- A rule targets branches by an `fnmatch` pattern (e.g. `main`, `*release*`, `releases/*`). Only one classic branch protection rule applies to a branch at a time; **rulesets** are the newer alternative that can layer.
- Available protections:
  - **Require a pull request before merging** — with a required approval count, optional "dismiss stale pull request approvals when new commits are pushed", and optional requirement that the most recent push be approved by someone other than its author.
  - **Require status checks to pass before merging** — "Required status checks must have a `successful`, `skipped`, or `neutral` status"; the *strict* variant additionally requires the branch to be up to date with the base branch before merging. Checks are identified by context name (commit status `context` or check run name).
  - **Require conversation resolution before merging**; **Require signed commits**; **Require linear history** (no merge commits — squash/rebase only); **Require deployments to succeed before merging**; **Require merge queue**.
  - **Lock branch** — read-only; no commits can be made.
  - **Restrict who can push to matching branches** — allowlist of users/teams/apps.
  - **Allow force pushes** (off by default on protected branches) and **Allow deletions** (off by default).
- By default admins are exempt; enabling **"Do not allow bypassing the above settings"** applies the rule to admins and bypass-permission holders too.
- Enforcement applies equally to git pushes and REST API writes: a direct push (or `PATCH /git/refs` update) to a protected branch that violates the rule is rejected, and PRs cannot merge until requirements are green.

## Notable quotes

> "A git repository can support multiple working trees, allowing you to check out more than one branch at a time." — git-scm.com, git-worktree

> "Locking a branch will make the branch read-only and ensures that no commits can be made to the branch." — GitHub Docs

## Application to Ouroboros

The runner materializes a parallel agent fleet from one clone: `git worktree add -b <agent-branch> <path> <base-sha>` per agent, giving each agent an isolated `HEAD`/index while sharing objects (cheap on disk, and one agent's commits are immediately fetchable by the orchestrator without network I/O). The one-branch-one-worktree rule doubles as a free mutex — two agents cannot silently collide on a branch — and teardown is `git worktree remove` plus a periodic `git worktree prune`. Quarantine work happens on Ouroboros-owned branches precisely because target branches are expected to be protected: the backend must anticipate that pushes to `main` will be rejected and that fix-up PRs merge only when required status checks (which can be the harness's own `ouroboros/*` commit statuses) pass, required reviews are in, and — under *strict* checks — the PR branch is up to date with base. Onboarding docs should recommend a protection rule on the monitored branch requiring the Inspector's status context, turning Ouroboros's verdict into a hard merge gate.
