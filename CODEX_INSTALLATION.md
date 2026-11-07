# Per-user ChatGPT desktop plugin installation

This plugin lets multiple users and their agents work from one Redis Agent
Memory store and approved Redis Agent Playbook. Every user installs the same
plugin and configures the same service endpoints, RAM store ID, and namespace.
Credentials stay on that user's computer.

This is the participant installation guide. It assumes an administrator has
already provisioned RAM and Playbook, declared the two memory types, published
the agenda Skill, ingested the approved corpus, and started central
reconciliation. For a fresh environment, complete
[DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md) first.

Installing the plugin does not deploy either service, run MemoryETL, hydrate
the shared store, publish Playbook content, or install the central scheduler.
Hook trust is also a manual per-user decision; it cannot be granted by this
repository or by the environment administrator.

## Before you begin

You need:

- ChatGPT desktop with Codex plugin support;
- the Codex CLI;
- Python 3.11 or newer available as `python3`;
- the shared RAM endpoint, store ID, namespace, and management-state owner;
- preferably a unique private RAM namespace for this user (otherwise it is
  derived from the participant ID);
- the shared Redis Agent Playbooks data-plane URL, playbook ID, and a reader key;
- a participant ID plus a RAM API key and a Playbook reader key for this user; and
- enterprise approval for the Git repository/ref, local Python execution,
  outbound HTTPS access to both service endpoints, and HTTPS access to the
  Python package index (pypi.org and files.pythonhosted.org, or the enterprise
  mirror that `pip` is configured to use) for the one-time runtime install.

The environment administrator should also give you the exact approved Git
tag or commit, confirm that the management context and corpus are ready, and
confirm that central reconciliation is healthy. If any of those are missing,
stop here and use [the administrator guide](DEMO_ENVIRONMENT_SETUP.md).

Check the local prerequisites:

```sh
python3 -c 'import sys; print(sys.version); raise SystemExit(sys.version_info < (3, 11))'
codex --version
```

If `codex` is not on `PATH` on macOS but ChatGPT desktop is installed, use the
bundled executable explicitly:

```sh
"/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex" --version
```

Use that full executable path in place of `codex` in the commands below.

macOS does not guarantee a suitable Python version. On a managed laptop, use
the Python distribution approved by your administrator.

