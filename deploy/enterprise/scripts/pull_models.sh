#!/usr/bin/env bash
# Download the local AI models into the Ollama and Speaches caches.
# Safe to re-run; already-downloaded models are skipped by the servers.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

get_env() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//'; }

PROFILE="$(get_env COMPOSE_PROFILES)"
SUFFIX=""; [[ "$PROFILE" == "gpu" ]] && SUFFIX="-gpu"
LLM_MODEL="$(get_env LOCAL_LLM_MODEL)"; LLM_MODEL="${LLM_MODEL:-qwen2.5:7b-instruct}"
STT_MODEL="$(get_env LOCAL_STT_MODEL)"; STT_MODEL="${STT_MODEL:-deepdml/faster-whisper-large-v3-turbo-ct2}"

failures=0

echo "==> LLM: $LLM_MODEL"
docker compose exec -T "ollama$SUFFIX" ollama pull "$LLM_MODEL" || failures=$((failures+1))

# Every TTS model referenced by the language packs, plus the STT model.
MODELS=$(docker compose exec -T api python -c "
from api.services.local_ai.language_packs import all_tts_models
print('\n'.join(all_tts_models()))
")
MODELS="$STT_MODEL
$MODELS"

while IFS= read -r model; do
  [[ -z "$model" ]] && continue
  echo "==> Speaches: $model"
  # POST /v1/models/{id} downloads a model into the shared Hugging Face cache.
  if ! docker compose exec -T api python - "$model" <<'PY'
import sys, urllib.request, urllib.error
model = sys.argv[1]
req = urllib.request.Request(f"http://speaches:8000/v1/models/{model}", method="POST")
try:
    with urllib.request.urlopen(req, timeout=1800) as r:
        print("   ok", r.status)
except urllib.error.HTTPError as e:
    body = e.read().decode()[:200]
    if e.code in (200, 201, 409) or "already" in body.lower():
        print("   already present")
    else:
        print(f"   FAILED {e.code}: {body}")
        sys.exit(1)
PY
  then
    failures=$((failures+1))
  fi
done <<< "$MODELS"

if [[ $failures -gt 0 ]]; then
  echo "$failures model(s) failed. Check ids against: docker compose exec api curl -s http://speaches:8000/v1/registry"
  exit 1
fi
echo "All models ready."
