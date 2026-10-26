# Redis Shared Memory desktop plugin

This repository contains one installable ChatGPT desktop plugin. It gives every
installed user and agent the same local MCP surface over a shared Redis Agent
Memory store and Redis Agent Playbook:

- `editor_status`
- `editor_search`
- `editor_publish`
- `editor_update`
- `system_status`
- `context_resolve_entities`
- `ram_search_state`
- `ram_get_evidence`
- `playbook_discover`
- `playbook_load_skill`
- `playbook_fetch_resource`

Teams share RAM and Playbook endpoints, a RAM store, and a namespace. Each
person keeps service API keys and a participant value in a private local file.
API keys authenticate requests; the participant value records attribution but
is not proof of identity.

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

The plugin calls reviewed RAM operations directly over HTTPS and allows only
three read-only Playbook MCP operations. It is not a generic HTTP or MCP proxy.
