# Release Process (`docs/RELEASE.md`)

Every production release is gated by automated offline tests, the eval release gate, and live smoke checks.

## 1. App Release Pipeline (`.github/workflows/release.yml`)

1. **Tag**: Create an annotated release tag (`git tag v2.0.0 && git push origin v2.0.0`).
2. **Verify & Build (`verify-and-build`)**:
   - Runs `make check` (`ruff`, `ruff format --check`, `mypy`, `pytest`, `notes-check`).
   - Builds the multi-stage non-root Docker image (`Dockerfile`).
3. **Eval Release Gate (`eval-gate`)**:
   - Runs `make eval-gate` (smoke + red-team + statistical CI comparison against `eval/baselines/main.json`).
   - Blocks deployment if `no_answer` false accept > `0`, any red-team category exceeds its budget, or a core metric regresses beyond its 95% CI.
   - On branch dry-runs without live LLM secrets, skips the live gate cleanly.
4. **Deploy & Smoke Test (`deploy`)**:
   - Deploys the tagged image via `docker-compose.prod.yml` only if all prior jobs are green and deploy secrets are configured.
   - Probes `/api/health/live` and `/api/health/ready` over HTTPS.
   - Post-deploy manual check: run `docs/DEMO_SCRIPT.md` and the red-team smoke subset at low rate against the live URL.

## 2. App Rollback Command

```bash
# Pin ATLAS_IMAGE to the previous known-good tag and recreate only the API service
ATLAS_IMAGE=support-agent:v2.0.0 docker compose -f docker-compose.prod.yml up -d --no-deps api
curl -fsS "https://${ATLAS_DOMAIN}/api/health/ready"
```

## 3. Index Releases & Rollbacks (Commit 22)

Knowledge-base index updates are decoupled from app deploys and go through the versioned Milvus alias gate:
- Plan & build: `make index-plan` → `make index-build`
- Gated release: `make index-release` (runs paired retrieval/gate check before moving `support_chunks_live`)
- Instant rollback: `make index-rollback` (moves the Milvus alias back to `previous_build_id` without re-embedding)
