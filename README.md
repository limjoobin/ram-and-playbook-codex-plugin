# Redis Shared Memory desktop plugin

This repository contains one installable ChatGPT desktop plugin. It gives every
installed user and agent the same four Redis Agent Memory tools:

- `editor_status`
- `editor_search`
- `editor_publish`
- `editor_update`

Teams share a RAM endpoint, store, and namespace. Each person keeps their own
API key and participant value in a private local file. The API key
authenticates the request; the participant value records attribution but is not
proof of identity.

The local MCP server is dependency-free Python 3.10+ source. Installation does
not run a package manager, installer script, lifecycle hook, or first-run
download.

## Install

Follow [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md) for Git marketplace and
local-checkout installation, configuration, verification, updates, removal,
and enterprise prerequisites.

## Maintain

Read [AGENTS.md](AGENTS.md) before changing code. Use
[docs/adding-tools.md](docs/adding-tools.md) when adding an MCP tool, and review
[SECURITY.md](SECURITY.md) before changing identity, credentials, permissions,
data scope, or network behavior.

The plugin currently implements the reviewed RAM operations directly over
HTTPS. It is not a generic MCP proxy, and it does not yet expose Playbook
operations. Add Playbook only from an authoritative API contract with its own
authorization and tests.
