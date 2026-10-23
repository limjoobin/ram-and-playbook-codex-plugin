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
