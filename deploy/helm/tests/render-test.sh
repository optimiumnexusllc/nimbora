#!/usr/bin/env bash
# Chart checks run by .github/workflows/helm-chart.yml (helm + yq v4).
#   deploy/helm/tests/render-test.sh
# Lints the chart with each example, then renders the object-store modes and
# checks what each one must (and must not) create.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../nimbora"

BASE=(--set secrets.ossJwtSecret=test --set secrets.turnSecret=test
      --set exposure.gatewayApi.gatewayClassName=test)
fail() { echo "FAIL: $*" >&2; exit 1; }
render() { helm template nimbora . "${BASE[@]}" "$@"; }
# kind/name of every rendered object
objects() { yq -N 'select(.kind) | .kind + "/" + .metadata.name' <<< "$1" | sort; }
has() { grep -qx "$2" <<< "$(objects "$1")" || fail "$3: $2 missing"; }
lacks() { ! grep -qx "$2" <<< "$(objects "$1")" || fail "$3: $2 rendered"; }
get() { yq -N "select(.kind == \"$2\" and .metadata.name == \"$3\") | $4" <<< "$1"; }

helm lint . "${BASE[@]}"
for example in examples/*.yaml; do
  helm lint . "${BASE[@]}" -f "$example" --set secrets.databaseUrl=x --set secrets.redisUrl=x
done

# Default (internalMinio): releases installed before keep MinIO, now pullable.
out="$(render)"
has "$out" Deployment/nimbora-minio default
has "$out" Secret/nimbora-minio default
lacks "$out" Deployment/nimbora-seaweedfs default
[[ "$(get "$out" Deployment nimbora-minio '.spec.template.spec.containers[0].image')" == \
   docker.io/bitnamilegacy/minio:2025.4.22@sha256:* ]] || fail "default: MinIO image"
[[ "$(get "$out" Deployment nimbora-minio '.spec.template.spec.containers[0].args[0]')" == minio ]] \
  || fail "default: Bitnami MinIO needs the minio command"
[[ "$(get "$out" PersistentVolumeClaim nimbora-minio '.metadata.annotations["helm.sh/resource-policy"]')" == keep ]] \
  || fail "default: MinIO volume not kept"
[[ "$(get "$out" ConfigMap nimbora-config '.data.MINIO_ENDPOINT')" == nimbora-minio:9000 ]] \
  || fail "default: MINIO_ENDPOINT"

# internalSeaweedfs: SeaweedFS only, shared credentials, /voice-audio/ to it.
out="$(render --set storage.mode=internalSeaweedfs --set exposure.mode=ingress)"
has "$out" Deployment/nimbora-seaweedfs seaweedfs
has "$out" Service/nimbora-seaweedfs seaweedfs
has "$out" Secret/nimbora-minio seaweedfs
lacks "$out" Deployment/nimbora-minio seaweedfs
lacks "$out" PersistentVolumeClaim/nimbora-minio seaweedfs
[[ "$(get "$out" Deployment nimbora-seaweedfs '.spec.template.spec.containers[0].image')" == \
   docker.io/chrislusf/seaweedfs:4.55@sha256:7ca46aeae2f223b37e5d91593c17ab37738eec6df6ab69b48a0487f7643342b9 ]] \
  || fail "seaweedfs: image"
[[ "$(get "$out" PersistentVolumeClaim nimbora-seaweedfs '.metadata.annotations["helm.sh/resource-policy"]')" == keep ]] \
  || fail "seaweedfs: volume not kept"
[[ "$(get "$out" Deployment nimbora-seaweedfs '.spec.template.spec.containers[0].env[] | select(.name == "AWS_SECRET_ACCESS_KEY") | .valueFrom.secretKeyRef.name')" == nimbora-minio ]] \
  || fail "seaweedfs: identity from the shared secret"
[[ "$(get "$out" ConfigMap nimbora-config '.data.OBJECT_STORE')" == seaweedfs ]] || fail "seaweedfs: OBJECT_STORE"
[[ "$(get "$out" ConfigMap nimbora-config '.data.SEAWEEDFS_ENDPOINT')" == http://nimbora-seaweedfs:8333 ]] \
  || fail "seaweedfs: SEAWEEDFS_ENDPOINT"
[[ "$(get "$out" ConfigMap nimbora-config '.data.MINIO_ENDPOINT')" == null ]] || fail "seaweedfs: MINIO_ENDPOINT set"
[[ "$(get "$out" Ingress nimbora '.spec.rules[0].http.paths[] | select(.path == "/voice-audio/") | .backend.service.name')" == nimbora-seaweedfs ]] \
  || fail "seaweedfs: ingress /voice-audio/"
out="$(render --set storage.mode=internalSeaweedfs --set exposure.mode=gatewayApi)"
[[ "$(get "$out" HTTPRoute nimbora-minio '.spec.rules[0].backendRefs[0].name')" == nimbora-seaweedfs ]] \
  || fail "seaweedfs: HTTPRoute /voice-audio/"

# Migration: both stores, files still on MinIO readable.
out="$(render --set storage.mode=internalSeaweedfs --set minio.keepDuringMigration=true)"
has "$out" Deployment/nimbora-seaweedfs migration
has "$out" Deployment/nimbora-minio migration
[[ "$(get "$out" ConfigMap nimbora-config '.data.MINIO_ENDPOINT')" == nimbora-minio:9000 ]] \
  || fail "migration: MINIO_ENDPOINT"

# External S3: no bundled store at all.
out="$(render --set storage.mode=s3)"
lacks "$out" Secret/nimbora-minio s3
lacks "$out" Deployment/nimbora-seaweedfs s3
lacks "$out" Deployment/nimbora-minio s3

echo "Helm chart checks passed."
