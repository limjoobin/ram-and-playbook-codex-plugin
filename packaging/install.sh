#!/bin/bash
set -euo pipefail

role='@@ROLE@@'
title='@@TITLE@@'
version='@@VERSION@@'
package_root="$(cd "$(dirname "$0")" && pwd -P)"
data_root="$HOME/.local/share/redis-shared-memory"
role_root="$data_root/$role"
version_dir="$role_root/$version"
bin_root="$HOME/.local/bin"
launcher="$bin_root/redis-memory-$role"
seed_launcher="$bin_root/redis-memory-seed"
config_root="$HOME/.config/redis-shared-memory"
credential_file="$config_root/$role.env"
stage=''
credential_tmp=''

fail() {
  printf 'Redis Shared Memory %s installer: %s\n' "$title" "$1" >&2
  exit 1
}
cleanup() {
  [[ -z "$stage" || ! -e "$stage" ]] || /bin/rm -rf "$stage"
  [[ -z "$credential_tmp" || ! -e "$credential_tmp" ]] || /bin/rm -f "$credential_tmp"
}
trap cleanup EXIT HUP INT TERM

[[ "$(uname -s)" = 'Darwin' ]] || fail 'this release supports macOS only.'
command -v node >/dev/null 2>&1 || fail 'install Node.js 20 or newer first.'
node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
[[ "$node_major" -ge 20 ]] || fail 'Node.js 20 or newer is required.'
[[ -f "$package_root/FILES.sha256" ]] || fail 'package checksum manifest is missing.'
(cd "$package_root" && /usr/bin/shasum -a 256 -c FILES.sha256 >/dev/null) || fail 'package integrity check failed; obtain a fresh ZIP and verify its release checksum.'

printf 'Redis Shared Memory — %s setup\n' "$title"
printf 'RAM endpoint (https://...): '
IFS= read -r endpoint
printf 'RAM store ID: '
IFS= read -r store_id
printf 'Shared namespace [northstar-pilot-demo]: '
IFS= read -r namespace
namespace="${namespace:-northstar-pilot-demo}"
default_participant='demo-reader'
[[ "$role" = 'editor' ]] && default_participant='hillary'
printf 'Participant ID [%s]: ' "$default_participant"
IFS= read -r participant
participant="${participant:-$default_participant}"
printf 'RAM API key (input hidden): '
IFS= read -r -s api_key
printf '\n'

[[ -n "$endpoint" && -n "$store_id" && -n "$namespace" && -n "$participant" && -n "$api_key" ]] || fail 'all connection values are required.'

if [[ -e "$role_root/current" && ! -L "$role_root/current" ]]; then fail 'current installation marker is not a symlink.'; fi
if [[ -e "$launcher" && ! -L "$launcher" ]]; then fail "$launcher already exists and is not managed by this package."; fi
if [[ "$role" = 'editor' && -e "$seed_launcher" && ! -L "$seed_launcher" ]]; then fail "$seed_launcher already exists and is not managed by this package."; fi

/bin/mkdir -p "$role_root" "$bin_root" "$config_root"
/bin/chmod 700 "$config_root"
stage="$role_root/.install-$$"
credential_tmp="$config_root/.$role.env.$$"
[[ ! -e "$stage" && ! -e "$credential_tmp" ]] || fail 'temporary installation path already exists.'
/bin/mkdir -m 700 "$stage"
/bin/cp -R "$package_root/." "$stage/"
/bin/chmod 755 "$stage/install.sh" "$stage/uninstall.sh" "$stage/bin/redis-memory-$role" "$stage/bin/run-server.sh"
if [[ "$role" = 'editor' ]]; then /bin/chmod 755 "$stage/bin/redis-memory-seed"; fi

umask 077
{
  printf 'RAM_ENDPOINT=%s\n' "$endpoint"
  printf 'RAM_STORE_ID=%s\n' "$store_id"
  printf 'RAM_NAMESPACE=%s\n' "$namespace"
  printf 'RAM_PARTICIPANT=%s\n' "$participant"
  printf 'RAM_API_KEY=%s\n' "$api_key"
} > "$credential_tmp"
/bin/chmod 600 "$credential_tmp"

REDIS_SHARED_MEMORY_CONFIG="$credential_tmp" node "$stage/bin/verify.cjs" "$role" "$stage/bin/run-server.sh" || fail 'connection was not installed; check the values and try again.'

if [[ -e "$version_dir" ]]; then
  [[ -f "$version_dir/manifest.json" ]] || fail 'refusing to replace an unrecognized installation directory.'
  /bin/rm -rf "$version_dir"
fi
/bin/mv "$stage" "$version_dir"
stage=''
/bin/mv "$credential_tmp" "$credential_file"
credential_tmp=''

/bin/ln -sfn "$version_dir" "$role_root/current"
/bin/ln -sfn "$role_root/current/bin/redis-memory-$role" "$launcher"
if [[ "$role" = 'editor' ]]; then /bin/ln -sfn "$role_root/current/bin/redis-memory-seed" "$seed_launcher"; fi

printf '\nInstalled and verified Redis Shared Memory — %s %s.\n' "$title" "$version"
printf 'Start it from VS Code or any terminal with:\n  %s\n' "$launcher"
printf 'Uninstall only this role with:\n  %s\n' "$role_root/current/uninstall.sh"
