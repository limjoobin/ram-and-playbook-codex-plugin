# Adding an MCP tool

Add one explicit, reviewable user action at a time. Do not add a generic
`execute`, `call_api`, or arbitrary proxy tool.

## 1. Define the contract

Before coding, decide:

- the exact user request that should trigger the tool;
- whether it is read-only, additive, destructive, or irreversible;
- which configured store and namespace it may access;
- which server-side permission authorizes it;
- the minimum safe input and output; and
- how an uncertain write will be reconciled without duplication.

Endpoint, store, namespace, participant, headers, and credentials are trusted
local configuration. Never make them model-controlled tool arguments.

## 2. Implement the RAM operation

Put RAM behavior on `SharedMemory` in
`plugins/redis-shared-memory-editor/server/ram_plugin/ram.py`. Keep the MCP
handler thin.

For reads, include the namespace filter in the request and recheck every
returned record. For writes, read the current record when applicable, preserve
unmodified fields, verify persistence by exact ID, and never replay an
uncertain mutation automatically.

Add Playbook or another service behind its own module and authorization
boundary. Do not add unrelated methods to `SharedMemory` or pass arbitrary
operations, URLs, or headers from model input.

Session capture and personal-to-shared promotion belong in `promotion.py`.
Keep capture private-only. A promotion must create a new shared observation,
retain private-source identifiers, require explicit confirmation, and use
deterministic idempotency. Do not add a second organizational-state reconciler.

## 3. Register the MCP contract

Add the tool to `TOOLS` in `ram_plugin/mcp_server.py`, validate its arguments in
`_validate_arguments()`, and map it in `call_tool()`.

Each tool must have:

- a unique action-oriented name;
- a description that states when to use it and what it changes;
- a strict JSON Schema with bounded values and `additionalProperties: false`;
- explicit `readOnlyHint`, `destructiveHint`, and `openWorldHint` values; and
- sanitized, task-relevant output.

Use `destructiveHint: true` for overwrite, delete, revoke, cancel, or other
difficult-to-reverse actions. An annotation describes behavior; it does not
replace server-side authorization or host approval.

## 4. Test it

Add tests to `tests/test_plugin.py` for:

- success and MCP listing;
- invalid and boundary input;
- namespace/store isolation;
- sanitized authentication, network, and dependency failures; and
- timeout or ambiguous persistence for every mutation.

If a change affects state retrieval, evidence traversal, Playbook attestation,
or agenda output, run `.venv/bin/python evaluation/run.py`. Add or change a fixed case
only for a reviewed product-contract change; do not lower a threshold to hide
a regression. Regenerate `evaluation/results.json` with `--write` and inspect
the diff.

For management-state changes, keep the contracts separate: history reads the
immutable `organizational_state` observation lane, while current/conflict views
read `organizational_state_projection` and hydrate evidence only through the
projection's supporting observation IDs. Do not reintroduce model-selected
"latest" state IDs in the tool contract.

Run:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evaluation/run.py
```

The runtime must continue to work on Python 3.11+ with only the pinned
redis-iris set in `server/requirements.txt`. Run these commands from the
development virtual environment described in `AGENTS.md`.

## 5. Update user-facing files

Update the plugin README and `plugin.json` when capabilities change. Update
`CODEX_INSTALLATION.md` for configuration or verification changes and
`SECURITY.md` for any new permission, data type, destination, identity rule, or
trust boundary.

For a new setting, update `Config`, `SETTING_NAMES`, the credential loader,
`.env.example`, installation/security docs, and invalid/missing-value tests.
Keep the versions in `ram_plugin/config.py` and `plugin.json` aligned.

Before sharing a release, install its exact tag or commit in a clean checkout
and exercise the new tool with successful, invalid, out-of-scope, and upstream-
failure inputs.
