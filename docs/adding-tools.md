# Adding MCP tools

This guide is for maintainers extending the Redis Shared Memory desktop plugin.
The short rule is: one explicit user action per tool, with the smallest input
and output contract that can safely perform it.

## 1. Write the tool contract first

Record these decisions before coding:

- What exact user request should trigger the tool?
- Is it read-only, additive, destructive, or irreversible?
- Does it access only the configured private store, or an open-ended external
  destination?
- Which identity authorizes the operation?
- What is safe to return to the model?
- If a network response is ambiguous, how will the server determine whether a
  write happened?

Do not expose a generic `execute`, `call_api`, or `run_tool` operation. Every
model-callable operation must have a stable name, its own schema, and reviewable
behavior.

## 2. Add the service operation

Implement RAM behavior on `SharedMemory` in `ram_plugin/ram.py`. The service layer
owns scope checks, safe retries, verification, and the minimal result shape.
MCP handlers in `ram_plugin/mcp_server.py` should remain thin.

For a read:

- Include the configured namespace filter in the SDK request.
- Recheck every returned record before disclosing it.
- Return only fields required for the user task.

For a write:

- Keep writes available only through explicitly registered `editor_*` tools.
- Read the current record before updating it.
- Preserve fields that the user did not ask to change.
- Never replay an uncertain mutation merely because it timed out.
- Verify persistence by exact ID, then report search visibility separately.

Add a new dependency or client abstraction only when the existing RAM client
cannot represent the operation. Keep Playbook or another service behind its own
adapter instead of adding unrelated methods to `SharedMemory`.

## 3. Register the MCP tool

Register the tool in the `TOOLS` list in `ram_plugin/mcp_server.py`. A typical
read tool has this shape:

```python
{
    "name": "editor_get_example",
    "title": "Get example",
    "description": (
        "Retrieve one example from the configured Redis memory namespace "
        "by its exact ID. No writes."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "pattern": "^[a-zA-Z0-9-]{1,64}$",
            }
        },
        "required": ["memory_id"],
        "additionalProperties": False,
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    },
}
```

Then add exact argument validation in `_validate_arguments()` and map the name
to its `SharedMemory` method in `call_tool()`. The advertised JSON Schema and
runtime validation must agree.

For every tool:

- Use an action-oriented, unique name.
- State when to use it, its limitations, and its side effects.
- Reject unknown fields with a strict schema.
- Bound string lengths and identifier formats.
- Set all three safety annotations explicitly. Classify actual behavior; do not
  copy values from another tool without checking them.
- Use `destructiveHint: true` for overwrite, delete, revoke, cancel, or other
  difficult-to-reverse actions.
- Keep sensitive values and internal diagnostics out of tool metadata and
  responses.

`idempotentHint` may be added when the operation is genuinely safe to repeat,
but it does not replace the three required safety annotations.

## 4. Test the contract

Add tests to `tests/test_python_plugin.py` for:

- the successful operation;
- invalid and boundary inputs;
- Reader or unauthorized access, when relevant;
- namespace/store isolation;
- sanitized authentication, network, and dependency failures;
- timeout or ambiguous persistence behavior for writes; and
- the MCP tool listing and direct call path.

Update `tests/packages.test.ts` when the packaged artifact, launch contract, or
end-to-end network behavior changes. Tests must prove behavior; a tool appearing
in `tools/list` is not enough.

## 5. Update package metadata and docs

Update these files as needed:

- `plugins/redis-shared-memory-editor/README.md` for the public tool list and
  usage notes;
- `plugins/redis-shared-memory-editor/plugin.json` for accurate capabilities
  and prompts;
- `CODEX_INSTALLATION.md` for configuration or verification changes;
- `SECURITY.md` for a new permission, data category, destination, or trust
  boundary.

If a new setting is required, add it to all of these places:

1. `Config` and `load_config()` in `ram_plugin/config.py`;
2. `SETTING_NAMES` and the loader in `ram_plugin/credentials.py`;
3. `plugins/redis-shared-memory-editor/.env.example`;
4. configuration and security documentation; and
5. tests for missing, invalid, duplicate, and unexpected values.

Never make endpoint, store, namespace, authorization headers, or credentials a
tool argument. They belong to administrator/user-controlled local configuration
or, in a later hosted design, to validated OAuth credentials.

## 6. Build and review the installable artifact

```sh
npm ci
npm run check
```

The desktop plugin is committed as dependency-free Python source; there is no
generated executable or vendored Python environment. Review the source, tests,
manifest changes, and `BUILD.json` source digest.

Before sharing a ref, install that exact ref in a clean checkout and invoke each
new tool with representative, invalid, out-of-scope, and dependency-failure
inputs.
