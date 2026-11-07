# Demo environment setup (administrator)

This guide prepares the shared Redis Agent Memory (RAM) and Redis Agent
Playbook environment used by the management-agenda demo. Run it once per demo
environment. After the environment passes acceptance, each participant follows
[CODEX_INSTALLATION.md](CODEX_INSTALLATION.md) to install the desktop plugin,
configure their own credentials, and trust the two reviewed hooks.

For the clean-machine checklist and release-specific seams, read
[HANDOVER.md](HANDOVER.md) first.

## What this guide does—and does not automate

The repository contains the complete versioned context-model contract:

- the `organizational_state` observation schema and extraction prompt;
- the `organizational_state_projection` schema and deterministic projector;
- the canonical management-agenda Playbook Skill and its resources;
- a three-document ES2002 smoke corpus (two AMI artifacts and one synthetic action log); and
- a credential-free context check, bounded MemoryETL submission,
  reconciliation, and evaluation commands.

The current configured-services bootstrap adapter is deliberately read-only.
It does **not** provision RAM or Playbook, declare memory types, publish the
Skill, or guess a release-specific control plane. A fresh service therefore
still needs those administrator mutations through its supported interface.
MemoryETL corpus submission is a separate thin adapter so transport changes do
not alter the context schemas, prompt, policy, or projector.

Do not tell a tester that cloning this repository recreates the prepared
15-artifact environment. The checked-in bundle contains only the kickoff
minutes, the final report, and one synthetic action log, so that bootstrap
smoke tests remain fast.

## Ownership boundary

| Environment administrator | Individual participant |
| --- | --- |
| Provision RAM and Playbook | Install the approved plugin release |
| Configure the model provider and MemoryETL | Store personal service keys locally |
| Declare the two RAM memory types | Set participant and private namespace |
| Publish the Playbook Skill | Review and trust the exact hooks |
| Ingest the smoke or approved full corpus | Confirm any private-to-shared promotion |
| Run central reconciliation | Run the human demo tests |

Hooks do not provision or hydrate the shared environment. Hook trust is a
per-user security decision and cannot be pre-approved by this runbook.

## 1. Collect the environment handoff

Before changing a service, record these values outside the repository:

- the approved Git release tag or commit SHA;
- RAM data-plane endpoint, store ID, shared namespace, and an administrator
  credential for the approved service operations;
- the management owner lane, normally `ami-project-office`;
- a configured RAM model/embedding provider and running MemoryETL worker;
- Playbooks data-plane base URL, playbook ID (`pb_` plus 32 lowercase hex), a
  read/write/publish content key, and a separate runtime reader key; and
- one central host that can run Python 3.11+, the pinned redis-iris SDK, and
  the reconciliation command.

