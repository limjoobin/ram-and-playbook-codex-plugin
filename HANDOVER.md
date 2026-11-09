# Clean-machine handover

This is the shortest path for another engineer or agent to recreate and test
the management-agenda PoC without access to the original developer's computer.

## What is portable now

The repository is authoritative for:

- the two RAM custom-memory contracts;
- canonical entities and source-envelope fields;
- the document extraction prompt;
- the three-document smoke corpus (two AMI artifacts plus one synthetic action log) and deterministic expected extraction;
- relationship and lifecycle policy;
- the one canonical projector/reconciliation job;
- the Playbook Skill and all linked resources;
- the private capture and confirmed-promotion hooks; and
- offline, MemoryETL, reconciliation, plugin, and agenda tests.

No checked-in command reads credentials from the repository. No required
context file lives only on the original developer's Mac.

The expected-observation JSONL is a deterministic contract fixture, not a
claim about model extraction quality. The live acceptance still submits the
source documents through RAM MemoryETL and inspects its source-linked output.

## Projector reuse acceptance

The projector is infrastructure, not an AMI-specific resolver. Handover
acceptance requires all of the following:

- `projector.py` contains no AMI, Real Reaction, ES2002, meeting-name, subject,
  or project-specific state identity;
- entity mappings, aliases, state families, and any fixture-specific relation
  rules remain in the versioned entity registry or projection policy;
- tests exercise temporal ordering with an unrelated fictional project,
  different dates, and non-AMI event sequences; and
- connector/source-envelope event order is authoritative. A heading that
  references an earlier meeting may identify context but never backdates the
  observation. Heading-based ordering is only a policy fallback when the
  envelope sequence is unknown.

Run `.venv/bin/python -m unittest tests.test_projector_reusability -v` as the focused
acceptance check.

## Clean setup order

1. Clone the approved commit or tag, create the development environment
   (Python 3.11+, `.venv/` is gitignored), and run:

   ```sh
   python3 -m venv .venv
   .venv/bin/python -m pip install -r plugins/redis-shared-memory-editor/server/requirements.txt
   .venv/bin/python scripts/validate_context_pipeline.py
   .venv/bin/python -m unittest discover -s tests -v
   .venv/bin/python evaluation/run.py
   ```

2. Provision RAM and Playbook using the supported instructions for the
   deployed release.
   To reuse an existing non-production RAM store, first inspect and explicitly
   empty only its entries:

   ```sh
   .venv/bin/python scripts/reset_demo_ram.py
   .venv/bin/python scripts/reset_demo_ram.py --apply --confirm-empty-store
   ```

   This preserves the store, namespaces, custom-memory types, and document
   extractors while deleting all long-term memories and private sessions.
3. In RAM, register the memory types for the store's layout. The default
   compact layout uses the one nine-field `organizational-state-compact.json`
   type and a document extractor with `extraction-prompt-compact.txt`, entered
   in the Redis Cloud console (README Steps 4–5). The expanded layout
   (`RAM_MEMORY_LAYOUT=expanded`) uses the two original contracts with
   `extraction-prompt.txt`, keeping extraction disabled for
   `organizational_state_projection`.
4. Publish the one entry described by `playbook/manifest.json`, including
   `SKILL.md` and every declared reference. Use the manifest's entry key,
   intents, attributes, version, and digests.
5. Store endpoints, scopes, participant identity, and keys in the ignored
   `~/.config/redis-shared-memory/editor.env` described by
   [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md) (0.13.0 names:
   `IRIS_AGENT_MEMORY_*` and `IRIS_AGENT_PLAYBOOKS_*`).
6. Preview and ingest the smoke corpus:

   ```sh
   .venv/bin/python scripts/ingest_context_corpus.py --extractor-id EXTRACTOR_ID
   .venv/bin/python scripts/ingest_context_corpus.py --extractor-id EXTRACTOR_ID --apply \
     --rehydration-id RESET-YYYYMMDD-A
   ```

   `--rehydration-id` is required when intentionally repopulating a store whose
   prior MemoryETL receipts and immutable source identities remain after its
   memories were emptied. It deterministically creates a new source revision
   in both the RAM request and source envelope. Choose a new value for each
   reset, and reuse that value for retries of the same run.

7. Build current state and prove idempotency:

   ```sh
   .venv/bin/python scripts/reconcile_management_state.py
   .venv/bin/python scripts/reconcile_management_state.py --apply
   .venv/bin/python scripts/reconcile_management_state.py --apply
   ```

   The second applied run must report no changes.
8. Install the plugin, run `launch.py --install` to pre-install the pinned
   runtime, and personally review/trust `UserPromptSubmit` and
   `SessionEnd` as described by `CODEX_INSTALLATION.md`.
9. Run the human flow in `docs/management-agenda-demo-runbook.md`, including a
   confirmed completion promotion followed by reconciliation.

## Release-specific seams

The context model must not change merely because a service API changes. The
replaceable seams are deliberately small:

- the redis-iris SDK adapters: `RAMClient` in `ram.py` (including
  `create_document_ingestion`, `get_document_ingestion`, and
  `list_document_ingestion_outputs`) and `PlaybookClient` in `playbook.py`,
  plus the exact pins in `server/requirements.txt`;
- RAM administrator declarations: the SDK's Agent Memory control plane
  (`create_memory_type`, `create_extractor`), not yet automated here;
- Playbook publication: `iris agent-playbooks skills ...` with the content key
  and a staged Skill folder named after the manifest (see
  [DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md)); not yet verified
  live in 0.13.0.

After a Redis service release, update only the affected seam and its fake
contract tests unless the actual memory semantics changed. Do not silently
rewrite schemas, extraction instructions, entity IDs, source ordering, or
projection rules to accommodate transport changes.

## Acceptance evidence

Keep these with the environment handoff, without secrets or source text:

- Git commit/tag and `bundleDigest` from `validate_context_pipeline.py`;
- custom-memory type names and schema versions;
- document extractor identity and prompt component version;
- Playbook entry key and published version;
- two document/revision identities and successful ingestion states;
- successful reconciliation plus a repeated no-change run;
- plugin version, reviewed hooks, and `system_status`; and
- one evidence-backed agenda and one promoted completion test.

The three-document bundle is a fast smoke environment, not a recreation of the
prepared 15-artifact research store. That distinction is intentional and must
remain visible in any handover claim.
