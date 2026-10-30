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
- a two-document AMI ES2002 smoke corpus; and
- a credential-free context check, bounded MemoryETL submission,
  reconciliation, and evaluation commands.

The current configured-services bootstrap adapter is deliberately read-only.
It does **not** provision RAM or Playbook, declare memory types, publish the
Skill, or guess a release-specific control plane. A fresh service therefore
still needs those administrator mutations through its supported interface.
MemoryETL corpus submission is a separate thin adapter so transport changes do
not alter the context schemas, prompt, policy, or projector.

Do not tell a tester that cloning this repository recreates the prepared
15-artifact environment. The checked-in bundle contains only kickoff minutes
and the final report so that bootstrap smoke tests remain fast.

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
- Playbook service endpoint, Playbook ID, publisher credential, and a separate
  runtime reader credential when supported; and
- one central host that can run Python 3.10+ and the reconciliation command.

Prove the checked-in context pipeline before connecting to either service:

```sh
python3 scripts/validate_context_pipeline.py
```

Do not continue unless every check passes. This is the portable handover gate
and does not depend on the original developer's laptop or prepared Redis data.

Use a fresh non-production RAM store for a schema-breaking change. Never paste
credentials into chat, write them into the repository, or reuse a publisher
credential as the participant runtime key.

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
python3 scripts/admin_bootstrap.py plan
```

Review every target hash, component version, digest, and blocker. The command
uses `~/.config/redis-shared-memory/editor.env` for its safe read-only service
preflight; create that file with an environment-specific runtime reader key as
described in [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md#2-create-the-private-configuration).
For this test prototype, an administrator who is also a participant may keep
`RAM_ADMIN_API_KEY`, `PLAYBOOK_PUBLISHER_API_KEY`, and `OPENAI_API_KEY` in the
same `0600` file. Ordinary participants leave them blank. The desktop MCP
drops those values from its runtime configuration, and the current read-only
bootstrap adapter does not consume them yet.

## 3. Provision RAM and Playbook

Provision RAM and Playbook separately using the supported deployment method
for those services. RAM may be local or cloud-hosted; the plugin only requires
a reachable RAM data-plane endpoint with the expected API contract. Playbook
must expose its readable MCP endpoint.

Before continuing, verify:

- RAM and Playbook are reachable from the central host and tester laptops;
- RAM has its model provider and asynchronous MemoryETL processing available;
- the shared namespace and management owner lane are agreed; and
- the Playbook publisher credential is held only by the administrator.

Managed Redis Agent Memory provisions its model and embedding provider with
the service, so it normally does not require `OPENAI_API_KEY` in this local
file. A local/dev RAM deployment may use it when its documented setup requires
a client-supplied provider key.

The desktop plugin installation is not a service deployment mechanism.

## 4. Declare the context model

Create these exact RAM custom memory types in the fresh test store:

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
service. Apply them through the approved RAM administrator interface, then
read them back and compare every field, required attribute, controlled value,
schema version, and extraction setting with the checked-in JSON.

## 5. Publish the one Playbook Skill

Publish the entry declared in
[`playbook/manifest.json`](context-models/management-agenda/v1/playbook/manifest.json)
with its exact linked resources and digests. The environment should contain
one canonical `prepare-management-review-agenda` Skill for this PoC.

Use the publisher credential only for publication. Give plugin users a
read-only Playbook key. Do not overwrite a published version with different
content; publish a new version and update the checked-in manifest and runtime
attestation together.

The current bootstrap adapter cannot publish to a live Playbook. Use the
approved Playbook publication workflow, then confirm that discovery returns
the expected entry key and version and that every resource digest matches the
manifest.

## 6. Ingest the MemoryETL smoke corpus

The checked-in
[`corpus/manifest.json`](context-models/management-agenda/v1/corpus/manifest.json)
declares two immutable source artifacts:

- `ami-es2002-minutes-kickoff`; and
- `ami-es2002-final-report`.

Preview the credential-free ingestion plan with the document extractor created
from the checked-in extraction prompt:

```sh
python3 scripts/ingest_context_corpus.py \
  --extractor-id YOUR_DOCUMENT_EXTRACTOR_ID
```

After reviewing the target configuration, submit and wait for both revisions:

```sh
python3 scripts/ingest_context_corpus.py \
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
python3 scripts/reconcile_management_state.py
```

Review the target scope and proposed changes, then apply:

```sh
python3 scripts/reconcile_management_state.py --apply
```

The command reads immutable observations, applies the checked-in relationship
and lifecycle policy, and upserts only changed projections by deterministic
ID. Repeated runs are idempotent.

For the current PoC, run the same command centrally every five minutes:

```sh
python3 scripts/reconcile_management_state.py --apply --quiet-no-changes
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
8. `python3 evaluation/run.py` passes in the pinned checkout.

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

`python3 scripts/admin_bootstrap.py verify` becomes the final read-only
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
