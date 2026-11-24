# NIMBORA - Project Overview

NIMBORA is a voice AI platform for building and deploying conversational AI agents with telephony and WebRTC support.

## Project Structure

```
nimbora/
├── api/              # Backend - FastAPI application
├── ui/               # Frontend - Next.js application
├── scripts/          # Helper scripts for local development
├── docs/             # Mintlify documentation
├── pipecat/          # Pipecat framework (vendored in this repository)
├── docker-compose.yaml       # Production/OSS deployment
├── docker-compose-local.yaml # Local development services
```

## Tech Stack

- **Backend**: Python with FastAPI
- **Frontend**: Next.js 15 with React 19, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with SQLAlchemy (async)
- **Cache/Queue**: Redis with ARQ for background tasks
- **Storage**: S3-compatible object storage for audio and documents: SeaweedFS by default in `docker-compose.yaml`, MinIO in `docker-compose-local.yaml` and on installations not yet migrated (see `docs/deployment/object-storage.mdx`)

## Local Development

Contributor setup and service startup are documented in `docs/contribution/setup.mdx`.

## Environment Configuration

- `api/.env` - Backend environment variables. Source this when running repo-owned backend scripts against the dev DB (e.g. `python -m scripts.dump_docs_openapi`).
- `api/.env.test` - Test-only environment variables. Source this when running pytest so tests hit the test DB and never the dev/prod credentials in `api/.env`.
- `ui/.env` - Frontend environment variables

Typical invocation:

```bash
# Tests
source venv/bin/activate && set -a && source api/.env.test && set +a && python -m pytest api/tests/...

# Backend scripts
source venv/bin/activate && set -a && source api/.env && set +a && python -m scripts.dump_docs_openapi
```

## Working Rules

Rules for every agent (and person) changing this repository. Adapted from Andrej Karpathy's observations on LLM coding mistakes, as collected in [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). They favour care over speed: a typo or an obvious one-liner does not need the whole process.

1. **Look and ask before coding.** Read what already exists before adding to it (there is usually a service, client or test helper to reuse: `api/services/`, `api/db/`, `api/tests/pbx_fake.py`). State your assumptions. When a request can be read several ways, or when getting it wrong is expensive (a migration, a deployment change, anything touching existing customer data), name the options and ask instead of picking one silently.
2. **The simplest change that solves it.** No feature, option or abstraction nobody asked for; no error handling for cases that cannot happen. If it could be half as long, rewrite it.
3. **Surgical changes, one subject per PR.** Every changed line should trace back to the request. Match the surrounding style. Do not reformat or refactor code you are not changing: run `scripts/format.sh` (what CI checks), not a formatter over whole directories. A defect found on the way gets its own commit or PR, mentioned in the description; dead code you did not create is reported, not deleted. Remove only what your own change made unused.
4. **Prove it.** Turn the task into checks before writing code: a bug gets a test that reproduces it first; a feature gets tests for its rules, including isolation between organizations. For several steps, write the plan with how each step is verified. Generated files (`docs/api-reference/openapi.json`, `ui/src/client/`) are regenerated, not edited. Look at a UI change rendered, not only at its tests.
5. **Say what is not verified.** Anything that depends on a real PBX, a provider key or an operating system stays 🧪 in the README until it has run there (`docs/validation/phase5-lab.md` records the lab runs). Never present a guess as a result.
6. **Never on your own:** merging a PR, committing secrets (check `git diff --staged`; credentials stay in the server's chmod 600 files), or acting on production data. These wait for the maintainer's explicit go-ahead.
