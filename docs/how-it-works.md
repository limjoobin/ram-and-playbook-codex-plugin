# How it works

This is the technical overview of the management-agenda proof of concept. New
users should start with the [README](../README.md); administrators preparing
the shared environment should read [DEMO_ENVIRONMENT_SETUP.md](../DEMO_ENVIRONMENT_SETUP.md)
and [HANDOVER.md](../HANDOVER.md).

The repository packages an installable ChatGPT desktop plugin and a versioned
context model for one experiment: turn meeting evidence and human-confirmed
work updates into an evidence-backed management-review agenda.

The plugin exposes Redis Agent Memory (RAM) and Redis Agent Playbook through one
local MCP server. Multiple people can install the same plugin, connect to the
same RAM store and Playbook, inspect shared organizational state, publish
reviewed updates, and prepare a human-editable agenda from the same evidence.
For a clean-machine handover, [HANDOVER.md](../HANDOVER.md) distinguishes the
stable context pipeline from the small RAM/Playbook service adapters that may
need adjustment when a service release changes its API.

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

The repository deliberately checks in only a small bootstrap smoke corpus to
keep bootstrap tests fast: the AMI kick-off minutes and final report, plus one
short synthetic action log, `demo-es2002-functional-design-actions`, written for
the guided tour so that each demo participant owns an open action. The
synthetic document is marked as such in the corpus manifest and is not part of
the AMI corpus. The smoke corpus is not intended to recreate the complete
prepared demo corpus. See the
[corpus manifest](../context-models/management-agenda/v1/corpus/manifest.json) and
[demo runbook](management-agenda-demo-runbook.md).

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

The [complete extraction prompt](../context-models/management-agenda/v1/extraction-prompt.txt),
[observation schema](../context-models/management-agenda/v1/memory-types/organizational-state.json),
[projection schema](../context-models/management-agenda/v1/memory-types/organizational-state-projection.json),
entity registry, and projection policy are versioned together under
`context-models/management-agenda/v1`.

Generic relationships live with observations under `relations.edges`.
Supported predicates include `fulfills`, `resolves`, `supersedes`, `blocks`,
`depends_on`, `conflicts_with`, and `supports`. The application-owned projector
applies only confirmed relationships and narrow versioned policy rules when it
rebuilds current state. RAM stores the evidence and derived projections; it
does not natively implement this management-specific lifecycle policy.

### Storage layouts

The management code always works with flat records on two logical types. RAM
stores them in one of two layouts, chosen per store with `RAM_MEMORY_LAYOUT`:

- `compact` (default): one custom type, `organizational_state`, with nine
  fields. The seven fields that searches filter on (`schema_version`,
  `state_kind`, `lifecycle_status`, `project_id`, `meeting_id`,
  `accountable_entity_id`, `conflict_status`) stay top level, `record_kind`
  distinguishes observations from projections, and every other attribute lives
  in one `details` object. It is small enough to enter in the Redis Cloud
  console, the only way to register custom types there today.
- `expanded`: the original two types with every attribute as its own field.

`RAMClient` encodes writes and search filters for the configured layout and
decodes every read, so the projector, agenda, promotion, and reconciliation are
unchanged. A compact-layout search on an attribute inside `details` fails
closed with `ram_contract_error`.

## Playbook Skill and agenda generation

The PoC publishes one Skill,
[`prepare-management-review-agenda`](../context-models/management-agenda/v1/playbook/SKILL.md).
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
state. They use only the Python standard library: each queues its private
event locally, and the running MCP server, which loads the redis-iris SDK once,
delivers it to RAM.

When a person explicitly reports a lifecycle change, the agent retrieves the
exact current state and creates a private review candidate. The person inspects
and confirms that candidate before `memory_candidate_promote` writes one
immutable shared `organizational_state` observation. This already-structured
human update is written directly to RAM; it does not pass through document
MemoryETL.

