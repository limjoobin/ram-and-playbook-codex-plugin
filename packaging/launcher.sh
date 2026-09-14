#!/bin/bash
set -euo pipefail

role='@@ROLE@@'
title='@@TITLE@@'
role_root="$HOME/.local/share/redis-shared-memory/$role"
package_root="$role_root/current"
runner="$package_root/bin/run-server.sh"

fail() {
  printf 'Redis Shared Memory %s: %s\n' "$title" "$1" >&2
  exit 1
}

[[ $# -eq 0 ]] || fail 'this launcher takes no command-line arguments; start it, then chat interactively.'
[[ "$(uname -s)" = 'Darwin' ]] || fail 'this release supports macOS only.'
command -v claude >/dev/null 2>&1 || fail 'Claude Code CLI is not installed or is not on PATH.'
command -v node >/dev/null 2>&1 || fail 'Node.js 20 or newer is not installed or is not on PATH.'
[[ -x "$runner" ]] || fail 'the installed server is missing; run install.sh again.'

mcp_config="$(mktemp "${TMPDIR:-/tmp}/redis-memory-$role.XXXXXX")"
/bin/rm -f "$mcp_config"
cleanup() { /bin/rm -f "$mcp_config"; }
trap cleanup EXIT HUP INT TERM
node "$package_root/bin/make-config.cjs" "$mcp_config" "$role" "$runner"
instructions="$(/bin/cat "$package_root/demo-workspace/CLAUDE.md")"

permission_mode='manual'
tool_allowlist='mcp__redis-shared-memory-editor__editor_status,mcp__redis-shared-memory-editor__editor_search,mcp__redis-shared-memory-editor__editor_publish,mcp__redis-shared-memory-editor__editor_update'
if [[ "$role" = 'reader' ]]; then
  permission_mode='auto'
  tool_allowlist='mcp__redis-shared-memory-reader__reader_status,mcp__redis-shared-memory-reader__reader_search'
fi

claude \
  --name "Redis Memory $title" \
  --restricted \
  --strict-mcp-config \
  --mcp-config "$mcp_config" \
  --permission-mode "$permission_mode" \
  --tools "$tool_allowlist" \
  --append-system-prompt "$instructions"
