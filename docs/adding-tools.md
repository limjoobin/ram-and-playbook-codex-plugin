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

Implement RAM behavior on `SharedMemory` in `src/memory.ts`. The service layer
owns scope checks, safe retries, verification, and the minimal result shape.
MCP handlers in `src/server.ts` should remain thin.

For a read:

- Include the configured namespace filter in the SDK request.
- Recheck every returned record before disclosing it.
- Return only fields required for the user task.

For a write:

- Call `requireEditor()` before accessing RAM.
- Read the current record before updating it.
- Preserve fields that the user did not ask to change.
- Never replay an uncertain mutation merely because it timed out.
- Verify persistence by exact ID, then report search visibility separately.

Add a new dependency or client abstraction only when the existing RAM client
cannot represent the operation. Keep Playbook or another service behind its own
adapter instead of adding unrelated methods to `SharedMemory`.

## 3. Register the MCP tool

Register the tool in `src/server.ts`. A typical read tool has this shape:

```ts
server.registerTool(
  'editor_get_example',
  {
    title: 'Get example',
    description:
      'Retrieve one example from the configured Redis memory namespace by its exact ID. No writes.',
    inputSchema: z.object({
      memory_id: z.string().regex(SLUG),
    }).strict(),
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      openWorldHint: true,
    },
  },
  ({ memory_id }) => wrap(memory => memory.getExample(memory_id))(),
);
```

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

Add tests to `tests/memory.test.ts` for:

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

1. `Config` and `loadConfig()` in `src/config.ts`;
2. the allowlist in `src/credential-file.ts`;
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

The build compiles TypeScript and bundles runtime dependencies into
`plugins/redis-shared-memory-editor/server/index.cjs`. Review the TypeScript
source, tests, manifest changes, and `BUILD.json` source digest. Do not edit the
bundle manually.

Before sharing a ref, install that exact ref in a clean checkout and invoke each
new tool with representative, invalid, out-of-scope, and dependency-failure
inputs.
