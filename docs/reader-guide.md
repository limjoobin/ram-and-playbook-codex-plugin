# Redis Shared Memory — Reader

The Reader package gives Claude Desktop or Claude Code two local MCP tools: `reader_status` and
`reader_search`. It connects to the same Redis Agent Memory store and namespace
as the Editor package but contains no write tools.

## Install from GitHub for Claude Desktop

Prerequisites are macOS, Claude Desktop opened once, Git, and Node.js 20 or newer.
Claude Code CLI is not required.

```sh
git clone https://github.com/redis-field-engineering/cross-user-ram.git
cd cross-user-ram
./scripts/install-claude-desktop.sh reader
```

Enter the endpoint, store ID, the same namespace as Editor, participant ID
`demo-reader`, and the API key received through the company's approved
secret-sharing method. Fully quit and reopen Claude Desktop after installation,
then run `reader_status`.

## Install the portable Claude Code package

Prerequisites are macOS, Claude Code CLI, and Node.js 20 or newer:

```sh
claude --version
node --version
```

Obtain these two files from Hillary:

- `redis-shared-memory-reader-0.1.1.zip`
- `SHA256SUMS`

Obtain the API key separately through the company's approved secret-sharing
method. Never paste it into chat, email, a repository, or a screenshot.

From the folder containing both files:

```sh
grep 'redis-shared-memory-reader-0.1.1.zip' SHA256SUMS | /usr/bin/shasum -a 256 -c -
/usr/bin/unzip redis-shared-memory-reader-0.1.1.zip -d redis-shared-memory-reader-0.1.1
cd redis-shared-memory-reader-0.1.1
./install.sh
```

Enter the endpoint, store ID, and the same `northstar-pilot-demo` namespace as
the Editor. Use participant ID `demo-reader`. The API-key prompt is hidden. The
installer verifies package contents, the Reader-only tool list, and a real RAM
read before it creates the launcher.

Start Claude Code from the VS Code integrated terminal or any terminal:

```sh
~/.local/bin/redis-memory-reader
```

Then ask:

1. “Run `reader_status` and report the role, namespace, and connection.”
2. “Use shared memory to prepare Northstar Retail's pilot plan. Cite the memory
   IDs you used.”

The status must show `role: reader`, the intended namespace, and
`connection: verified`. A request to change memory must not have a matching tool.

## Reconfigure or uninstall

Run `./install.sh` again from the same verified extracted package to replace the
Reader's local configuration. Uninstall only Reader with:

```sh
~/.local/share/redis-shared-memory/reader/current/uninstall.sh
```

Uninstall removes the Reader launcher, installed files, and its local credential
file. It does not change shared RAM records or remove Editor.

If status fails, share only the package version and sanitized status code. The
credential is stored at `~/.config/redis-shared-memory/reader.env`, outside the
demo workspace, with mode `0600`. Do not open or copy it into chat.

Reader-only behavior is enforced by local tools, not by separate RAM
credentials. Someone holding the shared API key may be able to write through a
different client; this is the accepted boundary for this trusted demo.
