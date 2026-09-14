# Non-secret connection sheet

Fill in the first two values before handoff. Never put an API key in this file.

| Setting | Value |
|---|---|
| RAM endpoint | Pending existing service endpoint |
| RAM store ID | Pending existing demo store ID |
| Presentation namespace | `northstar-pilot-demo` |
| Local test namespace | `northstar-pilot-qa` |
| Reader participant ID | `demo-reader` |
| Reader package | `redis-shared-memory-reader-0.1.1.zip` |

Send the key separately using an approved credential-sharing method. The
installer writes it to the teammate's user-owned configuration directory with
mode `0600`; it is never placed in Claude's MCP JSON. Participant IDs label
activity but do not authenticate users or enforce RAM permissions.
