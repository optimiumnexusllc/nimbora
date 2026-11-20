#!/usr/bin/env bash
# Grant platform-operator (super-admin) rights to an existing account.
#   ./scripts/make_superuser.sh you@example.com
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ $# -eq 1 ]] || { echo "usage: $0 email"; exit 1; }
# The email is passed as a psql variable, never interpolated into SQL.
docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -v email="$1" <<'SQL'
UPDATE users SET is_superuser = true WHERE lower(email) = lower(:'email')
RETURNING id, email, is_superuser;
SQL