Right after the write, the plugin runs the idempotent reconciliation code: it
reads the complete observation lane, applies relationship and lifecycle policy,
and writes only changed current projections, so the update reaches the team's
current view at once. Replacements name the revision they read, so two people
publishing at the same moment cannot overwrite each other; the loser reads
again and retries. The setup command and an administrator script run the same
code after document ingestion. See
[management-state reconciliation](management-reconciliation.md) and
[private session promotion](private-session-promotion.md).

## What this repository contains

- the Python 3.11+ local MCP plugin on the pinned redis-iris SDK;
- the two reviewed private-capture hooks;
- the versioned RAM schemas, extraction prompt, entities, projection policy,
  and canonical projector;
- the Playbook Skill and its resources;
- the three-document bootstrap smoke corpus;
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
operations through the redis-iris SDK and three read-only Playbook REST reads
through the same SDK.

## External prerequisites

Provision or deploy these separately:

- a RAM service with an endpoint, store, API key, configured custom memory
  types, and MemoryETL;
- a Playbook with the agenda Skill published and a readable data-plane REST
  endpoint, playbook ID, and reader key;
- one shared namespace for every management record (documents, published
  updates, and the current view), plus a distinct private namespace per
  participant. Each record's `ownerId` is the participant who wrote it.

Every user supplies the shared endpoints and scope plus private service keys
and a participant value in `~/.config/redis-shared-memory/editor.env`. API keys
authenticate requests. The participant value records attribution but is not
proof of identity.

Installing the plugin does not provision RAM or Playbook, publish the Skill,
or declare custom memory types. The service-independent
context contract is executable offline; RAM control-plane declarations and
Playbook publication still use the supported administrator surface for the
deployed release. The current configured-services bootstrap adapter remains
read-only rather than guessing those release-specific contracts.

## Developer environment and offline checks

Administrator and developer commands need the SDK. Create a development
environment once (`.venv/` is gitignored; Python 3.11+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r plugins/redis-shared-memory-editor/server/requirements.txt
```

Before connecting to any service, validate the entire checked-in context path:

```sh
.venv/bin/python scripts/validate_context_pipeline.py
```

This renders the exact MemoryETL source envelopes, validates all 24 custom
memory attributes, loads deterministic expected extraction output, runs the
real projector, and verifies representative current-state cases. It does not
use credentials or modify a service.

The repository bootstrap can be inspected without writing to either service:

```sh
.venv/bin/python scripts/admin_bootstrap.py plan
```

## Quality gate

The credential-free 15-case evaluation covers agenda generation,
terminal-state exclusion, unresolved conflicts, owner gaps, missing-source
abstention, evidence coverage, and exact Playbook attestation:

```sh
.venv/bin/python evaluation/run.py
```

The committed deterministic result is in
[evaluation/results.json](../evaluation/results.json). Read
[evaluation/README.md](../evaluation/README.md) before changing cases or
thresholds.

## PoC boundaries

- One management forum and the AMI ES2002 project are modelled.
- Context Retriever and Context Surfaces are not deployed or evaluated.
- The evaluation supports a quality claim, not a scale or performance claim.
- Agenda output remains a human-editable draft.
- Participant attribution is not server-validated identity.
- The checked-in corpus is a fast three-document smoke subset; the prepared demo
  environment contains the broader 15-artifact research corpus.

## Maintain

Read [AGENTS.md](../AGENTS.md) before changing code. Use
[adding-tools.md](adding-tools.md) when adding an MCP tool, and review
[SECURITY.md](../SECURITY.md) before changing identity, credentials, permissions,
data scope, or network behavior.

The administrator/user handoff is defined in
[DEMO_ENVIRONMENT_SETUP.md](../DEMO_ENVIRONMENT_SETUP.md) and
[CODEX_INSTALLATION.md](../CODEX_INSTALLATION.md). The bootstrap harness's current
read-only adapter boundary is documented in
[admin-bootstrap.md](admin-bootstrap.md).

The private-to-shared trust boundary and acceptance cases are in
[private-session-promotion.md](private-session-promotion.md). The
central observation-projection job is documented in
[management-reconciliation.md](management-reconciliation.md).
