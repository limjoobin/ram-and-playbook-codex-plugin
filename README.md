# Redis Shared Memory + Playbook management-agenda PoC

This repository packages an installable ChatGPT desktop plugin and a versioned
context model for one experiment: turn meeting evidence and human-confirmed
work updates into an evidence-backed management-review agenda.

For a clean-machine handover, start with [HANDOVER.md](HANDOVER.md). It
distinguishes the stable context pipeline from the small RAM/Playbook service
adapters that may need adjustment when a service release changes its API.

The plugin exposes Redis Agent Memory (RAM) and Redis Agent Playbook through one
local MCP server. Multiple people can install the same plugin, connect to the
same RAM store and Playbook, inspect shared organizational state, publish
reviewed updates, and prepare a human-editable agenda from the same evidence.

## Management-agenda use case

Management-review preparation usually requires reconstructing what was
decided, what remains open, who owns it, which risks or dependencies matter,
and whether later evidence superseded an earlier statement. This PoC tests
whether RAM can retain that organizational history and whether one Playbook
Skill can turn its current state into a consistent agenda without hiding the
underlying evidence.

The output is a draft for a human chair. It does not send email, update a
calendar, or publish meeting material.

## Real Reaction scenario and source corpus

The demo uses the text-based ES2002 scenario from the
[AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/). Four people play
the project manager, marketing expert, industrial designer, and user-interface
designer for the fictional Real Reaction team while designing a new remote
control over four meetings.

The prepared shared demo environment was built from 15 text artifacts:

- four meeting transcripts;
- four minutes documents;
- one final report;
- one agenda; and
- five presentations.

Audio, video, image, whiteboard, and pen data are excluded. RAM MemoryETL
ingested the normalized text artifacts and retained source identities,
revisions, evidence locations, and ingestion provenance.

The repository deliberately checks in only a two-document bootstrap smoke
subset—kickoff minutes and the final report—to keep bootstrap tests fast. It is
not intended to recreate the complete prepared demo corpus. See the
[corpus manifest](context-models/management-agenda/v1/corpus/manifest.json) and
[demo runbook](docs/management-agenda-demo-runbook.md).

## Architecture

```text
AMI text artifacts ──► RAM MemoryETL ──► organizational_state observations
                                               │
Human prompt ──► private hooks ──► reviewed promotion
                                               │
                                               ▼
                                  reconciliation / projector
                                               │
                                               ▼
                                  current-state projections
                                               │
                         RAM evidence + Playbook Skill
                                               │
                                               ▼
                                    draft management agenda
```

The desktop plugin owns the local MCP surface. RAM and Playbook remain separate
services and must be deployed and configured before installing the plugin.

## Context model and extraction

Source extraction uses one custom memory type, `organizational_state`. Its
`state_kind` distinguishes:

- `action_item`;
- `decision`;
- `risk`;
- `issue`;
- `dependency`;
- `approval`; and
- `conflict`.

These records form an immutable, source-linked observation ledger. A second
derived type, `organizational_state_projection`, contains the deterministic
current view. Keeping observations and projections separate preserves history
while allowing the current state to be rebuilt whenever the policy changes.

The extraction prompt begins:

> Extract only explicit, management-relevant organizational state from this
> document. Return one observation for each grounded action item, decision,
> risk, issue, dependency, approval, or unresolved factual conflict. Never
> infer urgency, ownership, dates, impact, or a requested management decision.

The [complete extraction prompt](context-models/management-agenda/v1/extraction-prompt.txt),
[observation schema](context-models/management-agenda/v1/memory-types/organizational-state.json),
[projection schema](context-models/management-agenda/v1/memory-types/organizational-state-projection.json),
entity registry, and projection policy are versioned together under
`context-models/management-agenda/v1`.

Generic relationships live with observations under `relations.edges`.
Supported predicates include `fulfills`, `resolves`, `supersedes`, `blocks`,
`depends_on`, `conflicts_with`, and `supports`. The application-owned projector
applies only confirmed relationships and narrow versioned policy rules when it
rebuilds current state. RAM stores the evidence and derived projections; it
does not natively implement this management-specific lifecycle policy.

## Playbook Skill and agenda generation

The PoC publishes one Skill,
[`prepare-management-review-agenda`](context-models/management-agenda/v1/playbook/SKILL.md).
Its linked resources define the meeting charter, qualification rules, output
schema, evidence lifecycle, conflict treatment, and abstention behavior.
Business rules remain in Playbook resources rather than being copied into the
application prompt.

`agenda_prepare` loads and verifies the exact published Skill and resource
digests at runtime. It enumerates the structured current-state register by
state kind, traverses RAM evidence, and performs a bounded read-only second
pass over possible conflicts. It returns action, completion, decision, open
work, and conflict registers separately from the ordered agenda topics.

## Human updates, hooks, and reconciliation

The active `UserPromptSubmit` and `SessionEnd` hooks append bounded events only
to a per-user private RAM namespace. Hooks never publish shared organizational
state.

When a person explicitly reports a lifecycle change, the agent retrieves the
exact current state and creates a private review candidate. The person inspects
and confirms that candidate before `memory_candidate_promote` writes one
immutable shared `organizational_state` observation. This already-structured
human update is written directly to RAM; it does not pass through document
MemoryETL.