Administrator commands need the SDK. Create the development environment once
(Python 3.11+; `.venv/` is gitignored):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r plugins/redis-shared-memory-editor/server/requirements.txt
```

Prove the checked-in context pipeline before connecting to either service:

```sh
.venv/bin/python scripts/validate_context_pipeline.py
```

Do not continue unless every check passes. This is the portable handover gate
and does not depend on the original developer's laptop or prepared Redis data.

Use a fresh non-production RAM store for a schema-breaking change. Never paste
credentials into chat, write them into the repository, or reuse a publisher
credential as the participant runtime key.

For a repeatable smoke test on an existing non-production store whose schemas
and extractor already match this bundle, use the checked-in reset command:

```sh
.venv/bin/python scripts/reset_demo_ram.py
.venv/bin/python scripts/reset_demo_ram.py --apply --confirm-empty-store
```

Review the first command's target hash and counts. The applied command deletes
all long-term memories and private sessions from the exact store in
`editor.env`, enumerating unnamespaced records and every visible namespace
(RAM namespaces are first-class resources), verifies both lanes are empty, and
preserves declarations and extractors. It does not reset Playbook or modify credentials.

Shared endpoints must use HTTPS. Loopback HTTP is acceptable only when every
component is on the same development machine.

## 2. Pin and inspect the release

Use one clean checkout for administration and the central reconciliation job:

```sh
git clone https://github.com/redis-field-engineering/ram-and-playbook-codex-plugin.git
cd ram-and-playbook-codex-plugin
git switch --detach <approved-tag-or-sha>
git status --short
git rev-parse HEAD
```

Require an empty `git status` and record the commit. Inspect the desired state
without writing to RAM or Playbook:

```sh
.venv/bin/python scripts/admin_bootstrap.py plan
```

Review every target hash, component version, digest, and blocker. The command
uses `~/.config/redis-shared-memory/editor.env` for its safe read-only service
preflight; create that file with an environment-specific runtime reader key as
described in [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md#2-create-the-private-configuration).
For this test prototype, an administrator who is also a participant may keep
the optional administrator names (`IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY`,
`IRIS_AGENT_PLAYBOOKS_SERVICE_URL`, `IRIS_AGENT_PLAYBOOKS_SERVICE_TOKEN`,
`IRIS_AGENT_MEMORY_SERVICE_URL`, and `IRIS_AGENT_MEMORY_SERVICE_TOKEN`) in the
same `0600` file. Ordinary participants leave them unset. The desktop MCP
drops those values from its runtime configuration, and the current read-only
bootstrap adapter does not consume them.

## 3. Provision RAM and Playbook

Provision RAM and Playbook separately using the supported deployment method
for those services. RAM may be local or cloud-hosted; the plugin only requires
a reachable RAM data-plane endpoint with the expected API contract. Playbook
must expose its readable data-plane REST endpoint (base URL only in
`IRIS_AGENT_PLAYBOOKS_URL`, with the playbook ID in
`IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID`).

Before continuing, verify:

- RAM and Playbook are reachable from the central host and tester laptops;
- RAM has its model provider and asynchronous MemoryETL processing available;
- the shared namespace and management owner lane are agreed; and
- the Playbooks content (publish) key is held only by the administrator.

Managed Redis Agent Memory provisions its model and embedding provider with
the service, so no model-provider key belongs in this local file.

The desktop plugin installation is not a service deployment mechanism.

## 4. Declare the context model

The default **compact** layout (`RAM_MEMORY_LAYOUT=compact`) needs one custom
memory type with nine fields,
[`organizational-state-compact.json`](context-models/management-agenda/v1/memory-types/organizational-state-compact.json),
and one document extractor using
[`extraction-prompt-compact.txt`](context-models/management-agenda/v1/extraction-prompt-compact.txt).
Both are entered in the Redis Cloud console; the README's Steps 4 and 5 walk
through it with screenshots. Redis Cloud does not yet offer a customer API for
custom memory types (MOD-18619, MOD-18732), which is why the compact layout is
small enough to enter by hand.

The **expanded** layout (`RAM_MEMORY_LAYOUT=expanded`) keeps the original two
types below. Use it for stores created with them or managed through a
self-managed control plane. Create these exact RAM custom memory types in the
fresh test store:

1. [`organizational_state`](context-models/management-agenda/v1/memory-types/organizational-state.json)
   is the immutable observation ledger. Enable RAM extraction and use the
   versioned [extraction prompt](context-models/management-agenda/v1/extraction-prompt.txt).
2. [`organizational_state_projection`](context-models/management-agenda/v1/memory-types/organizational-state-projection.json)
   is the rebuildable current view. Keep extraction disabled; only the
   repository projector writes it.

The entity registry, projection policy, and projector are application-owned
context, not additional RAM custom memory types. They are versioned under
[`context-models/management-agenda/v1`](context-models/management-agenda/v1).

RAM does not alter an existing custom memory type in place for this PoC. If a
field contract or controlled value changes, create a fresh test store or use a
separately reviewed migration. Reinstalling the plugin cannot upgrade a RAM
schema.

The repository does not currently automate these declarations against a live
service. The SDK exposes them on the Agent Memory control plane
(`redis_agent_memory.controlplane.AgentMemoryService.create_memory_type` and
`create_extractor`), which needs `IRIS_AGENT_MEMORY_SERVICE_URL` and
`IRIS_AGENT_MEMORY_SERVICE_TOKEN`; the `iris` CLI has no memory-type command.
An undeclared store rejects writes with `memory type "organizational_state" is
not registered on this store`. Apply the declarations through the control plane
or the approved RAM administrator interface, then
read them back and compare every field, required attribute, controlled value,
schema version, and extraction setting with the checked-in JSON.

## 5. Publish the one Playbook Skill

Publish the entry declared in
[`playbook/manifest.json`](context-models/management-agenda/v1/playbook/manifest.json)
with its exact linked resources and digests. The environment should contain
one canonical `prepare-management-review-agenda` Skill for this PoC.

Use the content key (`IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY`) only for
publication. Give plugin users a read-only reader key. Do not overwrite a published
version with different content; publish a new version and update the checked-in manifest and runtime
attestation together.

On Redis Cloud the simplest path is the console: `python3 scripts/package_skill.py`
builds the Skill ZIP from the checked-in files after verifying every digest and
prints the alias, intents, and attributes for **Upload Skill**; then publish the
version (README Step 7). Give runtime users a read-only key created through
**Customize in the full page** (MOD-20988).

The current bootstrap adapter cannot publish to a live Playbook. The bundled
`iris` CLI can: export `IRIS_AGENT_PLAYBOOKS_URL`,
`IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID`, and `IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY`.
The SDK requires the Skill folder name to equal the manifest name, so stage it
first:

```sh
mkdir -p /tmp/skills/prepare-management-review-agenda
cp -R context-models/management-agenda/v1/playbook/SKILL.md \
  context-models/management-agenda/v1/playbook/references \
  /tmp/skills/prepare-management-review-agenda/
