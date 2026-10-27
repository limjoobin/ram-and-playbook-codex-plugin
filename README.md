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
- `agenda_prepare`
- `memory_state_update_propose`
- `memory_candidate_list`
- `memory_candidate_inspect`
- `memory_candidate_promote`
- `memory_candidate_reject`

Teams share RAM and Playbook endpoints, a RAM store, and a namespace. Each
person keeps service API keys and a participant value in a private local file.
API keys authenticate requests; the participant value records attribution but
is not proof of identity.

The local MCP server and reviewed capture hooks are dependency-free Python
3.10+ source. Installation does not run a package manager, installer script,
or first-run download. The active hooks capture user prompts and session-end
markers into a per-user private namespace; they never publish shared memory.
When a prompt looks like a lifecycle report, `UserPromptSubmit` tells the agent
to retrieve the exact current state and use `memory_state_update_propose`. That
tool creates a private, source-linked candidate; it does not share anything.
Promotion remains a separate MCP write requiring inspection and explicit
confirmation. `PostToolUse` and `Stop` remain inactive.

## Quality gate

The repository includes a credential-free 15-case evaluation covering normal
agenda generation, stale/conflicted exclusion, insufficient-evidence
abstention, evidence coverage, and exact Playbook attestation:

```sh
python3 evaluation/run.py
```

The committed deterministic result is in
[evaluation/results.json](evaluation/results.json); see
[evaluation/README.md](evaluation/README.md) before changing cases or
thresholds.

## Install

Follow [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md) for Git marketplace and
local-checkout installation, configuration, verification, updates, removal,
and enterprise prerequisites.

## Administrator bootstrap experiment

Repository administrators can inspect the separate versioned RAM/Playbook
bootstrap experiment with `python3 scripts/admin_bootstrap.py plan`. It is never
run by plugin installation or startup. The first adapter is deliberately
read-only and blocks live mutations until the administrator service contracts
are approved; see [docs/admin-bootstrap.md](docs/admin-bootstrap.md) for modes,
upgrade rules, the attestation, and exact human acceptance steps.

## Maintain

Read [AGENTS.md](AGENTS.md) before changing code. Use
[docs/adding-tools.md](docs/adding-tools.md) when adding an MCP tool, and review
[SECURITY.md](SECURITY.md) before changing identity, credentials, permissions,
data scope, or network behavior.

The private-to-shared contract, trust boundary, and manual acceptance cases
are documented in [docs/private-session-promotion.md](docs/private-session-promotion.md).
The central post-extraction projection job is documented in
[docs/management-reconciliation.md](docs/management-reconciliation.md).

The plugin calls reviewed RAM operations directly over HTTPS and allows only
three read-only Playbook MCP operations. `agenda_prepare` loads the exact
published workflow and its required resources at runtime, verifies their
digests, and emits only agenda items backed by traversable source evidence. It
is not a generic HTTP or MCP proxy.

Management state uses two RAM lanes. `organizational_state` is the immutable,
source-linked observation ledger. `organizational_state_projection` is a
deterministic current-state view built by the ingestion pipeline from a
versioned state-family policy. `ram_search_state` returns projections by
default; `view: history` returns the underlying breadcrumbs and `view:
conflicts` returns only unresolved current conflicts. Business ordering uses
the source date, meeting sequence, and transcript-relative offset; RAM creation
time remains system/ingestion time.
