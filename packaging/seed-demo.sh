#!/bin/bash
set -euo pipefail

package_root="$HOME/.local/share/redis-shared-memory/editor/current"
credential_file="$HOME/.config/redis-shared-memory/editor.env"

if [[ $# -ne 2 || ( "$1" != 'seed' && "$1" != 'reset' ) || ( "$2" != 'qa' && "$2" != 'demo' ) ]]; then
  printf 'Usage: redis-memory-seed <seed|reset> <qa|demo>\n' >&2
  exit 2
fi
[[ -f "$package_root/FILES.sha256" ]] || { printf 'Editor installation is missing.\n' >&2; exit 1; }
(cd "$package_root" && /usr/bin/shasum -a 256 -c FILES.sha256 >/dev/null) || { printf 'Editor package integrity check failed; reinstall it.\n' >&2; exit 1; }
exec node "$package_root/bin/seed.cjs" "$1" "$2" "$credential_file"