.venv/bin/iris agent-playbooks skills validate /tmp/skills/prepare-management-review-agenda
```

Validation has been verified offline. Then use `plan`, `sync`, or `publish` on
the staged directory; see `.venv/bin/iris agent-playbooks skills --help` for
exact options. Live publication has not yet been verified in 0.13.0. After publishing,
confirm that discovery returns the expected entry key and version and that every resource digest matches the
manifest.

## 6. Ingest the MemoryETL smoke corpus

The checked-in
[`corpus/manifest.json`](context-models/management-agenda/v1/corpus/manifest.json)
declares three immutable source artifacts:

- `ami-es2002-minutes-kickoff`;
- `ami-es2002-final-report`; and
- `demo-es2002-functional-design-actions`, a short synthetic action log (not
  part of the AMI corpus) that gives each demo participant an owned open action
  for the guided tour.

`python3 scripts/setup_demo.py` submits whichever of these are not yet loaded
and then builds the current state, so the commands below are only needed for a
scripted or repeated administrator run.

Preview the credential-free ingestion plan with the document extractor created
from the checked-in extraction prompt:

```sh
.venv/bin/python scripts/ingest_context_corpus.py \
  --extractor-id YOUR_DOCUMENT_EXTRACTOR_ID
```

After reviewing the target configuration, submit and wait for both revisions:

```sh
.venv/bin/python scripts/ingest_context_corpus.py \
  --extractor-id YOUR_DOCUMENT_EXTRACTOR_ID \
  --apply
