# Cross-user Redis Agent Memory demo

This project connects desktop AI clients to the same Redis Agent Memory store
through local MCP servers:

- **Editor:** search, publish, and update shared memories.
- **Reader:** search shared memories without write tools.

The original Reader and Editor packages use Claude Desktop's
`claude_desktop_config.json`. The Codex/ChatGPT desktop plugin currently exposes
the write-capable Editor tools through a native repository marketplace. Both
clients reuse credentials stored outside this repository.

## Get started

Follow the [installation guide](INSTALLATION.md) to clone the repository and
install either role.

For Codex and ChatGPT desktop, follow the
[Codex installation guide](CODEX_INSTALLATION.md). The Codex package uses a
manually populated `.env` and does not run the Claude installer.

Use the [runbook](RUNBOOK.md) to verify the connection, seed demo data, run the
cross-user demonstration, troubleshoot, or uninstall.

Only use fictional data in this demo. Reader is enforced at the MCP-tool level;
the underlying shared RAM credential may have broader permissions.

## Extending the desktop plugin

Coding agents should start with [AGENTS.md](AGENTS.md). The detailed
[tool-extension guide](docs/adding-tools.md) explains where to implement a new
operation, how to describe and annotate it, which security boundaries must stay
fixed, and which tests and generated artifacts to update. Review
[SECURITY.md](SECURITY.md) before adding credentials, permissions, data types,
network destinations, or write behavior.

The desktop plugin runtime is readable Python under
`plugins/redis-shared-memory-editor/server/`. It uses only the Python standard
library, so installation does not run `pip install`, `npm install`, a package
lifecycle hook, or a first-run download. The inherited Claude packages remain
TypeScript and use the official Redis Agent Memory SDK; they are maintained as
a separate distribution path.

For this local POC, the Python runtime implements only the reviewed MCP stdio
methods and RAM HTTPS operations it needs. It starts Python in isolated mode so
user-site packages and `PYTHONPATH` cannot alter the plugin. A future managed
deployment can adopt the official Python SDKs once their locked dependencies
have an approved distribution path; it must not download them during startup.

Python changes the runtime prerequisite, not the enterprise trust boundary.
The local MCP server still executes code on the user's computer and makes
authenticated HTTPS requests to the configured Redis endpoint.
