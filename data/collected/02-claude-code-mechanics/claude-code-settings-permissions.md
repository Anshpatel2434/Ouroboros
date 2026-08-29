---
title: settings.json, settings.local.json, and permission rule syntax
source_url: https://code.claude.com/docs/en/permissions
publisher: Anthropic
retrieved: 2026-08-26
domain: claude-code-mechanics
doc_type: official-docs
relevance: Ouroboros generates guard-railed repos — the allow/deny/ask rule grammar, settings precedence, and permission modes are the exact enforcement surface the Generator writes and the runner relies on.
---

## Summary

Claude Code reads settings from four JSON files plus managed sources, with precedence (highest first): managed settings → `--settings` CLI → `.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`. Permission rules live under the `permissions` key as `allow`/`ask`/`deny` arrays of `Tool` or `Tool(specifier)` patterns; evaluation order is deny → ask → allow, first match wins, and a deny at any scope beats an allow at any other. Six permission modes (`default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`) set the approval baseline. Project allow rules wait for workspace trust; `-p`/SDK sessions never show the trust dialog. Companion page: code.claude.com/docs/en/settings.

## Key knowledge

### Settings files and precedence
- Files: user `~/.claude/settings.json` (all your projects); shared project `.claude/settings.json` (commit for the team); project local `.claude/settings.local.json` (yours only — Claude Code adds `**/.claude/settings.local.json` to your global git excludes when it creates it; if you create it by hand, gitignore it yourself); managed `managed-settings.json` / MDM / server-managed (org-enforced, nothing overrides it except a few security keys where the stricter value from any scope wins, e.g. `disableClaudeAiConnectors: true`).
- Precedence (highest→lowest): managed → `--settings <file-or-json>` (one session) → project local → shared project → user. List keys like `permissions.allow` merge across scopes rather than overriding (exceptions: `fallbackModel`, `modelPicker`, managed `availableModels`).
- Strict JSON: `//` comments or trailing commas are a Settings Error. `$schema`: `https://json.schemastore.org/claude-code-settings.json`. Malformed individual entries → Settings Warning, entry skipped. In `-p` runs broken files are silently skipped — run `claude doctor` to see what was dropped.
- Files hot-reload mid-session (permissions, hooks, apiKeyHelper); `model`, `effortLevel`, `outputStyle` are read at start only. `ConfigChange` hook fires per detected settings change.
- On Windows `~/.claude` = `%USERPROFILE%\.claude`; `CLAUDE_CONFIG_DIR` relocates everything. `~/.claude.json` is a separate machine-managed file (sign-in, MCP servers, per-project trust state, global config keys).
- `settings.local.json` is read/written at the git repository root (v2.1.211+; resolved through worktrees to the main checkout), except outside git repos, when the root is `$HOME`, on Windows, or on ownership mismatches — then it stays in the starting directory. Env vars are not a precedence level; each settings key documents its paired variable (e.g. `ANTHROPIC_MODEL` beats the `model` key; `ANTHROPIC_DEFAULT_MODEL` applies only when no file sets `model`).
- Cloud sessions read only committed `.claude/settings.json` and server-managed settings — never user or local files.
- "Yes, and don't ask again" on a Bash prompt saves an allow rule to `.claude/settings.local.json` (permanent per repo); file-edit approvals last only until session end. Approving a compound command saves up to 5 per-subcommand rules.