```

The command verifies the checked-in bytes, prepends the exact source envelope,
uses deterministic idempotency keys, and waits for terminal MemoryETL success.
It reports safe identities and counts, never document text or credentials.

Each submitted text must include one connector-supplied
`[RAM_SOURCE_ENVELOPE]` JSON line with the exact source artifact ID, revision,
observation time, event sequence, project ID, meeting ID, and project-step ID.
The extraction prompt explains this contract. The envelope is provenance, not
organizational state, and must not become a memory by itself.

Wait for each ingestion to reach the service's terminal success state. Then
verify that extracted `organizational_state` observations:

- use `project-ami-es2002` and the canonical entity IDs;
- retain the source artifact, revision, event order, and evidence locator;
- have empty `relations.edges` during document extraction; and
- remain in the immutable management observation lane.

Do not blind-retry an ambiguous ingestion. Read the service state by
deterministic document ID and revision first.

If a GA release changes the MemoryETL API, update the isolated RAM transport
and its fake contract tests; do not change the context model merely to fit a
new wire format. To recreate the prepared 15-artifact research environment,
an administrator must additionally
obtain the approved normalized corpus and a reviewed ingestion adapter; those
13 artifacts are not checked into this repository.

## 7. Build current state and start reconciliation

Run a read-only projection plan first:

```sh
.venv/bin/python scripts/reconcile_management_state.py
```

Review the target scope and proposed changes, then apply:

```sh
.venv/bin/python scripts/reconcile_management_state.py --apply
```

The command reads immutable observations, applies the checked-in relationship
and lifecycle policy, and upserts only changed projections by deterministic
ID. Repeated runs are idempotent.

For the current PoC, run the same command centrally every five minutes:

```sh
.venv/bin/python scripts/reconcile_management_state.py --apply --quiet-no-changes
```

Install that schedule once on the central host, not through every user's
plugin. Keep its checkout clean and detached at the same approved release used
by participants. The repository currently documents the macOS LaunchAgent
contract but does not ship an installer; follow
[docs/management-reconciliation.md](docs/management-reconciliation.md) and the
host's approved operations process. Confirm the job's last exit status is zero
after pinning or updating the release.

## 8. Install one participant and accept the environment

Have one tester follow [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md). The
tester must personally review and trust `UserPromptSubmit` and `SessionEnd`;
installing the plugin does not trust hooks automatically.

Require all of the following before inviting more users:

1. `editor_status` verifies RAM access, namespace, participant, and write
   permissions without exposing an endpoint or key.
2. `system_status` reports both RAM and Playbook available.
3. Entity resolution maps `remote control project` to `project-ami-es2002`.
4. Current-state search returns projections and history search returns
   source-linked observations.
5. Playbook discovery and loading return the expected Skill version and
   resource digests.
6. `agenda_prepare` returns evidence-linked registers and a human-editable
   draft agenda.
7. A confirmed private-to-shared completion creates one immutable shared
   observation, and the next reconciliation run updates its projection.
8. `.venv/bin/python evaluation/run.py` passes in the pinned checkout.

Do not use fixed memory or lifecycle counts as an acceptance criterion. Counts
change when legitimate observations are added; evidence traversal, schema
conformance, lifecycle behavior, and exact versions are the stable checks.

## 9. Handover record

Record, without secrets or document contents:

- approved Git commit or tag;
- RAM and Playbook safe target identifiers or hashes;
- RAM custom-type versions and extraction settings;
- Playbook entry key, version, and resource digests;
- ingested corpus version and document/revision IDs;
- reconciliation host, pinned commit, schedule, and last successful run; and
- the participant acceptance result.

`.venv/bin/python scripts/admin_bootstrap.py verify` becomes the final read-only
attestation command only after a reviewed live administrator adapter can read
all required service state. Until then, use the explicit readbacks and human
acceptance above and retain the adapter's `unsupported_mutation` blockers as a
visible handover limitation.

## Future one-command automation contract

A future live bootstrap adapter may automate the administrator stages only if
every mutation has an exact pre-check, deterministic idempotency key, bounded
asynchronous wait, post-write readback, sanitized attestation, and a safe
answer for ambiguous writes. It must also provide reviewed scheduler
install/status/uninstall operations. Do not add those capabilities by routing
arbitrary HTTP or MCP calls through the desktop plugin.
