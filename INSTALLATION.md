# Installation guide

These instructions install either the Reader or Editor as a local MCP server in
Claude Desktop on macOS.

## Before you start

Install these prerequisites:

1. Git.
2. Node.js 20 or newer.
3. Claude Desktop. Open it once before continuing.

Obtain the following from the demo owner:

- RAM HTTPS endpoint.
- RAM store ID.
- Shared namespace. Reader and Editor must use exactly the same value.
- RAM API key, sent through an approved secret-sharing method.

Do not paste the API key into Claude, email, or a GitHub repository.

## 1. Clone the repository

```sh
git clone https://github.com/redis-field-engineering/ram-and-playbook-codex-plugin.git
cd ram-and-playbook-codex-plugin
```

## 2. Install one role

### Reader

```sh
./scripts/install-claude-desktop.sh reader
```

Use participant ID `demo-reader` when prompted.

### Editor

```sh
./scripts/install-claude-desktop.sh editor
```

Use your name or another agreed contributor ID when prompted.

For either role, enter the supplied endpoint, store ID, shared namespace, and
API key. The API-key prompt hides the value while you type.

The installer:

1. Builds and verifies the local MCP server.
2. Performs a real RAM connection check.
3. Preserves existing MCP entries and adds only the selected role to
   `~/Library/Application Support/Claude/claude_desktop_config.json`.
4. Stores credentials at `~/.config/redis-shared-memory/<role>.env` with mode
   `0600`.

## 3. Restart Claude Desktop

Fully quit Claude Desktop, then reopen it. Closing only the window is not
enough.

## 4. Verify the installation

In a new Claude Desktop conversation, ask:

### Reader

```text
Run reader_status. Report the role, connection, namespace, participant, and permissions.
```

### Editor

```text
Run editor_status. Report the role, connection, namespace, participant, and permissions.
```

The result should report `connection: verified` and the intended role and
namespace. Continue with the [runbook](RUNBOOK.md).
