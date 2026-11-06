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

The MCP server is Python 3.11+ source on the pinned redis-iris SDK. On first
launch (or `server/launch.py --install`), `server/launch.py` installs the
exact pins in `server/requirements.txt` once into a private virtual
environment under the plugin data directory; this needs HTTPS access to the
Python package index. The reviewed session-capture hooks are standard-library
only and never load the SDK: they queue each private event locally and the
running MCP server, which loads the SDK once, delivers it to RAM. Version
0.13.0 is macOS/Linux only.
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

Users in one collaboration group configure the same
`IRIS_AGENT_MEMORY_URL`, `IRIS_AGENT_MEMORY_STORE_ID`, `RAM_NAMESPACE`,
`RAM_AGENDA_OWNER_ID`, `IRIS_AGENT_PLAYBOOKS_URL` (base URL only), and
`IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID`. Each user configures their own `RAM_PERSONAL_NAMESPACE`,
`RAM_PARTICIPANT`, and,
preferably, their own service API keys.

`IRIS_AGENT_MEMORY_API_KEY` and `IRIS_AGENT_PLAYBOOKS_API_KEY` (a reader key)
authenticate requests.
`RAM_PARTICIPANT` is contributor attribution, not verified identity. Never put
the populated file in the repository, plugin cache, or chat.

An environment administrator may also keep the optional names
`IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY`, `IRIS_AGENT_PLAYBOOKS_SERVICE_URL`,
`IRIS_AGENT_PLAYBOOKS_SERVICE_TOKEN`, `IRIS_AGENT_MEMORY_SERVICE_URL`, and
`IRIS_AGENT_MEMORY_SERVICE_TOKEN` in this same private prototype file. The
desktop MCP accepts but does not retain them in its runtime configuration.
Ordinary participant installations leave them unset. The pre-0.13.0 names are
rejected; see "Upgrading from 0.12.x" in `CODEX_INSTALLATION.md`.

`agenda_prepare` does not bundle a second copy of the management policy. It
discovers and loads `prepare-management-review-agenda` from Playbook at runtime,
fetches the five required policy resources, verifies every digest, retrieves
deterministic current projections, and traverses their immutable supporting
observations before including a topic. It then runs a bounded read-only second
pass over first-pass conflicts and distinguishes later-evidence reconciliation
from genuinely unresolved or ambiguous conflicts. Missing owners, impact
statements, and requested-decision fields remain visible rather than suppressing
the draft. `ram_search_state` also exposes an explicit `history` view for
source-event breadcrumbs and a `conflicts` view for registered unresolved
current projections.

Session events first enter RAM under `RAM_PERSONAL_NAMESPACE`, where RAM owns
native session memory and any configured personal extraction. The local
candidate ledger is only a bounded review queue. `memory_candidate_promote`
does not move or mutate private memory: it writes the confirmed, already
structured `organizational_state` observation directly with deterministic
provenance and verifies it by exact ID. MemoryETL is not used for this path.
The repository's central reconciliation job then applies the single versioned
projector; it is deliberately not run independently by every
desktop plugin.

`ram_get_evidence` accepts a returned source ID for document evidence. For a
confirmed human promotion, it accepts the exact returned memory ID without a
source ID and exposes the scoped immutable observation as evidence. Agenda
progress therefore cites the human completion report itself as well as any
earlier document evidence.

See the repository's `CODEX_INSTALLATION.md` for installation and verification.
Maintainers should read `AGENTS.md`, `SECURITY.md`, and
`docs/adding-tools.md` before changing behavior.
