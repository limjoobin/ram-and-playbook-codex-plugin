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
or agenda output, run `python3 evaluation/run.py`. Add or change a fixed case
only for a reviewed product-contract change; do not lower a threshold to hide
a regression. Regenerate `evaluation/results.json` with `--write` and inspect
the diff.

Run:

```sh
python3 -m unittest discover -s tests -v
python3 evaluation/run.py
```

The runtime must continue to work with Python 3.10+ and no third-party package.

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
