# Redis Shared Memory — Editor

The Editor package gives Claude Code `editor_status`, `editor_search`,
`editor_publish`, and `editor_update`. It connects to the same Redis Agent
Memory store and namespace as Reader.

## Install on Hillary's Mac

Confirm macOS prerequisites:

```sh
claude --version
node --version
```

From the folder containing `redis-shared-memory-editor-0.1.1.zip` and
`SHA256SUMS`:

```sh
grep 'redis-shared-memory-editor-0.1.1.zip' SHA256SUMS | /usr/bin/shasum -a 256 -c -
/usr/bin/unzip redis-shared-memory-editor-0.1.1.zip -d redis-shared-memory-editor-0.1.1
cd redis-shared-memory-editor-0.1.1
./install.sh
```

Enter the RAM endpoint, store ID, `northstar-pilot-demo`, participant ID
`hillary`, and the API key. The key prompt is hidden. The installer performs a
real RAM read and creates no project or user MCP registration.

Start from VS Code's integrated terminal or any terminal:

```sh
~/.local/bin/redis-memory-editor
```

Ask Claude to run `editor_status`. Search before publishing or updating. For an
existing requirement, call `editor_update` with the exact retrieved memory ID.
Only `saved_and_searchable` means it is ready for the Reader demonstration.
`saved_search_pending` requires another search; `write_unverified` requires
reconciliation and must not be automatically retried.

The launcher uses Claude Code's manual permission mode so writes remain visible
for approval. No delete, automatic capture, generic HTTP, filesystem, or shell
tool is included.

## Reconfigure or uninstall

Run `./install.sh` again from the verified extracted Editor package to update its
configuration. Uninstall only Editor with:

```sh
~/.local/share/redis-shared-memory/editor/current/uninstall.sh
```

This removes Editor's launcher, files, and credential without changing shared
RAM memories or the Reader installation.
