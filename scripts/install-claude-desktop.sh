#!/bin/bash
set -euo pipefail

role="${1:-reader}"
case "$role" in reader|editor) ;; *) printf 'Usage: %s [reader|editor]\n' "$0" >&2; exit 2 ;; esac

root="$(cd "$(dirname "$0")/.." && pwd -P)"
stage=''

fail() { printf 'Claude Desktop %s installer: %s\n' "$role" "$1" >&2; exit 1; }
cleanup() { [[ -z "$stage" || ! -e "$stage" ]] || /bin/rm -rf "$stage"; }
trap cleanup EXIT HUP INT TERM

[[ "$(uname -s)" = 'Darwin' ]] || fail 'this release supports macOS only.'
command -v node >/dev/null 2>&1 || fail 'Node.js 20 or newer is required.'
command -v npm >/dev/null 2>&1 || fail 'npm is required to build the cloned source.'
node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
[[ "$node_major" -ge 20 ]] || fail 'Node.js 20 or newer is required.'
version="$(cd "$root" && node -p 'require("./package.json").version' 2>/dev/null || true)"
[[ -n "$version" ]] || fail 'could not read the project version.'
name="redis-shared-memory-$role"
artifact="$root/dist/claude-code/$name-$version.zip"

if [[ ! -d "$HOME/Library/Application Support/Claude" ]]; then
  fail 'open Claude Desktop once before installing this connector.'
fi

printf 'Installing dependencies from the locked package manifest...\n'
(cd "$root" && npm ci)
printf 'Building verified Reader and Editor packages from source...\n'
(cd "$root" && npm run build)

[[ -f "$artifact" ]] || fail 'the expected build artifact was not produced.'
(cd "$(dirname "$artifact")" && /usr/bin/grep "  $(basename "$artifact")$" SHA256SUMS | /usr/bin/shasum -a 256 -c -) \
  || fail 'the built package checksum did not verify.'

stage="$(mktemp -d "${TMPDIR:-/tmp}/redis-memory-$role.XXXXXX")"
/usr/bin/unzip -q "$artifact" -d "$stage"
/bin/bash "$stage/install.sh"

node "$HOME/.local/share/redis-shared-memory/$role/current/bin/configure-desktop.cjs" add "$role"
printf '\nRedis Shared Memory — %s is installed for Claude Desktop.\n' "$role"
printf 'Fully quit and reopen Claude Desktop, then run the %s_status tool.\n' "$role"
