# Administrator context bootstrap

The repository now contains an explicit, versioned bootstrap harness for the
shared RAM and Playbook context model. It is separate from the installable
plugin under `plugins/`: installing or starting the plugin never imports or
runs this harness.

The first bundle is `context-models/management-agenda/v1`. It contains the two
memory-type schemas, entity registry, extraction prompt, projection policy,
the single authoritative projector ported from the management-agenda
consumer, the Playbook Skill and resources, and a two-document AMI smoke
corpus. The smoke corpus is intentionally the smallest source-grounded slice;
the 15-document research corpus remains a later compatible bundle revision
after a live administrator adapter is approved.

## Commands

Use the existing private plugin configuration at
`~/.config/redis-shared-memory/editor.env`. Do not add credentials, endpoints,
or customer content to the bundle.

Read-only plan:

```sh
python3 scripts/admin_bootstrap.py plan
```

The plan reports safe target hashes plus every current and desired component
version and digest. It does not write an attestation or change either service.

Explicit administrator apply:

```sh
python3 scripts/admin_bootstrap.py apply --confirm-admin
```

`apply` is the only mutating mode. It always inspects first and will stop on a
service failure, a reused version with a different digest, a breaking schema
fingerprint, or a stage for which the selected adapter has no reviewed
mutation. A successful apply writes an owner-readable attestation to
`.bootstrap/attestation.json`; use `--attestation /approved/private/path.json`
to select another local path.

Read-only verification:

```sh
python3 scripts/admin_bootstrap.py verify
```

Verification recomputes bundle digests, checks the service state, runs the
declared central projection implementation, checks counts, and runs the
versioned representative retrieval cases. It never rewrites the attestation.

## Current adapter boundary

The configured-services adapter deliberately performs only read-only RAM and
Playbook preflight. The plugin's external configuration provides data-plane
and read-only Playbook access, but no reviewed RAM control-plane, document
ingestion, or Playbook publication operation. Consequently, a live `apply`
currently exits with `unsupported_mutation` blockers before changing state.
This is intentional: add a live administrator adapter only after its endpoint,
authentication, publication, ingestion-idempotency, and ambiguous-write
contracts are approved. Do not infer those contracts from the local prototype.

The contract tests exercise the complete intended order with a fake adapter:

1. verify RAM and Playbook service access;
2. compare and apply declarations;
3. compare and publish the Playbook bundle;
4. compare and ingest the corpus;
5. wait for asynchronous extraction;
6. run the one versioned projector and apply derived projections; and
7. verify counts and representative retrieval cases before attesting.

No step deletes, resets, or blindly overwrites a store, memory type, corpus,
projection, or Playbook publication.

## Model upgrade rules

- Never change files while retaining their declared component version. The
  harness treats the same version with another digest as an error.
- A compatible prompt, policy, content, or corpus update receives new
  component and context-model versions. It may be applied only when the
  breaking schema fingerprint is unchanged and the adapter supports that
  stage's check-first mutation.
- A field/type, required-field, or controlled-value change changes the
  breaking schema fingerprint. The harness stops and directs the administrator
  to a fresh test store or namespace, unless a separate migration has been
  reviewed and explicitly approved.
- Do not mutate a validated corpus in place. Create a new declared corpus
  version and preserve its prior attestation.

## Human acceptance

Before any future live adapter is used:

1. Select a fresh non-production store/namespace and a test Playbook. Keep the
   existing shared environment unchanged.
2. Run `plan`; record the Git commit, bundle digest, target hashes, desired
   versions/digests, and all proposed stages. Stop if any target is unexpected.
3. Review the administrator adapter and service API contracts. Confirm every
   mutation has an exact pre-check and post-write verification and that no
   delete/reset path exists.
4. Run `apply --confirm-admin` once. Do not retry an ambiguous write; inspect
   service state and rerun `plan` first.
5. Run `verify`; require all component checks, expected counts, source
   traversal, and both representative retrieval cases to pass.
6. Inspect `.bootstrap/attestation.json`. It must contain only versions,
   digests, safe target hashes, counts, case results, and no credential,
   endpoint, query result, or document content.
7. Run `system_status`, resolve `remote control project`, inspect current and
   history state, discover the exact agenda Skill version, and prepare one
   evidence-backed agenda through the plugin.
8. Confirm `hooks/hooks.json` still registers only `UserPromptSubmit` and
   `SessionEnd`, then obtain human approval before using another target.
