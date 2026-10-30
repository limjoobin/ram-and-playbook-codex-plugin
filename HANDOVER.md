# Clean-machine handover

This is the shortest path for another engineer or agent to recreate and test
the management-agenda PoC without access to the original developer's computer.

## What is portable now

The repository is authoritative for:

- the two RAM custom-memory contracts;
- canonical entities and source-envelope fields;
- the document extraction prompt;
- the two-document AMI smoke corpus and deterministic expected extraction;
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

## Clean setup order

1. Clone the approved commit or tag and run:

   ```sh
   python3 scripts/validate_context_pipeline.py
   python3 -m unittest discover -s tests -v
   python3 evaluation/run.py
   ```

2. Provision RAM and Playbook using the supported instructions for the
   deployed release.
   To reuse an existing non-production RAM store, first inspect and explicitly
   empty only its entries:

   ```sh
   python3 scripts/reset_demo_ram.py
   python3 scripts/reset_demo_ram.py --apply --confirm-empty-store
   ```

   This preserves the store, namespaces, custom-memory types, and document
   extractors while deleting all long-term memories and private sessions.
3. In RAM, register the two exact JSON contracts under
   `context-models/management-agenda/v1/memory-types/`. Configure a document
   extractor for `organizational_state` with `extraction-prompt.txt`. Keep
   extraction disabled for `organizational_state_projection`.
4. Publish the one entry described by `playbook/manifest.json`, including
   `SKILL.md` and every declared reference. Use the manifest's entry key,
   intents, attributes, version, and digests.
5. Store endpoints, scopes, participant identity, and keys in the ignored
   `~/.config/redis-shared-memory/editor.env` described by
   [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md).
6. Preview and ingest the smoke corpus:

   ```sh
   python3 scripts/ingest_context_corpus.py --extractor-id EXTRACTOR_ID
   python3 scripts/ingest_context_corpus.py --extractor-id EXTRACTOR_ID --apply
   ```

7. Build current state and prove idempotency:

   ```sh
   python3 scripts/reconcile_management_state.py
   python3 scripts/reconcile_management_state.py --apply
   python3 scripts/reconcile_management_state.py --apply
   ```

   The second applied run must report no changes.
8. Install the plugin and personally review/trust `UserPromptSubmit` and
   `SessionEnd` as described by `CODEX_INSTALLATION.md`.
9. Run the human flow in `docs/management-agenda-demo-runbook.md`, including a
   confirmed completion promotion followed by reconciliation.

## Release-specific seams

The context model must not change merely because a service API changes. The
replaceable seams are deliberately small:

- RAM MemoryETL HTTP shape: `RAMClient.create_document_ingestion`,
  `get_document_ingestion`, and `list_document_ingestion_outputs`;
- RAM administrator declarations: the deployed release's supported control
  plane or console;
- Playbook publication: the deployed release's supported publisher surface.

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

The two-document bundle is a fast smoke environment, not a recreation of the
prepared 15-artifact research store. That distinction is intentional and must
remain visible in any handover claim.