### Permission rule syntax
- Shape: `Tool` or `Tool(specifier)`. Bare `Bash` (or `Bash(*)`) matches every Bash call; as a deny rule a bare tool name removes the tool from Claude's context entirely, while a scoped rule (`Bash(rm *)`) leaves the tool visible and blocks matching calls.
- Evaluation: deny, then ask, then allow — first match decides; specificity is irrelevant. A broad `Bash(aws *)` deny beats a narrower `Bash(aws s3 ls)` allow; a matching ask beats a more specific allow.
- Rules are enforced by Claude Code, not the model; CLAUDE.md text shapes behavior but grants nothing.
- Bash wildcards: `*` matches any text including spaces. `Bash(npm run *)` matches `npm run build` and bare `npm run`; `Bash(ls *)` requires the space (doesn't match `lsof`), `Bash(ls*)` matches `lsof` too. `:*` suffix ≡ trailing ` *` (`Bash(ls:*)`). Put `*` after the subcommand — `Bash(git *)` allows every git command including `git -c core.fsmonitor=<script>`. Example config:
  `{"permissions": {"allow": ["Bash(npm run *)", "Bash(git commit *)"], "deny": ["Bash(git push *)"]}}`
- Compound commands: separators `&&`, `||`, `;`, `|`, `|&`, `&`, newlines are parsed; a rule must match each subcommand independently.
- Wrapper stripping: `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, zsh `noglob`, bare `xargs`, and known-safe leading env assignments are stripped before matching (deny/ask rules match past any leading assignment). Not stripped: `npx`, `docker exec`, `devbox run`, etc. — write combined rules like `Bash(devbox run npm test)`. `watch`, `setsid`, `ionice`, `flock`, `find -exec` always prompt unless exact-match ruled.
- Built-in read-only Bash set runs promptless in every mode (`ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`, `find`, `wc`, `which`, `diff`, `stat`, `du`, `cd`, read-only git). Not configurable; add ask/deny rules to re-gate. Output redirections (`>`, `>>`, `2>`) are checked as file writes against Edit rules/protected paths (`/dev/null` exempt).
- Parameter matching (deny/ask only): `Tool(param:value)` for top-level scalar params — `Agent(model:opus)`, `Agent(isolation:worktree)`, `Bash(run_in_background:true)`. `*` wildcard allowed in the value; omitted params never match; primary content fields (`command`, `file_path`, `path`, `url`) are not matchable this way (`Bash(command:rm *)` is ignored with a warning).
- Tool-name globs: deny/ask accept globs in the tool-name position (`"*"`, `"mcp__*"`); allow rules accept globs only after a literal `mcp__<server>__` prefix (`mcp__puppeteer__*`, `mcp__github__get_*`); unanchored allow globs are skipped with a warning.
- Read/Edit rules use gitignore syntax with four anchors: `//path` = filesystem root, `~/path` = home, `/path` = relative to the settings source (project root in project settings, `~/.claude` in user settings, original cwd for local/CLI/session rules), `path` or `./path` = cwd-relative. On Windows paths normalize to POSIX (`//c/Users/...`). `Edit` rules cover all built-in editing tools; write path rules as `Edit(...)`/`Read(...)` only — `Write(...)`, `Glob(...)`, `NotebookEdit(...)` path rules are accepted but never consulted. A `Read` deny also blocks Edit/Write on the path (v2.1.208+/228+). Bare filenames match at any depth (`Read(.env)` ≡ `Read(**/.env)`). Single-segment dir patterns: allow `Edit(src/**)` anchors at cwd; deny/ask match `src` at any depth. Symlinks: allow needs both link and target to match; deny fires if either matches. Read/Edit denies also cover recognized file commands in Bash (`cat`, `sed`...) but not arbitrary subprocess I/O — use OS sandboxing for that.
- WebFetch: `WebFetch(domain:example.com)`; `domain:*.example.com` matches subdomains only; mid-pattern `*` can't cross dots; `WebFetch(domain:*)` covers all URLs and also feeds the sandbox network allowlist, while bare `WebFetch` in allow just stops fetch prompts (and in deny removes the tool).
- MCP: `mcp__server` (whole server), `mcp__server__tool`. Subagents: `Agent(AgentName)`. `Cd(path)` rules gate the `/cd` command (`*` = one segment, `**` = across segments).
- Bash rules constraining URLs/args are fragile (flags, protocols, redirects, variables defeat them) — prefer denying `curl`/`wget` + allowing `WebFetch(domain:...)`, or a PreToolUse hook.
- PreToolUse hooks run before rules; a hook exit-2 block beats allow rules, but deny/ask rules still apply regardless of hook "allow" output.

### Permission modes
- `default` (labeled Manual, alias `manual` v2.1.200+): prompt on first use of each tool. `acceptEdits`: auto-accept file edits + common fs commands (`mkdir`, `touch`, `mv`, `cp`) inside working/additional dirs. `plan`: read-only exploration. `auto`: classifier reviews actions. `dontAsk`: auto-deny anything not pre-allowed (`AskUserQuestion`, org-ask connector tools, `requiresUserInteraction` MCP tools denied even if allowed). `bypassPermissions`: skip all prompts including protected paths (`.git`, `.claude`) — isolated environments only.
- Startup default: `permissions.defaultMode` in settings. Kill switches: `permissions.disableBypassPermissionsMode: "disable"` and `permissions.disableAutoMode: "disable"` (any scope; a user can lock themselves out too).
- Working directories: extend access with `--add-dir <path>`, `/add-dir`, or `permissions.additionalDirectories`. Only flag/command-added dirs also load skills/commands/agents; the settings key grants file access only. `/cd` relocates the session (new CLAUDE.md, `--resume` finds it there).
- Workspace trust: project `permissions.allow` + `additionalDirectories` apply only after the trust dialog is accepted (deny/ask apply immediately). `-p`/SDK sessions count as accepted for the git-tracking check but never apply untrusted project allow rules (stderr warning instead) and connect `.mcp.json` servers without asking. Manual trust: set `projects["<path>"].hasTrustDialogAccepted: true` in `~/.claude.json`. Hardening for foreign repos: `--setting-sources user`, `--bare`, `--settings '{"disableAllHooks": true}'`, `disabledMcpjsonServers`.
- Example starter configs: github.com/anthropics/claude-code/tree/main/examples/settings.

## Notable quotes

> "Rules are evaluated in order: deny, then ask, then allow. The first match in that order determines the outcome." — Configure permissions

> "If a tool is denied at any level, no other level can allow it." — Configure permissions

> "Permission rules are enforced by Claude Code, not by the model." — Configure permissions

## Application to Ouroboros

This is the Generator's core template: emit `.claude/settings.json` with a deny-first posture (`Bash(git push *)`, `Read(./.env*)`, `mcp__*` as needed), narrow subcommand-anchored allows, and `defaultMode` per harness profile; keep runner-specific overrides in `settings.local.json` knowing its rules skip workspace trust while untracked. The runner must account for `-p` semantics — no trust dialog, project allow rules silently withheld, `.mcp.json` auto-connected — so locked-down CI runs should pair `--permission-mode dontAsk` with explicit `--allowedTools` and `--setting-sources`. The Inspector validates generated rule files against this grammar (wildcard-before-subcommand warnings, unmatchable `command:` rules, unanchored MCP allow globs).
