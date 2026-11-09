# Commit 34 — Public deployment with cost cap, release process, README v2

**Phase 2 · Ops · depends on: everything** · final checkpoint: **v2 live**

## Context
An interviewer should be able to click a link and try it, without the author paying unbounded API bills or exposing anything.
Then the README must tell the phase-2 story: what "production grade" means here and the evidence for each claim.

## Read first
- `docs/ARCHITECTURE.md`, `docs/SLO.md`, `docs/RELIABILITY.md`, `docs/THREAT_MODEL.md`, `docs/EVAL_PLATFORM.md`, `docs/RESULTS.md`, `docs/PROGRESS.md`

## Task
1. **Deployment target** — pick one small, cheap setup and justify it in `docs/DEPLOY.md` (e.g. a single VM with Docker Compose + Caddy for TLS; or a PaaS for the API + managed Postgres/Redis + Zilliz Cloud free tier for Milvus). Must support: HTTPS, secrets via env, persistent volumes or managed stores, logs.
2. **Production images** — multi-stage Dockerfile (non-root user, pinned deps, model weights downloaded at build or first start into a volume), `docker-compose.prod.yml`, healthchecks wired to live/ready.
3. **Cost and abuse caps** — daily LLM spend cap (tracked from the cost module; above it → friendly "demo budget reached" and handoff), per-IP and per-session rate limits, max conversation length, demo customers only, a banner saying it is a demo with synthetic data.
4. **Release process** — `docs/RELEASE.md` + a GitHub workflow: tag → build image → run the full eval gate (offline evals, red-team, sim subset) against the candidate → deploy only if green → smoke test the live URL → rollback command. Index releases still go through the alias gate (22).
5. **Runbook** — `docs/RUNBOOK.md`: dashboards to check, what each alert/drift breach means, how to roll back app and index, how to rotate keys, how to purge a customer's data (memory delete + conversation purge).
6. **README v2** (keep generated results via `make results`, extend the generator):
   - Top: live demo link, video, one-paragraph pitch.
   - "What production-grade means here" — a table: concern → mechanism → evidence (link to report): safety (gate, grounding, guardrails), reliability (fail-closed, chaos report), data lifecycle (versioned index, policy dates), context & memory (ContextBuilder, short/long-term, sim reports), evals (CIs, CI gate, red-team, simulator, online drift), performance (SLO + load report), operations (release, runbook).
   - Results at a glance with CIs; v1 vs v2 comparison table.
   - Architecture diagram v2; design decisions with trade-offs (add phase-2 ones: fail-closed vs availability, partial answers, claim removal vs rewrite, cache eligibility, memory as hints not evidence).
   - Honest limitations: synthetic data and traffic, single region, demo auth.
7. Verify the live URL with the demo script and the red-team smoke subset against production (low rate).

## Requirements
- No secrets in images or repo; `.env.example` complete.
- README numbers generated; a CI check fails if a percentage appears outside generated blocks (from commit 16).

## Tests
- Spend cap logic (fixture costs cross the cap → demo-budget response).
- Release workflow dry-run on a branch (skips deploy without secrets).

## Done when
- [ ] Live URL works over HTTPS; spend cap and rate limits verified
- [ ] README v2 published; release + runbook docs written
- [ ] `make check` green; PROGRESS row 34 updated; mark **"v2 live"**
- [ ] Interview note `docs/notes/34-deploy-readme-v2.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(deploy): production images, capped public demo, eval-gated release workflow, runbook and README v2
```
