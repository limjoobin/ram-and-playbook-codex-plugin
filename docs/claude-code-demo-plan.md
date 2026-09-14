# Shared Redis Agent Memory Demo — Claude Code Delivery Plan

## Outcome

Deliver two role-specific Claude Code packages for macOS that connect to the same
Redis Agent Memory store and namespace:

- **Editor package for Hillary:** status, search, publish, and update.
- **Reader package for the teammate:** status and search only.

Both users run Claude Code from the VS Code integrated terminal. The packages use
a local stdio MCP server; they do not use Claude Desktop extensions, Claude Code
plugins, lifecycle hooks, a hosted application, or a tunnel.

The teammate must copy and run the Reader package locally. If Claude Code and
Node.js 20 or newer are already installed, no additional platform software is
required. The installer must stop with a clear message if either prerequisite is
missing.

Read-only is enforced at the available-tool and server-role layers. The Reader
package contains no write tools and rejects direct calls to mutation methods.
The shared RAM API key remains capable of writes outside this integration; that
is an accepted limitation for this trusted, synthetic-data demonstration.

## Architecture

```text
Hillary's VS Code / Claude Code
  -> restricted Editor MCP process
  -> Redis Agent Memory HTTPS API
  -> shared store + business-definitions-demo namespace

Teammate's VS Code / Claude Code
  -> restricted Reader MCP process
  -> Redis Agent Memory HTTPS API
  -> the same store + namespace
```

Use direct long-term-memory records with stable IDs for the demonstration facts.
Do not depend on asynchronous conversation extraction or Claude Code session
hooks. Every relevant answer performs a fresh memory search, so a Reader can see
an Editor update without restarting Claude Code.

## Deliverables

Produce these versioned artifacts from one source digest:

```text
dist/claude-code/redis-shared-memory-editor-<version>.zip
dist/claude-code/redis-shared-memory-reader-<version>.zip
dist/claude-code/SHA256SUMS
dist/claude-code/release.json
```

Each ZIP contains:

- One bundled Node MCP server with no runtime `npm install`.
- A fixed Reader or Editor entry point; role is not a configuration argument.
- `install.sh`, `uninstall.sh`, and a role-specific launcher.
- A non-secret MCP configuration containing only local executable paths.
- A small demo workspace with `CLAUDE.md` instructions and no business facts.
- A one-page setup and troubleshooting guide.
- Build metadata, checksum, and third-party notices.

The installer uses only user-owned locations and never requests `sudo`:

```text
~/.local/share/redis-shared-memory/<role>/<version>/
~/.local/bin/redis-memory-<role>
~/.config/redis-shared-memory/<role>.env
```

The credential file is outside the source and demo workspaces, is created with
mode `0600`, and is excluded from package output and logs. Neither `.mcp.json`
nor Claude settings may contain the API key.

## Implementation

### 1. Retarget the existing implementation

- Preserve the existing shared `SharedMemory` implementation and official
  `@redis-iris/agent-memory` SDK.
- Replace Desktop-specific terminology, manifests, and errors with Claude Code
  terminology.
- Build standalone `reader/index.cjs` and `editor/index.cjs` files.
- Keep namespace filtering server-side and reject any record returned outside
  the configured namespace.
- Keep write confirmation, stable memory IDs on retry, and the distinction
  between saved, search-pending, and unverified outcomes.
- Do not expose deletion, generic HTTP, arbitrary namespace, shell, filesystem,
  or automatic conversation-capture tools.

### 2. Create secure setup and launch commands

Each installer must:

1. Verify macOS, `claude`, and Node.js 20+.
2. Verify the artifact checksum before copying files.
3. Prompt for endpoint, store ID, namespace, participant ID, and a hidden API
   key. The API key must not appear in shell history or terminal output.
4. Write the role credential file outside the workspace with mode `0600`.
5. Run a real RAM status check without printing the key.
6. Print the exact launch and uninstall commands.

Each role launcher must:

- Read the role credential file locally.
- Start Claude Code with only the matching temporary MCP configuration.
- Use `--restricted` and `--strict-mcp-config` so Bash, file tools, plugins, and
  unrelated MCP servers are unavailable during the demonstration.
- Use `--permission-mode auto` for Reader. This combination has passed a live
  test under the current company-managed policy.
- Use manual permission mode for Editor so the user explicitly approves memory
  writes.
- Fail closed if the role, credential file, bundle checksum, or configuration
  is invalid.

### 3. Make retrieval deterministic

- Keep the six fictional Northstar Retail fixtures with deterministic IDs.
- Use `northstar-pilot-qa` for automated/live testing and
  `northstar-pilot-demo` for the presentation.
- Add role-specific `CLAUDE.md` instructions requiring a new RAM search before
  answering customer-specific questions and memory IDs in the response.
- Require Editor to search before publishing or updating.
- Require a successful Reader search after an Editor update before presenting
  the change.

### 4. Package and test

Automated acceptance must cover:

