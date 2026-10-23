# Codex and ChatGPT desktop installation

This local plugin is a direct Codex packaging of the existing Claude Desktop
Editor MCP server. It supports reads and writes and uses the same external
credential file as an installed Claude Editor.

## Prerequisites

- macOS with Node.js 20 or newer.
- Codex CLI and the ChatGPT desktop app.
- A RAM HTTPS endpoint, store ID, namespace, participant ID, and API key.
- Permission from your enterprise administrator to use this repository as a
  local or Git plugin marketplace and to run its local MCP server.

## 1. Create the local `.env`

Do not put the populated file in the cloned repository.

```sh
mkdir -p "$HOME/.config/redis-shared-memory"
cp plugins/redis-shared-memory-editor/.env.example \
  "$HOME/.config/redis-shared-memory/editor.env"
chmod 600 "$HOME/.config/redis-shared-memory/editor.env"
```

Open `~/.config/redis-shared-memory/editor.env` in a local text editor and fill
in every value. Do not paste the API key into a Codex or ChatGPT conversation.

If the Claude Editor is already installed, this file already exists and Codex
can reuse it without copying the credential into another location.

## 2. Install the repository marketplace

For a local checkout:

```sh
codex plugin marketplace add /absolute/path/to/ram-and-playbook-codex-plugin
```

After this Codex package is merged into the upstream repository, the equivalent
Git-backed command is:

```sh
codex plugin marketplace add redis-field-engineering/ram-and-playbook-codex-plugin
```

Restart the ChatGPT desktop app, open Plugins, choose **Redis Field
Engineering**, and install **Redis Shared Memory — Editor**.

Enterprise policy may reject the marketplace or disable the local MCP server.
That is an administrator policy decision; the plugin does not try to bypass it.

## 3. Verify

Start a new local conversation and ask:

```text
Run editor_status and report the connection, namespace, participant, and permissions.
```

The expected status includes `connection: verified` and permissions for search,
publish, and update. Write tools remain explicit actions and should use Codex's
prompt/approval policy.

## Development

The committed `server/index.cjs` is a dependency-bundled artifact, so installing
the marketplace does not run `npm install`, download code, or execute a package
lifecycle script. Rebuild and verify it from source with:

```sh
npm ci
npm run check
```