Adding a Git marketplace installs code that runs locally. An administrator can
allowlist the repository and an exact tag or commit. This repository contains
readable Python, reviewed runtime hooks, and exact dependency pins
(`server/requirements.txt`) that `server/launch.py` installs once into a
private virtual environment under the plugin data directory (step 4). Local installation is separate from publication in the
public plugin directory. See OpenAI's
[desktop deployment guide](https://developers.openai.com/plugins/deploy/desktop-only)
for the supported installation model.

The plugin currently activates only `UserPromptSubmit` and `SessionEnd`
command hooks. `PostToolUse` and `Stop` are intentionally unregistered. Codex
requires review/trust before non-managed plugin hooks run. Inspect the installed
`hooks/hooks.json` and `hooks/capture.py`, then approve only if their
private-capture behavior matches your policy. See OpenAI's
[hooks documentation](https://learn.chatgpt.com/docs/hooks) and
[plugin build guide](https://developers.openai.com/plugins/build/plugins).

For a multi-user deployment, both configured endpoints must be reachable from
every approved laptop. A loopback `http://127.0.0.1` or `http://localhost`
endpoint is accepted only for local development and cannot provide a shared
team service across laptops. Customer rollout endpoints should use HTTPS.

## 1. Add the marketplace

The current development ref is:

```sh
codex plugin marketplace add redis-field-engineering/ram-and-playbook-codex-plugin --ref plugin-wireframe
codex plugin marketplace list
```

For a customer rollout, replace `plugin-wireframe` with the administrator-
approved release tag or commit SHA. If the repository is private, Git access
and credentials must already be configured for the user; the plugin does not
bypass GitHub or enterprise policy.

To review and install from a local checkout instead:

```sh
git clone --branch plugin-wireframe --single-branch https://github.com/redis-field-engineering/ram-and-playbook-codex-plugin.git
cd ram-and-playbook-codex-plugin
codex plugin marketplace add "$PWD"
```

## 2. Create the private configuration

The easiest way is the guided command in a repository checkout,
`python3 scripts/setup_demo.py` (see the README's Step 9). It asks for each
value, hides keys as you type, and writes this file with the right
permissions. To create the file by hand instead, keep it outside the
repository and plugin cache:

```sh
mkdir -p "$HOME/.config/redis-shared-memory"
chmod 700 "$HOME/.config/redis-shared-memory"
touch "$HOME/.config/redis-shared-memory/editor.env"
chmod 600 "$HOME/.config/redis-shared-memory/editor.env"
```

On macOS, open the file directly in TextEdit:

```sh
open -e "$HOME/.config/redis-shared-memory/editor.env"
```

To reveal the hidden file in Finder instead:

```sh
open -R "$HOME/.config/redis-shared-memory/editor.env"
```

Opening the file may require normal desktop approval when an agent runs the
command. Add these settings in the local editor:

```dotenv
IRIS_AGENT_MEMORY_URL=https://your-region.memory.redis.io
IRIS_AGENT_MEMORY_STORE_ID=st_your-store-id
IRIS_AGENT_MEMORY_API_KEY=your-user-api-key
RAM_NAMESPACE=shared-namespace
RAM_PERSONAL_NAMESPACE=private-your-user-id
RAM_PARTICIPANT=your-user-id
RAM_AGENDA_OWNER_ID=ami-project-office
IRIS_AGENT_PLAYBOOKS_URL=https://your-playbook-endpoint.redis.io
IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID=pb_your-playbook-id
IRIS_AGENT_PLAYBOOKS_API_KEY=your-user-playbook-reader-key
```

The same names are in the repository's `.env.example`. The names are exact;
the pre-0.13.0 names are rejected as unexpected settings.

Do not paste the API key into a ChatGPT conversation or commit it to Git.

The values have these roles:

| Setting | Shared or per user | Purpose |
| --- | --- | --- |
| `IRIS_AGENT_MEMORY_URL` | Shared | HTTPS RAM data-plane base URL. URLs with embedded credentials, a query, or a fragment are rejected. |
| `IRIS_AGENT_MEMORY_STORE_ID` | Shared | Store used by the team (Redis Cloud IDs look like `st_` plus 32 hex characters). Letters, digits, underscores, and hyphens, 1–64. |
| `IRIS_AGENT_MEMORY_API_KEY` | Per user when supported | Credential that authenticates RAM requests. |
| `RAM_NAMESPACE` | Shared | Namespace that scopes every read and write. The plugin creates it as a shared namespace on first write if it does not exist; reads never create namespaces. |
| `RAM_PERSONAL_NAMESPACE` | Per user, optional | Private namespace for this user's captured session events and RAM-derived personal memory. It defaults to `private-{RAM_PARTICIPANT}`. Set it explicitly when participant IDs are not globally unique. On first write it is created as a personal namespace owned by `RAM_PARTICIPANT`. |
| `RAM_PARTICIPANT` | Per user | Contributor attribution. It is not authenticated identity. |
| `RAM_AGENDA_OWNER_ID` | Shared | Exact owner lane containing immutable `organizational_state` observations and derived `organizational_state_projection` records. |
| `IRIS_AGENT_PLAYBOOKS_URL` | Shared | Playbooks data-plane base URL only, for example `https://your-playbook-endpoint.redis.io`. Do not include an `/iris/data/v1/agent-playbooks/...` path; the SDK appends it. Loopback `http` is accepted for local development only. |
| `IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID` | Shared | Playbook ID: `pb_` followed by 32 lowercase hex characters. |
| `IRIS_AGENT_PLAYBOOKS_API_KEY` | Per user when supported | Runtime reader key that authenticates Playbook reads. |
| `RAM_MEMORY_LAYOUT` | Shared, optional | How management records are stored in RAM custom memory types. `compact` (default) uses the one 9-field `organizational_state` type that the README's console steps create; `expanded` uses the original `organizational_state` and `organizational_state_projection` types. Every participant of a store must use the store's layout. |
| `RAM_CAPTURE_FOLDERS` | Per user, optional | Absolute folders, separated by `:`, whose sessions the private-capture hooks may record. Empty or unset means the hooks record nothing anywhere. `scripts/setup_demo.py` sets it to the project folder. Plugins install account-wide, so this keeps prompts from other projects out of private memory even if the plugin is enabled elsewhere. |

Environment administrators may also keep these optional names in the same file:
`IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY` (read/write/publish key used by
`iris agent-playbooks skills ...`), `IRIS_AGENT_PLAYBOOKS_SERVICE_URL`,
`IRIS_AGENT_PLAYBOOKS_SERVICE_TOKEN`, `IRIS_AGENT_MEMORY_SERVICE_URL`, and
`IRIS_AGENT_MEMORY_SERVICE_TOKEN`. The desktop MCP accepts these names but
deliberately never copies their values into its runtime configuration.
Ordinary participants leave them unset. The names match those used by the SDK
and the `iris` CLI.

### Upgrading from 0.12.x

Version 0.13.0 uses the redis-iris SDK and renames the settings. There is no
fallback: the old names are rejected as unexpected. Edit the file in place.

| 0.12.x | 0.13.0 |
| --- | --- |
| `RAM_ENDPOINT` | `IRIS_AGENT_MEMORY_URL` |
| `RAM_STORE_ID` | `IRIS_AGENT_MEMORY_STORE_ID` |
| `RAM_API_KEY` | `IRIS_AGENT_MEMORY_API_KEY` |
| `PLAYBOOK_MCP_URL` (full `/v1/playbooks/{id}/mcp` URL) | `IRIS_AGENT_PLAYBOOKS_URL` (base URL only) plus new `IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID` |
| `PLAYBOOK_API_KEY` | `IRIS_AGENT_PLAYBOOKS_API_KEY` (reader key) |
| `RAM_ADMIN_API_KEY`, `PLAYBOOK_PUBLISHER_API_KEY`, `OPENAI_API_KEY` | Removed. Administrators publishing a Skill use `IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY`. |

`RAM_NAMESPACE`, `RAM_PERSONAL_NAMESPACE`, `RAM_PARTICIPANT`, and
`RAM_AGENDA_OWNER_ID` are unchanged. Python 3.11+ is now required, and the new
runtime must be installed (step 4).

The hook definitions are unchanged from 0.12.x, so existing hook trust still
applies. Hooks stay standard-library only and never load the SDK or touch the
network: each hook writes its private event to a local queue (`0600` files in
a `0700` directory under the plugin data directory) and returns. The running
MCP server, which loads the SDK once per session, delivers queued events to
RAM, normally within a second.

Namespace, participant, and agenda owner accept 1–64 letters, digits, or
hyphens.
Issue a different API key to each user when the service supports it so access
can be revoked and audited independently. If users share an API key,
`RAM_PARTICIPANT` remains self-asserted metadata; do not treat it as a security
identity. Server-validated OAuth can replace this limitation later without
changing the tool model.

## 3. Install the plugin in ChatGPT desktop

1. Restart ChatGPT desktop after adding the marketplace.
2. Open **Settings** → **Plugins** and select **Browse directory**. (The
   **Marketplace** tab only lists catalogs; it cannot install.)
3. On the **Personal** tab, under **Redis Field Engineering**, select **+** next
   to **Redis Shared Memory + Playbook**. Alternatively run
   `codex plugin add redis-shared-memory-editor@redis-field-engineering`.
4. Start a new chat.

Keep normal approval prompts enabled for write tools. `editor_publish` creates
a fact, `editor_update` replaces an existing fact by exact memory ID, and
`memory_candidate_promote` creates a new immutable shared organizational-state
observation after explicit confirmation. `memory_state_update_propose` creates
only a private candidate from an exact hook-captured prompt and exact current
state. Hooks themselves never write the shared namespace.

## 4. Install the runtime

The plugin runs on the pinned redis-iris SDK. On first launch,
`server/launch.py` (standard library only) creates one private virtual
environment under `$PLUGIN_DATA/runtime/py<version>-<requirements hash>/` and
installs the exact pins from `server/requirements.txt` with
`pip --only-binary=:all:`. This needs HTTPS access to the Python package index.
Pre-install it right after installing the plugin so the first MCP start is not
slow. Export the same `PLUGIN_DATA` that the MCP server and hooks use:

```sh
export PLUGIN_DATA="${CODEX_HOME:-$HOME/.codex}/plugins/data/redis-shared-memory-editor-redis-field-engineering"
python3 "${CODEX_HOME:-$HOME/.codex}/plugins/cache/redis-field-engineering/redis-shared-memory-editor/0.13.0/server/launch.py" --install
python3 "${CODEX_HOME:-$HOME/.codex}/plugins/cache/redis-field-engineering/redis-shared-memory-editor/0.13.0/server/launch.py" --check
```

`--check` exits 0 when the runtime is ready. The launcher is macOS/Linux only.
Hooks do not need the runtime: they only queue private events locally, and the
MCP server delivers them. Events captured while no MCP server is running (for
example a `SessionEnd` after Codex stops the server) are delivered by the next
server start. `system_status` reports the queue depth as
`private_capture.queued_events`. Installing a new plugin version creates a new
runtime directory the first time its requirements hash is used.

## 5. Verify one user, then the group

ChatGPT installs plugins for the whole user account. To keep the plugin's
tools and hooks out of other projects, `scripts/setup_demo.py` sets
`enabled = false` for `redis-shared-memory-editor@redis-field-engineering` in
`~/.codex/config.toml` (after backing it up), and the repository's
`.codex/config.toml` sets `enabled = true`. Codex honours a project's settings
only once that folder is trusted, and project enablement needs Codex 0.151.0
or later for a local marketplace. Start chats in the project folder.

Review the installed hooks before testing private capture. ChatGPT desktop
shows **Review hooks** on the first message after installation, listing
**Capturing private memory intent** (`UserPromptSubmit`) and **Recording
private session end** (`SessionEnd`). Allow them only after checking their
commands and source. From Codex CLI, `codex` prompts for the same review, and
`/hooks` opens it later.
Hook trust is stored for the user and the exact hook definition; it is not tied
to this working directory. Running from the plugin checkout simply makes local
marketplace troubleshooting clearer. A changed hook definition requires a new
review.

Ask the first user to run:

```text
Run editor_status and report the connection, namespace, participant, and permissions.
```

Expected: `connection` is `verified`, the namespace and participant match the
local file, and permissions include search, publish, and update.

Then ask:

```text
Search shared memory for a known team fact and return its memory ID and fact.
```

If writes are authorized, publish one non-sensitive fact explicitly approved
for the shared store. A second user configured with the same endpoint, store,
and namespace should be able to retrieve it. Their participant and preferably
their API key should be different.

Verify the management read surface separately:

```text
Run system_status. Do not display endpoints or credentials.
Resolve the "remote control project" entity, then search its current organizational state using the default current view.
Search the same project with the history view and confirm it returns immutable observations with source-event ordering metadata.
Discover the prepare-management-review-agenda Playbook entry and report only its ID and version.
Prepare the management review agenda for 2026-11-15 with at most 8 items.
```

Expected: both upstreams are available, entity resolution returns
`project-ami-es2002`, the current view returns projections, the history view
returns timestamped source observations, Playbook discovery (a read-only REST call to the Playbooks data plane) returns an exact
version without exposing either endpoint or credential, and agenda output uses
separate structured searches for every state kind. It returns the full
owner-grouped action-item register plus confirmed decisions, completed work,
open work, a human-editable management-topic draft, and the result of a bounded
read-only conflict-reconciliation pass. The agenda-item maximum does not
truncate the context registers. Missing owners or decision fields do not
suppress a topic; uncited or over-capacity candidates are explicitly deferred.

On a v3 test store, confirmed generic relationships are returned as
`confirmed_relations` on current-state results. Proposed and rejected
relationships remain visible only in history and never change projected
lifecycle status. Existing v2 stores remain readable, but reinstalling the
plugin does not add the v3 `relations` field to an existing RAM custom-memory
type; use the reviewed fresh-store bootstrap path described in
[DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md).

These checks are the manual acceptance gate. Passing repository tests and the
offline evaluation does not prove that a customer's network, credentials,
store contents, Playbook publication, or desktop policy is configured
correctly.

Verify the private lifecycle-update flow separately:

```text
At 2026-10-27T09:15:00Z, I completed the trend-watching artifact. Publish this update to shared memory, but show me the exact proposed update before sharing it.
```

Expected: `UserPromptSubmit` records the exact statement only in the personal
namespace and directs the agent to retrieve the current state. The agent calls
`memory_state_update_propose` with the returned `state_id`, its current
lifecycle, the complete prompt, and the explicit completion time as
`resolved_at`. The proposal preserves the current project, owner, subject, and
capture time and makes no shared write. The agent must inspect the
candidate and ask for explicit confirmation before calling
`memory_candidate_promote`. `PostToolUse` and `Stop` remain inactive.

After promotion, the shared observation is already stored and verified; there
is no MemoryETL wait. The central administrator then runs the versioned
reconciliation job from a repository checkout:

```sh
.venv/bin/python scripts/reconcile_management_state.py \
  --apply \
  --wait-for-candidate <candidate-id-returned-by-the-plugin> \
  --timeout-seconds 420
```

The promoted observation has no document source. Verify it independently by
calling `ram_get_evidence` with the exact promoted `memory_id` and no
`source_id`; the returned lifecycle, owner, resolution time, and candidate
locator must match the reviewed update. A subsequent agenda should cite this
RAM-memory reference for completed work rather than only the original
assignment document.

The environment administrator's PoC host also runs the same command centrally
every five minutes with `--apply --quiet-no-changes`. This catches document and
session extraction that does not originate from an interactive promotion.
RAM's ingestion webhook is a blocking decision hook, not a completion
notification, so it is not used as a post-extraction trigger.

Expected: the deterministic current projection changes to the confirmed
lifecycle. An unconfirmed or merely
"probably completed" action remains nonterminal. See
[docs/management-reconciliation.md](docs/management-reconciliation.md).

Before asking users to install a release, the maintainer should also run in a
clean checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r plugins/redis-shared-memory-editor/server/requirements.txt
.venv/bin/python scripts/validate_context_pipeline.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evaluation/run.py
```

The administrator-owned central scheduler checkout must be clean and pinned to
that same approved commit or tag. Detach it at the approved SHA, kick the
scheduler once, and confirm `git rev-parse HEAD` matches the plugin release
before completing the live acceptance test. See
[DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md) and
[docs/management-reconciliation.md](docs/management-reconciliation.md).

## Update

For a Git marketplace that Codex cloned and tracks itself:

```sh
codex plugin marketplace upgrade redis-field-engineering
```

If `codex plugin marketplace list` shows a normal local checkout as the
marketplace root, `marketplace upgrade` does not pull that checkout. Update it
and refresh the installed cache explicitly:

```sh
cd /path/reported/for/redis-field-engineering
git pull --ff-only origin plugin-wireframe
codex plugin remove redis-shared-memory-editor@redis-field-engineering
codex plugin add redis-shared-memory-editor@redis-field-engineering
```

After an update, re-run the `--install` command from step 4 with the new version in the cache path. Restart ChatGPT desktop and start a new chat. Installations pinned to a commit
SHA do not move automatically; approve a new SHA and add that ref when a new
release is ready. The desktop app caches installed plugin files, so editing a
checkout alone does not update an already installed copy.

## Remove

Uninstall the plugin with
`codex plugin remove redis-shared-memory-editor@redis-field-engineering`, then remove
the marketplace if it is no longer needed:

```sh
codex plugin marketplace remove redis-field-engineering
```

Removal does not delete `~/.config/redis-shared-memory/editor.env` or any RAM
records. Keep the file if another approved integration uses it; otherwise
remove it through the laptop's approved file-management process.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Marketplace or plugin is not visible | Run `codex plugin marketplace list`, confirm the approved ref and Git access, then restart ChatGPT desktop. |
| Local server will not start | Run the Python version check above and confirm enterprise policy permits `python3`. |
| Runtime install fails or the first MCP start is slow or times out | Confirm HTTPS access to the Python package index (pypi.org and files.pythonhosted.org, or the configured mirror), then run `launch.py --install` from step 4 and `--check`. |
| `configuration_invalid` for the Playbook URL | `IRIS_AGENT_PLAYBOOKS_URL` must be the base URL only, with no `/iris/data/v1/agent-playbooks/...` or `/v1/playbooks/...` path. Put the ID in `IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID`. |
| A pre-0.13.0 setting name is reported as unexpected | Rename it using the "Upgrading from 0.12.x" table. |
| "Private RAM capture is unavailable" | The hook could not read the credential file or write the local queue. Check the credential file and that the plugin data directory is writable. |
| `private_capture.queued_events` keeps growing | The MCP server cannot reach RAM. Fix the error `system_status` reports for RAM; queued events are delivered once it recovers. Events RAM rejects outright are moved to `promotion/outbox/rejected/`. |
| `configuration_missing` | Create the file at the exact path above and fill the nine required settings. `RAM_PERSONAL_NAMESPACE` may be omitted when `private-{RAM_PARTICIPANT}` is acceptable. |
| Hooks do not capture | Review the plugin's hooks in Codex, confirm they are trusted/enabled, and start a new chat. Confirm the MCP runtime is installed (`launch.py --check`) so the server can deliver queued events. |
| Private events exist but no personal memories appear | Confirm the RAM session worker and model provider are running and the store has the intended personal custom extraction enabled. |
| Promotion returns `write_unverified` | Read the deterministic observation ID from the candidate before attempting another write. Do not blindly resubmit. |
| History contains the promoted observation but current state is unchanged | Run the central reconciliation job for the returned candidate ID, or wait for the five-minute central schedule. Do not promote again. |
| Credential file permission or owner error | Confirm the file belongs to the signed-in OS user and run `chmod 600 ~/.config/redis-shared-memory/editor.env`. |
| `authentication_failed`, `access_denied`, or `playbook_authentication_failed` | Replace or reissue the affected service key and confirm its least-privilege access. |
| `network_error` or `playbook_unavailable` | Check both HTTPS endpoints, VPN, DNS, proxy, and enterprise allowlist. |
| `playbook_not_found` | Check `IRIS_AGENT_PLAYBOOKS_URL` is the data-plane base URL with no path, and `IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID` names an existing playbook. |
| `playbook_entry_not_found` or `playbook_resource_not_found` | The agenda Skill version, or one of its resources, is not published. Republish the entry from `playbook/manifest.json`. |
| `dependency_unavailable` | Retry a read once; if it persists, contact the Redis service owner. Do not blindly retry a write. |
| A repository change is not visible | Upgrade the marketplace, restart the app, and start a new chat. |

For marketplace command details, see OpenAI's
[plugin build and installation documentation](https://developers.openai.com/plugins/build/plugins).
