---
name: cu013-cloud-run
description: Operates and maintains Cloud Run packaging, Docker images, and deployment configurations.
---

# cu013-cloud-run

## Responsibility
Maintain container packaging, non-root execution, Docker builds, and deployment coordination with Cloud Run.

## Allowed Changes
- Optimizing Docker build caching.
- Adjusting Cloud Run resource allocations (CPU, memory, concurrency) within agreed limits.
- Updating `cloudbuild.yaml` build steps.

## Forbidden Changes
- Installing development tools or caches into the production container.
- Running container as `root`.
- Speculatively increasing autoscaling or creating new Cloud Run services without authorization.
- Adding API keys to deployment descriptors.

## Inputs / Contracts
- `Dockerfile`, `cloudbuild.yaml`, `.env.example`.

## Outputs / Contracts
- OCI-compliant lightweight Docker image built for `python:3.12-slim`.

## Trusted References
- [Dockerfile](../../Dockerfile)
- [cloudbuild.yaml](../../cloudbuild.yaml)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- `docker build -t cu013-agentic-ivr:test .`
- Container startup test on local port.

## STOP Conditions
- Docker build failures or container runtime crashes on `PORT=8080`.
