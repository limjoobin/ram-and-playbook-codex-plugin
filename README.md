# Cross-user Redis Agent Memory demo

This project connects two Claude Desktop users to the same Redis Agent Memory
store through local MCP servers:

- **Editor:** search, publish, and update shared memories.
- **Reader:** search shared memories without write tools.

Both roles use Claude Desktop's `claude_desktop_config.json`. Credentials are
stored outside this repository and are never written to that JSON file.

## Get started

Follow the [installation guide](INSTALLATION.md) to clone the repository and
install either role.

Use the [runbook](RUNBOOK.md) to verify the connection, seed demo data, run the
cross-user demonstration, troubleshoot, or uninstall.

Only use fictional data in this demo. Reader is enforced at the MCP-tool level;
the underlying shared RAM credential may have broader permissions.
