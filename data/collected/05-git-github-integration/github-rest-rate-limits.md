---
title: Rate Limits for the GitHub REST API
source_url: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
publisher: GitHub
retrieved: 2026-08-25
domain: git-github-integration
doc_type: official-docs
relevance: Ouroboros polls repositories for new commits and creates issues/branches/PRs via the API; primary and secondary limits bound the polling frequency and write throughput per user PAT.
---

## Summary

GitHub enforces primary rate limits (requests per hour, keyed to the authenticating identity) and secondary rate limits (points per minute, concurrency, CPU time, and content-creation caps). A personal access token — fine-grained or classic — gets 5,000 requests/hour (15,000 on Enterprise Cloud). Secondary limits are the ones an automation like Ouroboros is most likely to trip: write requests cost 5 points each against a 900-points-per-minute budget, and content creation is capped at 80/minute and 500/hour. Rate-limit state is exposed in `x-ratelimit-*` response headers, which should be read instead of polling `GET /rate_limit`.

## Key knowledge

- **Primary limits (requests/hour)**:
  - Unauthenticated: **60/hour**.
  - Authenticated user via PAT: **5,000/hour** ("All of these requests count towards your personal rate limit of 5,000 requests per hour" — note this is per *user*, shared across all of that user's tokens/OAuth apps).
  - Users affiliated with a GitHub Enterprise Cloud org: **15,000/hour**.
  - GitHub App installations: minimum 5,000/hour; scaling installs (non-Enterprise) gain +50/hour per repo beyond 20 and per user beyond 20, capped at **12,500/hour**; Enterprise Cloud installs: 15,000/hour.
  - `GITHUB_TOKEN` inside Actions: **1,000 requests/hour per repository** (15,000/hour/repo for Enterprise Cloud).
  - Git LFS: 300 req/min unauthenticated, 3,000 req/min authenticated.
- **Secondary limits** (all apply simultaneously):
  - Max **100 concurrent requests**.
  - Max **900 points per minute** to REST endpoints (GraphQL: 2,000 points/min).
  - Point costs: REST `GET`/`HEAD`/`OPTIONS` = **1 point**; REST `POST`/`PATCH`/`PUT`/`DELETE` = **5 points**; GraphQL without mutations = 1; with mutations = 5.
  - Max **90 seconds of CPU time per 60 seconds** of real time.
  - Content creation: max **80 content-generating requests per minute** and **500 per hour** (issues, comments, PRs, etc.).
  - Max 2,000 OAuth access-token requests per hour.
- **Response headers**: `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-used`, `x-ratelimit-reset` (UTC epoch seconds when the window resets), `x-ratelimit-resource` (which limit bucket applied), and on secondary-limit rejections `retry-after` (seconds to wait).
- **Checking status**: `GET /rate_limit` does not count against the primary limit (but can count against secondary); GitHub recommends reading the response headers on ordinary requests instead.
- **On exceeding**: primary limit → `403` or `429` with `x-ratelimit-remaining: 0`; secondary limit → `403`/`429` with an error message. Recovery protocol: honor `retry-after` if present, else wait until `x-ratelimit-reset`, else wait at least one minute. "Continuing to make requests while you are rate limited may result in the banning of your integration."
- **Raising limits**: authenticate everything; consider a GitHub App (scaling limits) or Enterprise Cloud for higher ceilings.

## Notable quotes

> "The primary rate limit for unauthenticated requests is 60 requests per hour." — GitHub Docs

> "No more than 80 content-generating requests per minute and no more than 500 content-generating requests per hour." — GitHub Docs

> "Continuing to make requests while you are rate limited may result in the banning of your integration." — GitHub Docs

## Application to Ouroboros

The runner's polling loop budgets against the *user's own* 5,000/hour PAT limit — polling every repo every minute with 2 reads costs ~2,880 requests/day/repo, so the backend should centralize per-token accounting, read `x-ratelimit-remaining`/`x-ratelimit-reset` on every response, and back off before hitting zero (the user's other tooling shares the same bucket). The Inquisitor/Inspector write path (issues, PR comments, fix-up PRs) must be throttled under the 80/min and 500/hour content-creation caps — a burst of findings on a big commit needs a queue, not a fan-out. All 403/429 handling should honor `retry-after` and never hot-retry, since bans are explicitly threatened.
