#!/bin/bash
set -euo pipefail

role='@@ROLE@@'
title='@@TITLE@@'
role_root="$HOME/.local/share/redis-shared-memory/$role"
launcher="$HOME/.local/bin/redis-memory-$role"
seed_launcher="$HOME/.local/bin/redis-memory-seed"
credential_file="$HOME/.config/redis-shared-memory/$role.env"

fail() {
  printf 'Redis Shared Memory %s uninstaller: %s\n' "$title" "$1" >&2
  exit 1
}

[[ "$role_root" = "$HOME/.local/share/redis-shared-memory/$role" ]] || fail 'unexpected installation path.'
[[ -f "$role_root/current/manifest.json" ]] || fail 'no recognized current installation was found.'

desktop_configurator="$role_root/current/bin/configure-desktop.cjs"
if [[ -f "$desktop_configurator" ]]; then
  node_path="$(command -v node || true)"
  [[ -n "$node_path" ]] || fail 'Node.js is required to remove the Claude Desktop entry safely.'
  "$node_path" "$desktop_configurator" remove "$role"
fi

if [[ -L "$launcher" ]]; then
  case "$(/usr/bin/readlink "$launcher")" in "$role_root/"*) /bin/rm -f "$launcher" ;; *) fail 'refusing to remove an unrelated launcher.' ;; esac
elif [[ -e "$launcher" ]]; then
  fail 'refusing to remove an unrelated launcher file.'
fi

if [[ "$role" = 'editor' && -L "$seed_launcher" ]]; then
  case "$(/usr/bin/readlink "$seed_launcher")" in "$role_root/"*) /bin/rm -f "$seed_launcher" ;; *) fail 'refusing to remove an unrelated seed launcher.' ;; esac
elif [[ "$role" = 'editor' && -e "$seed_launcher" ]]; then
  fail 'refusing to remove an unrelated seed launcher file.'
fi

if [[ -L "$credential_file" ]]; then fail 'refusing to remove a symlinked credential file.'; fi
[[ ! -e "$credential_file" ]] || /bin/rm -f "$credential_file"
/bin/rm -rf "$role_root"
printf 'Removed Redis Shared Memory — %s local files and credential. Shared RAM records were not changed.\n' "$title"
