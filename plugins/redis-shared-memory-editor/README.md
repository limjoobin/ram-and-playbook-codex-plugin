# Redis Shared Memory + Playbook

This plugin lets multiple ChatGPT desktop users and their agents work from one
Redis Agent Memory store and namespace. It exposes:

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
- `agenda_prepare`

The MCP server is dependency-free Python 3.10+ source. It has no lifecycle
hook, installer, package-manager step, or runtime download.

Each user creates a private configuration file at:

```text
~/.config/redis-shared-memory/editor.env
```

Users in one collaboration group configure the same `RAM_ENDPOINT`,
`RAM_STORE_ID`, `RAM_NAMESPACE`, `RAM_AGENDA_OWNER_ID`, and
`PLAYBOOK_MCP_URL`. Each user configures their own `RAM_PARTICIPANT` and,
preferably, their own service API keys.

`RAM_API_KEY` and `PLAYBOOK_API_KEY` authenticate requests.
`RAM_PARTICIPANT` is contributor attribution, not verified identity. Never put
the populated file in the repository, plugin cache, or chat.

`agenda_prepare` does not bundle a second copy of the management policy. It
discovers and loads `prepare-management-review-agenda` from Playbook at runtime,
fetches the five required policy resources, verifies every digest, reconciles
RAM lifecycle state, and traverses source evidence before including an item.
Missing, conflicting, terminal, superseded, or uncited candidates are returned
as deferrals or warnings.

See the repository's `CODEX_INSTALLATION.md` for installation and verification.
Maintainers should read `AGENTS.md`, `SECURITY.md`, and
`docs/adding-tools.md` before changing behavior.
