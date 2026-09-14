#!/bin/bash
set -euo pipefail

role='@@ROLE@@'
package_root="$(cd "$(dirname "$0")/.." && pwd -P)"
credential_file="${REDIS_SHARED_MEMORY_CONFIG:-$HOME/.config/redis-shared-memory/$role.env}"

fail() {
  printf 'Redis Shared Memory %s: %s\n' "$role" "$1" >&2
  exit 1
}

[[ -f "$package_root/FILES.sha256" ]] || fail 'package checksum manifest is missing.'
(cd "$package_root" && /usr/bin/shasum -a 256 -c FILES.sha256 >/dev/null) || fail 'installed package integrity check failed; reinstall the verified ZIP.'
[[ -f "$credential_file" && ! -L "$credential_file" ]] || fail 'credential file is missing or unsafe; run install.sh again.'
[[ "$(/usr/bin/stat -f '%u' "$credential_file")" = "$(/usr/bin/id -u)" ]] || fail 'credential file must be owned by the current user.'
[[ "$(/usr/bin/stat -f '%Lp' "$credential_file")" = '600' ]] || fail 'credential file permissions must be 0600; run install.sh again.'

seen='|'
while IFS='=' read -r key value || [[ -n "${key:-}${value:-}" ]]; do
  [[ -n "${key:-}" ]] || continue
  case "$key" in
    RAM_ENDPOINT|RAM_STORE_ID|RAM_NAMESPACE|RAM_PARTICIPANT|RAM_API_KEY) ;;
    *) fail 'credential file contains an unexpected setting.' ;;
  esac
  case "$seen" in *"|$key|"*) fail 'credential file contains a duplicate setting.' ;; esac
  seen="$seen$key|"
  export "$key=$value"
done < "$credential_file"

for required in RAM_ENDPOINT RAM_STORE_ID RAM_NAMESPACE RAM_PARTICIPANT RAM_API_KEY; do
  case "$seen" in *"|$required|"*) ;; *) fail "credential file is missing $required." ;; esac
done

node_path="$(command -v node || true)"
[[ -n "$node_path" ]] || fail 'Node.js 20 or newer is required.'
exec "$node_path" "$package_root/server/index.cjs"
