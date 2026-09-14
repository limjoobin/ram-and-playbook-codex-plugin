#!/bin/bash
set -euo pipefail

package_root="$(cd "$(dirname "$0")" && pwd -P)"
target="${1:-}"
credential_tmp=''

fail() {
  printf 'Redis Shared Memory fixture setup: %s\n' "$1" >&2
  exit 1
}
cleanup() {
  [[ -z "$credential_tmp" || ! -e "$credential_tmp" ]] || /bin/rm -f "$credential_tmp"
}
trap cleanup EXIT HUP INT TERM

[[ "$target" = 'qa' || "$target" = 'demo' ]] || fail 'use ./seed.sh qa or ./seed.sh demo.'
[[ "$(uname -s)" = 'Darwin' ]] || fail 'this release supports macOS only.'
command -v node >/dev/null 2>&1 || fail 'install Node.js 20 or newer first.'
node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
[[ "$node_major" -ge 20 ]] || fail 'Node.js 20 or newer is required.'
[[ -f "$package_root/FILES.sha256" ]] || fail 'package checksum manifest is missing.'
(cd "$package_root" && /usr/bin/shasum -a 256 -c FILES.sha256 >/dev/null) || fail 'package integrity check failed; obtain a fresh ZIP.'

namespace='northstar-pilot-demo'
[[ "$target" = 'qa' ]] && namespace='northstar-pilot-qa'
printf 'Seed Redis Shared Memory namespace: %s\n' "$namespace"
printf 'RAM endpoint (https://...): '
IFS= read -r endpoint
printf 'RAM store ID: '
IFS= read -r store_id
printf 'RAM API key (input hidden): '
IFS= read -r -s api_key
printf '\n'
[[ -n "$endpoint" && -n "$store_id" && -n "$api_key" ]] || fail 'all connection values are required.'

credential_tmp="$(mktemp "${TMPDIR:-/tmp}/redis-memory-seed.XXXXXX")"
/bin/chmod 600 "$credential_tmp"
{
  printf 'RAM_ENDPOINT=%s\n' "$endpoint"
  printf 'RAM_STORE_ID=%s\n' "$store_id"
  printf 'RAM_NAMESPACE=%s\n' "$namespace"
  printf 'RAM_PARTICIPANT=northstar-demo-seeder\n'
  printf 'RAM_API_KEY=%s\n' "$api_key"
} > "$credential_tmp"

node "$package_root/bin/seed.cjs" reset "$target" "$credential_tmp"
