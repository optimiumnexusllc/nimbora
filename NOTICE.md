# Notice

NIMBORA includes software originally released under the BSD 2-Clause License:

- The voice-agent platform code: Copyright (c) 2025, Zansat Technologies Private
  Limited — see `LICENSE`, which must accompany any redistribution.
- `pipecat/`: Copyright (c) 2024–2026, Daily — see `pipecat/LICENSE`.

Third-party components run by the deployment keep their own licenses, among them:
Asterisk (GPLv2, run as a separate service), Ollama (MIT), Speaches (MIT),
faster-whisper (MIT), Kokoro-82M (Apache-2.0), Piper voices (per-voice licenses —
check each model card before commercial use), Caddy (Apache-2.0), coturn (BSD),
PostgreSQL/pgvector, Redis, MinIO (AGPLv3, run unmodified as a separate service),
Space Grotesk and Geist fonts (SIL Open Font License).

## Enterprise PBX engine

The optional white-label PBX (`deploy/pbx/`) installs **Wazo Platform**
(https://github.com/wazo-platform), Copyright The Wazo Authors, licensed under the
**GNU GPL v3.0**. It runs on its own server as separate programs; NIMBORA talks to it
over its network APIs only. The kit configures it and replaces some of its templates
with our own; it does not modify its source code, and the engine's license files and
copyright notices stay installed. Anyone redistributing modified engine packages must
provide their source code under the GPL-3.0. "Wazo" is a trademark of its owner; the
white-label configuration removes it from what end users see, and no endorsement by its
owner is implied.

