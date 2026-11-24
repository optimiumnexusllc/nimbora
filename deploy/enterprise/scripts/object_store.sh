# shellcheck shell=bash
# Object store of the enterprise stack, sourced by install.sh and restore.sh.
#
# New installs use the bundled SeaweedFS. An install made before (the MinIO
# volume exists and .env has no OBJECT_STORE) keeps MinIO until its files are
# migrated (docs/deployment/object-storage.mdx). MinIO keeps running while its
# volume exists and MINIO_RETIRED is not true, so that during a migration the
# files not yet copied stay readable. The `minio` profile is written into
# COMPOSE_PROFILES in .env: a plain `docker compose up` then keeps it too.
#
#   usage: enterprise_object_store <env_file> <docker command…>
#   prints « minio » when MinIO must run, nothing otherwise.

MINIO_VOLUME="${MINIO_VOLUME:-nimbora-enterprise_minio_data}"

_object_store_get() {  # _object_store_get FILE KEY — last value, comment stripped
  awk -F= -v key="$2" '$1 == key { v = substr($0, length(key) + 2) } END { print v }' "$1" \
    | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//'
}

_object_store_set() {  # _object_store_set FILE KEY VALUE — replace or append
  if grep -qE "^$2=" "$1"; then
    sed -i -E "s|^$2=.*|$2=$3|" "$1"
  else
    printf '%s=%s\n' "$2" "$3" >> "$1"
  fi
}

enterprise_object_store() {
  local env_file=$1
  shift
  local store retired profiles has_minio=0 need_minio=0 profile list=() kept=() joined
  store="$(_object_store_get "$env_file" OBJECT_STORE)"
  retired="$(_object_store_get "$env_file" MINIO_RETIRED)"
  if "$@" volume inspect "$MINIO_VOLUME" >/dev/null 2>&1; then has_minio=1; fi
  if [[ -z "$store" ]]; then
    store=seaweedfs
    if [[ $has_minio == 1 ]]; then store=minio; fi
    _object_store_set "$env_file" OBJECT_STORE "$store"
  fi
  if [[ "$store" == minio || ( $has_minio == 1 && "$retired" != true ) ]]; then
    need_minio=1
  fi

  profiles="$(_object_store_get "$env_file" COMPOSE_PROFILES)"
  IFS=, read -r -a list <<< "$profiles"
  for profile in "${list[@]}"; do
    if [[ -n "$profile" && "$profile" != minio ]]; then kept+=("$profile"); fi
  done
  if [[ $need_minio == 1 ]]; then kept+=(minio); fi
  joined="$(IFS=,; echo "${kept[*]}")"
  if [[ "$joined" != "$profiles" ]]; then
    _object_store_set "$env_file" COMPOSE_PROFILES "$joined"
  fi
  if [[ $need_minio == 1 ]]; then echo minio; fi
  return 0
}
