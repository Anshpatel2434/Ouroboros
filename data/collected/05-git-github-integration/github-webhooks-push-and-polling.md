---
title: Repository Webhooks — Push Event, HMAC Validation, Redelivery, and the Polling Alternative
source_url: https://docs.github.com/en/webhooks/webhook-events-and-payloads
publisher: GitHub
retrieved: 2026-08-26
domain: git-github-integration
doc_type: official-docs
relevance: Ouroboros's hosted backend must detect commits in near-real time; webhooks are the push path and conditional-request polling is the PAT-only fallback.
---

## Summary

Repository webhooks deliver JSON payloads to a user-defined HTTPS endpoint when repository events occur. The `push` event carries the pushed ref, before/after SHAs, and an array of commit objects with per-file added/removed/modified lists — enough to detect a change without an immediate API call. Webhooks are created and managed via the REST API (`POST /repos/{owner}/{repo}/hooks`), authenticated deliveries are verified with an HMAC-SHA256 signature in the `X-Hub-Signature-256` header, and missed deliveries can be replayed via the redelivery endpoints for up to 3 days. Where a webhook endpoint is unavailable, the sanctioned alternative is polling with conditional requests (`if-none-match` ETags), because a `304 Not Modified` response does not count against the primary rate limit. (Supplementary sources: docs.github.com pages on creating repo webhooks, validating deliveries, webhook best practices, redelivering webhooks, and REST best practices.)

## Key knowledge

### Push event payload shape

- Fires when commits are pushed to a branch or tag, including branch/tag creation. It does **not** fire when more than 5,000 branches are pushed at once, nor for tags when more than three tags are pushed at once.
- Available for: `repository`, `organization`, `app` webhooks.
- Top-level fields:
  - `ref` (string) — full git ref pushed, e.g. `refs/heads/main` or `refs/tags/v3.14.1`.
  - `before` (string) — SHA of the most recent commit on the ref **before** the push.
  - `after` (string) — SHA of the most recent commit on the ref **after** the push.
  - `created` / `deleted` / `forced` (booleans) — whether the push created, deleted, or force-pushed the ref.
  - `compare` (string) — URL showing the changes from `before` to `after`.
  - `commits` (array) — pushed commit objects; "The array includes a maximum of 2048 commits" (fetch the rest via the compare API when truncated).
  - `head_commit` (object or null) — most recent commit object.
  - `pusher` (object) — git author/committer metaproperties.
  - `base_ref` (string or null).
  - Plus `repository` and `sender` objects common to all events.
- Each commit object in `commits[]` contains: `id`, `message`, `timestamp` (ISO 8601), `author` (name/email/username), `committer`, `added`, `removed`, `modified` (arrays of file paths), `distinct` (boolean), `url`.

### Creating and managing webhooks via REST

- Create: `POST /repos/{owner}/{repo}/hooks` — 201 on success; 403/404/422 on failure.
  - Body: `name` (only accepted value: `web`), `active` (default `true`), `events` (default `["push"]`), and required `config` object with `url` (required), `content_type` (`json` or `form`, default `form` — Ouroboros should always set `json`), `secret` (enables HMAC signing), `insecure_ssl` (`0` = verify SSL, `1` = skip; default `0`).
- List: `GET /repos/{owner}/{repo}/hooks`; Get: `GET /repos/{owner}/{repo}/hooks/{hook_id}`; Update: `PATCH /repos/{owner}/{repo}/hooks/{hook_id}`; Delete: `DELETE /repos/{owner}/{repo}/hooks/{hook_id}`.
- Ping: `POST /repos/{owner}/{repo}/hooks/{hook_id}/pings`; Test push: `POST /repos/{owner}/{repo}/hooks/{hook_id}/tests`.

### HMAC secret validation

- GitHub signs each delivery with the webhook `secret`: HMAC-SHA256 over the **raw request body**, hex digest, sent as `X-Hub-Signature-256: sha256=<hexdigest>`.
- Validation: recompute the HMAC with your stored secret and compare using a constant-time comparison — "Never use a plain `==` operator"; use `secure_compare` / `crypto.timingSafeEqual`.
- Process payload bytes as UTF-8 before hashing (payloads may contain unicode).
- Legacy `X-Hub-Signature` header is HMAC-SHA1, kept for backward compatibility only.
- Official test vector: secret `It's a Secret to Everybody`, payload `Hello, World!`, expected signature `sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17`.

### Delivery handling and redelivery

- Respond with a 2XX within **10 seconds**; queue for asynchronous processing rather than working inline.
- Identify the event via the `X-GitHub-Event` request header (and the payload's top-level `action` key for events that have one).
- `X-GitHub-Delivery` header is a GUID unique per event — use it for dedup/replay-attack protection. Redelivered requests keep the **original** `X-GitHub-Delivery` value.
- Redelivery window: "You can redeliver webhook deliveries that occurred in the past 3 days."
- REST redelivery endpoints:
  - List: `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries` (params: `per_page` max 100, `cursor` for pagination).
  - Get one: `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}`.
  - Redeliver: `POST /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}/attempts` — returns 202 Accepted.
- Hardening: use HTTPS with SSL verification on; optionally allowlist GitHub's IPs from `GET /meta`, refreshed periodically; subscribe only to needed events; do not assume delivery ordering.

### Polling alternative — conditional requests / ETags

- Most REST endpoints return an `etag` header; many return `last-modified`.
- Poll loop: save the `etag`, resend the same request with `if-none-match: <etag>` (or `if-modified-since: <last-modified>`); unchanged data returns `304 Not Modified`.
- Rate-limit exemption: "Making a conditional request does not count against your primary rate limit if a `304` response is returned and the request was made while correctly authorized with an `Authorization` header."
- Keep polling parameters and sort order stable so 304s stay frequent; request the narrowest data that answers "did anything change?".
- General write etiquette (secondary rate limits): avoid concurrent requests; wait at least one second between `POST`/`PATCH`/`PUT`/`DELETE` requests; on rate limiting honor `retry-after` if present, else wait until `x-ratelimit-reset`.

## Notable quotes

> "Your server should respond with a 2XX response within 10 seconds of receiving a webhook delivery." — GitHub Docs

> "Never use a plain `==` operator. Instead consider using a method like `secure_compare` or `crypto.timingSafeEqual`." — GitHub Docs

> "Making a conditional request does not count against your primary rate limit if a `304` response is returned." — GitHub Docs

## Application to Ouroboros

The hosted backend's commit-detection service (feeding the Inquisitor) should create a repo webhook at onboarding via `POST /repos/{owner}/{repo}/hooks` with `events: ["push"]`, `content_type: json`, and a per-repo random `secret`, then verify every delivery's `X-Hub-Signature-256` with a timing-safe comparison before enqueuing. The push payload's `before`/`after` SHAs slot directly into the already-documented compare API to pull diffs; `commits[].added/removed/modified` gives a cheap pre-filter for which files changed. Dedup on `X-GitHub-Delivery`, ack within 10 seconds, and on backend downtime replay via the `/deliveries/.../attempts` endpoint (3-day window). For users who cannot expose a webhook (or as a health fallback), the runner polls branch heads with `if-none-match` ETags — free of rate-limit cost on 304 — making polling viable even at short intervals under the PAT's 5,000 req/hr budget.
