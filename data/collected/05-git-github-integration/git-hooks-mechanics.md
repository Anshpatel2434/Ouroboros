---
title: Git Hooks Mechanics — Lifecycle, core.hooksPath, and Distribution
source_url: https://git-scm.com/docs/githooks
publisher: Git (git-scm.com)
retrieved: 2026-08-26
domain: git-github-integration
doc_type: reference
relevance: Generated Ouroboros harness repos ship pre-commit/pre-push hooks; this defines exactly how hooks fire, why they don't clone with the repo, and the distribution strategies the Generator must choose between.
---

## Summary

Git hooks are executable files that git runs at fixed points in its lifecycle. They live in `$GIT_DIR/hooks` (i.e. `.git/hooks`) unless `core.hooksPath` redirects lookup elsewhere; a hook is enabled simply by existing under the correct name with the executable bit set — no extension. Because `.git/hooks` is local repository state, hooks are **not** copied by `git clone`, which is a deliberate security property: cloning a repo must never grant it code execution on your machine. Teams therefore distribute hooks by committing them inside the working tree and pointing `core.hooksPath` at that directory (or symlinking/copying them into `.git/hooks`, or using `init.templatedir`), while truly mandatory policy belongs in server-side hooks or CI. Client-side hooks like `pre-commit` and `pre-push` can veto operations via nonzero exit but are bypassable with `--no-verify`. (Supplementary source: Pro Git book, "Customizing Git - Git Hooks".)

## Key knowledge

### Where hooks live and how they activate

- Default directory: `$GIT_DIR/hooks` (`.git/hooks` in a normal repo). Override with the `core.hooksPath` config variable: `git config core.hooksPath /path/to/hooks` (relative paths are taken relative to the directory where hooks are run).
- A hook runs iff a file with the exact hook name exists there and is executable; non-executable files are silently ignored. No file extension.
- `git init` seeds `.git/hooks` with `*.sample` scripts; they are inert until renamed to drop `.sample`.
- Hooks are **not copied on clone**; `git init` can copy hooks only via the template mechanism (`init.templatedir`).
- Working directory when a hook runs: root of the working tree for non-bare repos, `$GIT_DIR` for bare repos; push-side hooks (`pre-receive`, `update`, `post-receive`, `post-update`, `push-to-checkout`) always run in `$GIT_DIR`. Environment vars like `GIT_DIR`/`GIT_WORK_TREE` are exported to child git commands.

### Commit-path hooks

- `pre-commit` — runs before the commit message is obtained; **no arguments**; nonzero exit aborts the commit; bypassed by `git commit --no-verify`. Sample enforces no non-ASCII filenames / trailing whitespace (`hooks.allownonascii` toggles the former).
- `prepare-commit-msg` — runs after the default message is prepared, before the editor; args: (1) path of the commit message file, (2) source: `message` (`-m`/`-F`), `template` (`-t`/`commit.template`), `merge`, `squash`, or `commit` plus (3) a commit object name for `-c`/`-C`/`--amend`. Nonzero aborts. **Not suppressed by `--no-verify`.**
- `commit-msg` — single arg: path to the file holding the proposed message; may edit it in place; nonzero aborts; bypassed by `--no-verify`. Sample detects duplicate `Signed-off-by` trailers.
- `post-commit` — runs after the commit exists; no args; exit code cannot affect the commit — notification only.

### Push-path hooks

- `pre-push` — invoked by `git push`; args: (1) remote name, (2) remote location/URL. For each ref to be pushed, stdin receives one line: `<local-ref> SP <local-oid> SP <remote-ref> SP <remote-oid> LF` (full OIDs; `<remote-oid>` is all-zeroes if the remote ref doesn't exist; deletions show `(delete)` as `<local-ref>` and all-zeroes local OID). Nonzero exit aborts the entire push; stderr reaches the user.
- Server-side (relevant only if self-hosting a remote): `pre-receive` (stdin lines `<old-oid> SP <new-oid> SP <ref-name> LF`; nonzero rejects all refs), `update` (per-ref, args: refname, old OID, new OID; nonzero rejects that ref), `post-receive` (same stdin as pre-receive; cannot affect outcome; used for notification/deploy). Push options surface as `GIT_PUSH_OPTION_COUNT` / `GIT_PUSH_OPTION_<n>`.

### Why hooks don't clone, and distribution strategies

- `.git/` contents are never transferred by clone/fetch, so hooks committed nowhere simply don't exist on a fresh clone — and by design a cloned repo cannot autorun code on the cloner's machine.
- Strategy 1 — **tracked hooks dir + core.hooksPath** (modern standard): commit hooks to e.g. `.githooks/` in the working tree and have a one-time setup step run `git config core.hooksPath .githooks`. Caveat: the config command itself must be run per-clone (often wired into `npm prepare`, a Makefile target, or a bootstrap script).
- Strategy 2 — **copy/symlink into `.git/hooks`**: e.g. `ln -s ../../.githooks/pre-commit .git/hooks/pre-commit` (or copy on Windows). Same per-clone activation requirement.
- Strategy 3 — **init template**: `git config --global init.templatedir '~/.git-templates'` and place hooks in `~/.git-templates/hooks`; new `git init`/`clone` picks them up, existing clones don't.
- Strategy 4 — **server-side enforcement**: client hooks are advisory (bypassable via `--no-verify` or by deleting the hook); anything mandatory must run in `pre-receive`/`update` on the server — on GitHub.com, where custom server hooks aren't available, the equivalent is branch protection + required status checks/CI.

## Notable quotes

> "Before Git invokes a hook, it changes its working directory to either $GIT_DIR in a bare repository or the root of the working tree in a non-bare repository." — git-scm.com, githooks

> "It's important to note that client-side hooks are not copied when you clone a repository." — Pro Git

## Application to Ouroboros

The Generator ships each harness repo with a tracked `.githooks/` directory (`pre-commit` for fast local lint/eval gates, `post-commit` for fire-and-forget notification to the backend, `pre-push` as the last local checkpoint before code reaches GitHub) and an idempotent bootstrap step that runs `git config core.hooksPath .githooks` — because no hook will fire on a fresh clone otherwise. Hook scripts must carry the executable bit in the index (`git update-index --chmod=+x`) or self-invoke via `sh`, since a non-executable hook is silently ignored, especially on Windows checkouts. Crucially, the design must treat client hooks as best-effort: an agent (or human) can bypass them with `--no-verify`, so the Inspector's authoritative gate lives server-side in the GitHub Actions workflow plus commit statuses/branch protection, with hooks serving only as the low-latency first line. `pre-push`'s stdin format gives the harness the exact `<local-oid>` range to pre-report to the backend before the push event lands.
