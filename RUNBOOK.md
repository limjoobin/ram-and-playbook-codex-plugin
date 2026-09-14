# Runbook

## Before a demo

1. Confirm Reader and Editor were installed with the same RAM endpoint, store
   ID, and namespace.
2. Fully restart Claude Desktop on both Macs.
3. In Editor, run `editor_status`.
4. In Reader, run `reader_status`.
5. Confirm both return `connection: verified` and the same namespace.

Use `northstar-pilot-demo` for presentations and `northstar-pilot-qa` for
testing.

## Seed or restore the fictional demo data

Only the Editor installation includes the seed command.

Create missing presentation fixtures without changing existing updates:

```sh
~/.local/bin/redis-memory-seed seed demo
```

Restore the six presentation fixtures to their baseline values:

```sh
~/.local/bin/redis-memory-seed reset demo
```

For the QA namespace, replace `demo` with `qa`. These commands do not delete
unrelated records. Never use Redis `FLUSHDB`, `FLUSHALL`, or delete the managed
backing keys.

## Query map

Use one prompt at a time. Reader queries only retrieve information. Editor
queries may retrieve, publish, or update shared information.

### Reader queries

#### R1 — Connection status

```text
Run reader_status. Report the role, connection, namespace, participant, and permissions.
```

#### R2 — Retrieve one requirement

```text
Use reader_search to find Northstar Retail's pilot region requirement. Return the exact memory ID, fact, and update time.
```

#### R3 — Build the pilot plan

```text
Use shared memory to prepare Northstar Retail's pilot plan. Include region, duration, participants, data constraints, and success criteria. Cite the exact memory IDs.
```

#### R4 — Refresh a changed fact

```text
Search shared memory again for Northstar Retail's pilot region. Do not rely on earlier conversation context. Return the exact memory ID, current fact, and update time.
```

#### R5 — Confirm Reader cannot write

```text
Change the shared pilot duration to six weeks.
```

Reader should explain that it has no publish or update tool.

### Editor queries

#### E1 — Connection status

```text
Run editor_status. Report the role, connection, namespace, participant, and permissions.
```

#### E2 — Find a memory before changing it

```text
Use editor_search to find Northstar Retail's pilot region requirement. Return the exact memory ID, fact, and update time. Do not change it yet.
```

#### E3 — Update an existing memory

```text
Find Northstar Retail's pilot region memory and update that exact memory: the pilot must now deploy in Tokyo. Preserve unrelated requirements. Return the memory ID and outcome.
```

Continue only when Editor reports `saved_and_searchable`. Do not use publish to
replace an existing memory.

#### E4 — Publish a new fact

```text
Search shared memory for a Package rehearsal rollout-owner fact. If no existing memory expresses it, publish this new shared fact: "Package rehearsal: the demo rollout owner is Hillary." Return the memory ID and outcome.
```

#### E5 — Verify a write

```text
Use editor_search to retrieve the fact you just changed. Return the exact memory ID, current fact, update time, and whether it matches the requested change.
```

## Cross-user demo sequence

1. Run Reader query R1 and Editor query E1.
2. Run Reader query R3 to show the original shared plan.
3. Run Editor query E2, then E3 to change the pilot region.
4. Run Reader query R4 and confirm it returns Tokyo with the same memory ID.
5. Run Reader query R5 to demonstrate that Reader cannot write.

## Troubleshooting

- **Tools are missing:** fully quit and reopen Claude Desktop.
- **Wrong role or namespace:** rerun the installer for that role with the
  correct values, then restart Claude Desktop.
- **`access_denied`:** confirm the endpoint, store ID, and API key came from the
  same RAM service. Reinstall with a valid key; never send it through chat.
- **No search results:** confirm both users selected the same namespace. If the
  store is empty, have Editor seed it once.
- **`dependency_unavailable`:** if the fixtures already exist, wait and retry.
  For `database_out_of_memory`, contact the Redis service owner.
- **`saved_search_pending`:** wait and search again; do not publish again.
- **`write_unverified`:** search for the exact memory ID and reconcile it before
  attempting another change.
- **Security software blocks installation:** do not bypass it; capture the
  message and contact IT.

## Reconfigure

From the cloned repository, rerun the installer for the affected role:

```sh
./scripts/install-claude-desktop.sh reader
./scripts/install-claude-desktop.sh editor
```

## Uninstall

### Reader

```sh
~/.local/share/redis-shared-memory/reader/current/uninstall.sh
```

### Editor

```sh
~/.local/share/redis-shared-memory/editor/current/uninstall.sh
```

The uninstaller removes only that role's Claude Desktop MCP entry, installed
files, and local credential. It does not modify shared RAM records or the other
role.