One central idempotent reconciliation job reads the complete observation lane,
applies relationship and lifecycle policy, and upserts only changed current
projections. The PoC runs it every five minutes from one pinned scheduler
checkout. It is not installed independently by every plugin user. See
[management-state reconciliation](docs/management-reconciliation.md) and
[private session promotion](docs/private-session-promotion.md).

## What this repository contains

- the dependency-free Python 3.10+ local MCP plugin;
- the two reviewed private-capture hooks;
- the versioned RAM schemas, extraction prompt, entities, projection policy,
  and canonical projector;
- the Playbook Skill and its resources;
- the two-document bootstrap smoke corpus;
- deterministic source-envelope rendering, expected MemoryETL output, and an
  offline end-to-end context validator;
- an explicit plan/confirm/verify reset command for a non-production RAM store;
- a bounded MemoryETL corpus submission command;
- a credential-free 15-case agenda evaluation; and
- installation, administration, security, reconciliation, and demo guidance.

The MCP surface is intentionally bounded:

| Capability | Tools |
| --- | --- |
| Connection and team facts | `editor_status`, `editor_search`, `editor_publish`, `editor_update`, `system_status` |
| Organizational state | `context_resolve_entities`, `ram_search_state`, `ram_get_evidence` |
| Playbook and agenda | `playbook_discover`, `playbook_load_skill`, `playbook_fetch_resource`, `agenda_prepare` |
| Private-to-shared review | `memory_state_update_propose`, `memory_candidate_list`, `memory_candidate_inspect`, `memory_candidate_promote`, `memory_candidate_reject` |

The runtime is not a generic HTTP or MCP proxy. It performs only reviewed RAM
operations and three read-only Playbook MCP operations.

## External prerequisites

Provision or deploy these separately:

- a RAM service with an endpoint, store, API key, management owner lane,
  configured custom memory types, and MemoryETL;
- a Playbook service with the agenda Skill published and a readable MCP
  endpoint;
- one shared namespace plus a distinct private namespace per participant; and
- one central host for the five-minute reconciliation scheduler.

Every user supplies the shared endpoints and scope plus private service keys
and a participant value in `~/.config/redis-shared-memory/editor.env`. API keys
authenticate requests. The participant value records attribution but is not
proof of identity.

Installing the plugin does not provision RAM or Playbook, publish the Skill,
declare custom memory types, or start a scheduler. The service-independent
context contract is executable offline; RAM control-plane declarations and
Playbook publication still use the supported administrator surface for the
deployed release. The current configured-services bootstrap adapter remains
read-only rather than guessing those release-specific contracts.

## Install and run the demo

1. An environment administrator follows
   [DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md) to prepare RAM,
   Playbook, MemoryETL ingestion, and central reconciliation.
2. Each participant follows [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md) for
   Git marketplace or local-checkout installation, private configuration,
   manual hook trust, verification, updates, and removal.
3. Use [the management-agenda demo runbook](docs/management-agenda-demo-runbook.md)
   for the human test flow.

Before connecting to any service, validate the entire checked-in context path:

```sh
python3 scripts/validate_context_pipeline.py
```

This renders the exact MemoryETL source envelopes, validates all 24 custom
memory attributes, loads deterministic expected extraction output, runs the
real projector, and verifies representative current-state cases. It does not
use credentials or modify a service.

The repository bootstrap can be inspected without writing to either service:

```sh
python3 scripts/admin_bootstrap.py plan
```

## Quality gate

The credential-free 15-case evaluation covers agenda generation,
terminal-state exclusion, unresolved conflicts, owner gaps, missing-source
abstention, evidence coverage, and exact Playbook attestation:

```sh
python3 evaluation/run.py
```

The committed deterministic result is in
[evaluation/results.json](evaluation/results.json). Read
[evaluation/README.md](evaluation/README.md) before changing cases or
thresholds.

## PoC boundaries

- One management forum and the AMI ES2002 project are modelled.
- Context Retriever and Context Surfaces are not deployed or evaluated.
- The evaluation supports a quality claim, not a scale or performance claim.
- Agenda output remains a human-editable draft.
- Participant attribution is not server-validated identity.
- The checked-in corpus is a fast two-document smoke subset; the prepared demo
  environment contains the broader 15-artifact research corpus.

## Maintain

Read [AGENTS.md](AGENTS.md) before changing code. Use
[docs/adding-tools.md](docs/adding-tools.md) when adding an MCP tool, and review
[SECURITY.md](SECURITY.md) before changing identity, credentials, permissions,
data scope, or network behavior.

The administrator/user handoff is defined in
[DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md) and
[CODEX_INSTALLATION.md](CODEX_INSTALLATION.md). The bootstrap harness's current
read-only adapter boundary is documented in
[docs/admin-bootstrap.md](docs/admin-bootstrap.md).

The private-to-shared trust boundary and acceptance cases are in
[docs/private-session-promotion.md](docs/private-session-promotion.md). The
central observation-projection job is documented in
[docs/management-reconciliation.md](docs/management-reconciliation.md).
