# ChatGPT desktop plugin installation

This plugin lets multiple users and their agents work from one Redis Agent
Memory store and approved Redis Agent Playbook. Every user installs the same
plugin and configures the same service endpoints, RAM store ID, and namespace.
Credentials stay on that user's computer.

## Before you begin

You need:

- ChatGPT desktop with Codex plugin support;
- the Codex CLI;
- Python 3.10 or newer available as `python3`;
- the shared RAM endpoint, store ID, namespace, and management-state owner;
- preferably a unique private RAM namespace for this user (otherwise it is
  derived from the participant ID);
- the shared Redis Agent Playbook MCP URL;
- a participant ID plus RAM and Playbook API keys for this user; and
- enterprise approval for the Git repository/ref, local Python execution, and
  outbound HTTPS access to both service endpoints.

Check the local prerequisites:

```sh
python3 -c 'import sys; print(sys.version); raise SystemExit(sys.version_info < (3, 10))'
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
readable standard-library Python, reviewed runtime hooks, and no downloaded
runtime or package-manager step. Local installation is separate from publication in the
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

Create the file outside the repository and plugin cache:

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
RAM_ENDPOINT=https://your-memory-endpoint.redis.io
RAM_STORE_ID=shared-store
RAM_NAMESPACE=shared-namespace
RAM_PERSONAL_NAMESPACE=private-your-user-id
RAM_PARTICIPANT=your-user-id
RAM_API_KEY=your-user-api-key
RAM_AGENDA_OWNER_ID=ami-project-office
PLAYBOOK_MCP_URL=https://your-playbook-endpoint.redis.io/v1/playbooks/your-playbook-id/mcp
PLAYBOOK_API_KEY=your-user-playbook-api-key
```

Do not paste the API key into a ChatGPT conversation or commit it to Git.

The values have these roles:

| Setting | Shared or per user | Purpose |
| --- | --- | --- |
| `RAM_ENDPOINT` | Shared | HTTPS RAM data-plane endpoint. URLs with embedded credentials, a query, or a fragment are rejected. |
| `RAM_STORE_ID` | Shared | Store used by the team. |
| `RAM_NAMESPACE` | Shared | Namespace that scopes every read and write. |
| `RAM_PERSONAL_NAMESPACE` | Per user, optional | Private namespace for this user's captured session events and RAM-derived personal memory. It defaults to `private-{RAM_PARTICIPANT}`. Set it explicitly when participant IDs are not globally unique. |
| `RAM_PARTICIPANT` | Per user | Contributor attribution. It is not authenticated identity. |
| `RAM_API_KEY` | Per user when supported | Credential that authenticates RAM requests. |
| `RAM_AGENDA_OWNER_ID` | Shared | Exact owner lane containing immutable `organizational_state` observations and derived `organizational_state_projection` records. |
| `PLAYBOOK_MCP_URL` | Shared | Full approved Playbook MCP URL ending in `/v1/playbooks/{playbookId}/mcp`. |
| `PLAYBOOK_API_KEY` | Per user when supported | Credential that authenticates Playbook MCP requests. |

Store ID, namespace, participant, and agenda owner accept 1–64 letters,
digits, or hyphens.
Issue a different API key to each user when the service supports it so access
can be revoked and audited independently. If users share an API key,
`RAM_PARTICIPANT` remains self-asserted metadata; do not treat it as a security
identity. Server-validated OAuth can replace this limitation later without
changing the tool model.

## 3. Install the plugin in ChatGPT desktop

1. Restart ChatGPT desktop after adding the marketplace.
2. Open the Plugins directory.
3. Choose **Redis Field Engineering**.
4. Install **Redis Shared Memory + Playbook**.
5. Start a new chat.

Keep normal approval prompts enabled for write tools. `editor_publish` creates
a fact, `editor_update` replaces an existing fact by exact memory ID, and
`memory_candidate_promote` creates a new immutable shared organizational-state
observation after explicit confirmation. `memory_state_update_propose` creates
only a private candidate from an exact hook-captured prompt and exact current
state. Hooks themselves never write the shared namespace.

## 4. Verify one user, then the group

Before testing private capture, review the installed hooks from Codex CLI:

```sh
cd /path/to/ram-and-playbook-codex-plugin
codex
```

Enter `/hooks`, find `redis-shared-memory-editor@redis-field-engineering`,
review `UserPromptSubmit` and `SessionEnd`, and trust them only after checking
their commands and source. Then restart ChatGPT desktop and start a new chat.
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
returns timestamped source observations, Playbook discovery returns an exact
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
[docs/admin-bootstrap.md](docs/admin-bootstrap.md).

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
python3 scripts/reconcile_management_state.py \
  --apply \
  --wait-for-candidate <candidate-id-returned-by-the-plugin> \
  --timeout-seconds 420
```

The PoC host also runs the same command centrally every five minutes with
`--apply --quiet-no-changes`. This catches document and session extraction that
does not originate from an interactive promotion. RAM's ingestion webhook is a
blocking decision hook, not a completion notification, so it is not used as a
post-extraction trigger.

Expected: the deterministic current projection changes to the confirmed
lifecycle. An unconfirmed or merely
"probably completed" action remains nonterminal. See
[docs/management-reconciliation.md](docs/management-reconciliation.md).

Before asking users to install a release, the maintainer should also run in a
clean checkout:

```sh
python3 -m unittest discover -s tests -v
python3 evaluation/run.py
```

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

Restart ChatGPT desktop and start a new chat. Installations pinned to a commit
SHA do not move automatically; approve a new SHA and add that ref when a new
release is ready. The desktop app caches installed plugin files, so editing a
checkout alone does not update an already installed copy.

## Remove

Uninstall **Redis Shared Memory + Playbook** in the Plugins directory, then remove
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
| `configuration_missing` | Create the file at the exact path above and fill the eight required settings. `RAM_PERSONAL_NAMESPACE` may be omitted when `private-{RAM_PARTICIPANT}` is acceptable. |
| Hooks do not capture | Review the plugin's hooks in Codex, confirm they are trusted/enabled, and start a new chat. |
| Private events exist but no personal memories appear | Confirm the RAM session worker and model provider are running and the store has the intended personal custom extraction enabled. |
| Promotion returns `write_unverified` | Read the deterministic observation ID from the candidate before attempting another write. Do not blindly resubmit. |
| History contains the promoted observation but current state is unchanged | Run the central reconciliation job for the returned candidate ID, or wait for the five-minute central schedule. Do not promote again. |
| Credential file permission or owner error | Confirm the file belongs to the signed-in OS user and run `chmod 600 ~/.config/redis-shared-memory/editor.env`. |
| `authentication_failed`, `access_denied`, or `playbook_authentication_failed` | Replace or reissue the affected service key and confirm its least-privilege access. |
| `network_error` or `playbook_unavailable` | Check both HTTPS endpoints, VPN, DNS, proxy, and enterprise allowlist. |
| `dependency_unavailable` | Retry a read once; if it persists, contact the Redis service owner. Do not blindly retry a write. |
| A repository change is not visible | Upgrade the marketplace, restart the app, and start a new chat. |

For marketplace command details, see OpenAI's
[plugin build and installation documentation](https://developers.openai.com/plugins/build/plugins).
