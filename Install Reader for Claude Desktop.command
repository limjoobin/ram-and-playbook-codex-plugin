#!/bin/bash

root="$(cd "$(dirname "$0")" && pwd -P)"
/bin/bash "$root/scripts/install-claude-desktop.sh" reader
status=$?
printf '\nPress Return to close this window.\n'
IFS= read -r _
exit "$status"
