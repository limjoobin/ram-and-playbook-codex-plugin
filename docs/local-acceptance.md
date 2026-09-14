# Two-PC acceptance checklist

Use the exact ZIPs and hashes that passed automated tests. Rebuilds change the
hashes and require retesting. Keep all test content synthetic.

## Hillary's Mac

- Verify the Editor ZIP against `dist/claude-code/SHA256SUMS`.
- Install Editor with the QA namespace and confirm `editor_status` says
  `editor`, `verified`, and `northstar-pilot-qa`.
- Search, publish one uniquely labelled QA fact, and update the same ID.
- Confirm the result is `saved_and_searchable`.

## Reader rehearsal on Hillary's Mac

- Install Reader alongside Editor using the same QA store and namespace.
- Launch Reader through `~/.local/bin/redis-memory-reader`.
- Confirm only `reader_status` and `reader_search` are present.
- Retrieve the Editor's updated fact and exact memory ID.
- Request a write and confirm no write tool exists.
- Uninstall Editor and confirm Reader still starts and retrieves the record.
- Reinstall Editor and confirm the roles remain independent.

## Teammate's Mac

- Verify and install only the exact Reader ZIP that passed locally.
- Confirm Claude Code and Node.js 20+ are available.
- Use the same endpoint, store ID, and presentation namespace, but participant
  ID `demo-reader`.
- Run Reader from the VS Code terminal and confirm a verified status.
- Retrieve the same seeded memory IDs as Hillary.
- After Hillary updates the region record, search again and confirm the new
  value, same ID, and changed timestamp.
- Request a change and confirm Reader offers no mutation tool.

## Security checks

- Neither ZIP contains a RAM key, private key, developer absolute path, `.env`
  content, or real customer data.
- `~/.config/redis-shared-memory/<role>.env` is a regular file owned by the user
  with mode `0600`.
- The launcher's temporary MCP JSON contains only the role server command and is
  deleted when Claude exits.
- Claude launches with `--restricted`, `--strict-mcp-config`, and a role-specific
  MCP allowlist containing no built-in tools. Reader uses auto permission mode;
  Editor uses manual.
- Removing one role does not remove the other role or alter RAM records.

Record endpoint-protection prompts or quarantine behavior on the teammate's Mac.
The current company Claude Code policy allows local stdio MCP, but independent
endpoint protection can still block unfamiliar downloaded scripts.
