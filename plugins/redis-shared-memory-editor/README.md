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
- `memory_state_update_propose`
- `memory_candidate_list`
- `memory_candidate_inspect`
- `memory_candidate_promote`
- `memory_candidate_reject`

The MCP server and reviewed session-capture hooks are dependency-free Python
3.10+ source. It has no installer, package-manager step, or runtime download.
The active `UserPromptSubmit` and `SessionEnd` hooks write only to the
configured personal namespace. Automatic candidate creation is paused while
`PostToolUse` and `Stop` are inactive. A likely lifecycle report instead causes
`UserPromptSubmit` to guide the agent toward `memory_state_update_propose`,
which verifies the exact current state and creates a private candidate from the
exact captured prompt.

Each user creates a private configuration file at:

```text
~/.config/redis-shared-memory/editor.env
```

Users in one collaboration group configure the same `RAM_ENDPOINT`,
`RAM_STORE_ID`, `RAM_NAMESPACE`, `RAM_AGENDA_OWNER_ID`, and
`PLAYBOOK_MCP_URL`. Each user configures their own `RAM_PERSONAL_NAMESPACE`,
`RAM_PARTICIPANT`, and,
preferably, their own service API keys.

`RAM_API_KEY` and `PLAYBOOK_API_KEY` authenticate requests.
`RAM_PARTICIPANT` is contributor attribution, not verified identity. Never put
the populated file in the repository, plugin cache, or chat.

`agenda_prepare` does not bundle a second copy of the management policy. It
discovers and loads `prepare-management-review-agenda` from Playbook at runtime,
fetches the five required policy resources, verifies every digest, reconciles
RAM lifecycle state through deterministic current projections, and traverses
their immutable supporting observations before including an item. Missing,
conflicting, terminal, superseded, or uncited candidates are returned as
deferrals or warnings. `ram_search_state` also exposes an explicit `history`
view for source-event breadcrumbs and a `conflicts` view for unresolved current
projections.

Session events first enter RAM under `RAM_PERSONAL_NAMESPACE`, where RAM owns
native session memory and any configured personal extraction. The local
candidate ledger is only a bounded review queue. `memory_candidate_promote`
does not move or mutate private memory: it appends a new, confirmed shared
session observation with deterministic provenance and lets RAM's
`organizational_state` custom extractor create the shared observation.
The repository's central reconciliation job then applies the single versioned
projector after extraction; it is deliberately not run independently by every
desktop plugin.

See the repository's `CODEX_INSTALLATION.md` for installation and verification.
Maintainers should read `AGENTS.md`, `SECURITY.md`, and
`docs/adding-tools.md` before changing behavior.