- Type checking and unit tests.
- Exact bundled servers launched from outside the repository.
- Reader tool listing contains only status and search.
- Direct Reader mutation calls fail before any RAM request.
- Editor write followed by independent Reader retrieval of the same memory ID.
- Cross-namespace updates and unexpected out-of-scope results are rejected.
- API, payload, and SDK errors cannot disclose headers, keys, or memory bodies.
- Artifact scan finds no API keys, private keys, absolute developer paths, or
  source `.env` contents.
- Locked production and development dependencies have no known vulnerabilities.
- Install, reinstall, and uninstall do not affect RAM records or the other role.

Live acceptance must cover:

1. Verify all QA fixture IDs against the real RAM service.
2. Run the Reader through Claude Code and confirm `reader`, `verified`, and the
   intended namespace.
3. Run a QA Editor publish/update and retrieve it through Reader.
4. Confirm Reader cannot discover or call any write tool.
5. Install both roles on Hillary's Mac and test them separately.
6. Install only Reader on the teammate's Mac and complete the final two-PC
   rehearsal.

## Installation After Implementation

### Hillary's PC — Editor

1. Confirm prerequisites:

   ```sh
   claude --version
   node --version
   ```

2. Copy `redis-shared-memory-editor-<version>.zip` and `SHA256SUMS` to a local
   folder.
3. Verify the checksum using the command in the Editor guide.
4. Unzip the package and run:

   ```sh
   ./install.sh
   ```

5. Enter the RAM endpoint, store ID, `northstar-pilot-demo`, participant ID
   `hillary`, and the API key when prompted. The key prompt is hidden.
6. Open the supplied demo workspace in VS Code.
7. In the integrated terminal, start:

   ```sh
   ~/.local/bin/redis-memory-editor
   ```

8. Accept the workspace trust prompt if it appears.
9. Ask Claude to run `editor_status`; verify Editor, the presentation namespace,
   and a live connection.
10. Search for the seeded region memory, update it, and wait for
    `saved_and_searchable` before continuing the presentation.

### Teammate's PC — Reader

1. Confirm prerequisites:

   ```sh
   claude --version
   node --version
   ```

2. Copy only `redis-shared-memory-reader-<version>.zip` and `SHA256SUMS` to a
   local folder.
3. Verify the checksum using the command in the Reader guide.
4. Unzip the package and run:

   ```sh
   ./install.sh
   ```

5. Enter the same endpoint, store ID, and `northstar-pilot-demo` namespace.
   Use participant ID `demo-reader` and enter the API key at the hidden prompt.
6. Open the supplied demo workspace in VS Code.
7. In the integrated terminal, start:

   ```sh
   ~/.local/bin/redis-memory-reader
   ```

8. Accept the workspace trust prompt if it appears.
9. Ask Claude to run `reader_status`; verify Reader, the presentation namespace,
   and a live connection.
10. Ask the agreed business question and confirm the response cites Redis memory
    IDs. After Hillary updates a fact, repeat the prompt and confirm the changed
    record is retrieved.
11. Ask Reader to change a shared fact and confirm no write tool exists.

### Uninstall or reinstall

Each package installs a role-specific uninstaller. Run:

```sh
~/.local/share/redis-shared-memory/<role>/current/uninstall.sh
```

The uninstaller removes that role's executable, MCP configuration, installed
bundle, and local credential file. It does not delete or modify RAM memories and
does not remove the other role. Reinstall by unzipping the same verified artifact
and running `./install.sh` again.

## Demo Acceptance

The demo is ready only when:

- Both installed artifacts match the recorded release checksums.
- Both PCs report a verified connection to the same store and namespace.
- Both users independently retrieve the same seeded memory IDs.
- Hillary updates one existing memory and Reader retrieves the new value using
  that same ID.
- Reader has no write tools.
- No RAM key appears in the repository, demo workspace, Claude configuration,
  logs, screenshots, or presentation output.

## Known Limitations

- Both PCs possess the store API key. Reader is an integration-level boundary,
  not a store-credential authorization boundary.
- A policy smoke test on Hillary's Mac with Claude Code 2.1.267 successfully
  added, launched, connected to, listed, and removed a harmless local stdio MCP
  server. No managed MCP allowlist, denylist, managed-MCP-only restriction, or
  plugin-only MCP restriction was found. Assuming the teammate's stated policy
  is identical, this validates the proposed local MCP mechanism on both PCs; it
  does not replace final testing of the packaged Reader and Editor servers or
  their live Redis Agent Memory connection.
- Retrieved memory is untrusted input. The server labels it as reference data,
  but the demo must use only controlled synthetic records.
- The teammate runs local custom code. This passed the current Claude Code MCP
  policy smoke test, but endpoint protection software could still independently
  block an artifact; checksum verification and source/build provenance are part
  of the handover.
- The current organization policy prevents persistent user-defined permission
  allow rules. Reader therefore uses restricted auto mode; Editor keeps manual
  approval for writes.
- The plan currently targets macOS. A Windows package requires separate launcher,
  credential-permission, and installation testing.
