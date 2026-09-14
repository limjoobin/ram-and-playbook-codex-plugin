# Cross-user Redis Agent Memory demo

Two portable local MCP packages let Claude Desktop or Claude Code users retrieve the same
business Agent Memory records from separate Macs. The **Editor** can search,
publish, and update; the **Reader** exposes only status and search. Claude Code
can be launched from VS Code's integrated terminal or any other terminal.

This path does not use Claude Desktop extensions, Claude Code plugins, hooks,
a hosted MCP service, or a tunnel. Both packages connect directly to one Redis
Agent Memory HTTPS endpoint, store ID, and namespace.

## Clone and install for Claude Desktop

The repository can install either role into Claude Desktop while keeping the
connection in Claude Desktop's JSON configuration. The installer builds from
the locked source dependencies, prompts for the RAM API key with terminal echo
disabled, stores credentials outside the repository, preserves existing MCP
servers, and performs a real RAM status read.

Prerequisites are macOS, Git, Claude Desktop (opened once), and Node.js 20+.
Claude Code CLI is not required for Desktop use.

```sh
git clone https://github.com/redis-field-engineering/cross-user-ram.git
cd cross-user-ram
./scripts/install-claude-desktop.sh reader
```

For the Editor role, replace `reader` with `editor`. A Reader user can instead
double-click `Install Reader for Claude Desktop.command` in Finder after
cloning. The installer adds only the matching `redis-shared-memory-<role>` entry
to `~/Library/Application Support/Claude/claude_desktop_config.json`; the RAM
API key remains in `~/.config/redis-shared-memory/<role>.env` with mode `0600`.

Fully quit and reopen Claude Desktop after installation. Uninstall with:

```sh
~/.local/share/redis-shared-memory/<role>/current/uninstall.sh
```

The uninstaller removes only the matching Desktop MCP entry, local role files,
and local credential. It never changes shared RAM records.

## Build and verify

Development requires Node.js 20+. Python is needed only to seed the fictional
demo fixtures.

```sh
npm ci
npm run check
uv sync --frozen
uv run python -m unittest discover -s tests -p 'test_*.py'
```

The build produces:

```text
dist/claude-code/redis-shared-memory-editor-0.1.1.zip
dist/claude-code/redis-shared-memory-reader-0.1.1.zip
dist/claude-code/SHA256SUMS
dist/claude-code/release.json
```

Each ZIP includes its bundled Node MCP server, installer, launcher, uninstaller,
role instructions, integrity manifest, and dependency notices. End users never
run `npm install` and do not need this source repository.

## Seed and live-test

Set the non-secret values locally. The helper prompts for the API key with echo
disabled when it is not already present in the environment.

```sh
export RAM_ENDPOINT='https://your-memory-endpoint.redis.io'
export RAM_STORE_ID='your-store-id'
uv run python scripts/seed.py seed --namespace northstar-pilot-qa
uv run python scripts/seed.py verify --namespace northstar-pilot-qa
uv run python scripts/seed.py seed --namespace northstar-pilot-demo
uv run python scripts/live-terminal.py
```

Live tests are restricted to `northstar-pilot-qa` and intentionally leave one
synthetic QA memory behind. Normal seeding is idempotent and preserves existing
updates. `reset` restores only the six deterministic fixture IDs and does not
delete unrelated records. To clear a demo, use the Agent Memory Console's
memory-clear action; never use Redis `FLUSHDB`/`FLUSHALL` or delete its backing
keys through Redis Insight.

## Installation and use

See the [Editor package runbook](docs/editor-package-runbook.md),
[Reader package runbook](docs/reader-package-runbook.md), and
[two-PC acceptance checklist](docs/local-acceptance.md). Each ZIP contains its
own runbook as `RUNBOOK.md`. In outline, each
user verifies and unzips their role package, runs `./install.sh`, and then starts
Claude Code with one of:

```sh
~/.local/bin/redis-memory-editor
~/.local/bin/redis-memory-reader
```

The installer requires macOS, Claude Code CLI, and Node.js 20+. It asks for the
RAM key with terminal echo disabled, writes it outside workspaces with mode
`0600`, checks the exact role's tool list, and performs a real RAM status read.
The launcher creates a temporary non-secret MCP configuration and invokes Claude
Code with restricted mode, a role-specific MCP tool allowlist containing no
built-in tools, and strict MCP isolation.

## Security boundary

Reader has no write tools, and its server rejects mutation methods before any
RAM request. This is a tool-level boundary for a trusted demonstration. The
shared store API key may still permit direct writes outside the Reader package.
Participant IDs are labels, not authenticated identities.

No tool provides deletion, arbitrary HTTP, arbitrary namespace selection,
shell/file access, or automatic conversation capture. Retrieved memory is
labelled as untrusted reference data. Use only the included fictional Northstar
Retail records in the demo.

References: [Claude Code MCP](https://code.claude.com/docs/en/mcp),
[Claude Code CLI](https://code.claude.com/docs/en/cli-usage), and
[Redis Agent Memory SDKs](https://github.com/redis/iris-sdks).
