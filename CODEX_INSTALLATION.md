# ChatGPT desktop plugin installation

This plugin lets multiple users and their agents work from one Redis Agent
Memory store. Every user installs the same plugin and configures the same RAM
endpoint, store ID, and namespace. Credentials stay on that user's computer.

## Before you begin

You need:

- ChatGPT desktop with Codex plugin support;
- the Codex CLI;
- Python 3.10 or newer available as `python3`;
- the shared RAM endpoint, store ID, and namespace;
- a participant ID and RAM API key for this user; and
- enterprise approval for the Git repository/ref, local Python execution, and
  outbound HTTPS access to the RAM endpoint.

Check the local prerequisites:

```sh
python3 -c 'import sys; print(sys.version); raise SystemExit(sys.version_info < (3, 10))'
codex --version
```

macOS does not guarantee a suitable Python version. On a managed laptop, use
the Python distribution approved by your administrator.

Adding a Git marketplace installs code that runs locally. An administrator can
allowlist the repository and an exact tag or commit. This repository contains
readable standard-library Python and no install hooks, downloaded runtime, or
package-manager step. Local installation is separate from publication in the
public plugin directory. See OpenAI's
[desktop deployment guide](https://developers.openai.com/plugins/deploy/desktop-only)
for the supported installation model.

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

Open `~/.config/redis-shared-memory/editor.env` in a local text editor and add:

```dotenv
RAM_ENDPOINT=https://your-memory-endpoint.redis.io
RAM_STORE_ID=shared-store
RAM_NAMESPACE=shared-namespace
RAM_PARTICIPANT=your-user-id
RAM_API_KEY=your-user-api-key
```

Do not paste the API key into a ChatGPT conversation or commit it to Git.

The values have these roles:

| Setting | Shared or per user | Purpose |
| --- | --- | --- |
| `RAM_ENDPOINT` | Shared | HTTPS RAM data-plane endpoint. URLs with embedded credentials, a query, or a fragment are rejected. |
| `RAM_STORE_ID` | Shared | Store used by the team. |
| `RAM_NAMESPACE` | Shared | Namespace that scopes every read and write. |
| `RAM_PARTICIPANT` | Per user | Contributor attribution. It is not authenticated identity. |
| `RAM_API_KEY` | Per user when supported | Credential that authenticates RAM requests. |

Store ID, namespace, and participant accept 1–64 letters, digits, or hyphens.
Issue a different API key to each user when the service supports it so access
can be revoked and audited independently. If users share an API key,
`RAM_PARTICIPANT` remains self-asserted metadata; do not treat it as a security
identity. Server-validated OAuth can replace this limitation later without
changing the tool model.

## 3. Install the plugin in ChatGPT desktop

1. Restart ChatGPT desktop after adding the marketplace.
2. Open the Plugins directory.
3. Choose **Redis Field Engineering**.
4. Install **Redis Shared Memory — Editor**.
5. Start a new chat.

Keep normal approval prompts enabled for write tools. `editor_publish` creates
a fact, and `editor_update` replaces an existing fact by exact memory ID.

## 4. Verify one user, then the group

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

## Update

For a marketplace that tracks an approved branch or tag:

```sh
codex plugin marketplace upgrade redis-field-engineering
```

Restart ChatGPT desktop and start a new chat. Installations pinned to a commit
SHA do not move automatically; approve a new SHA and add that ref when a new
release is ready. The desktop app caches installed plugin files, so editing a
checkout alone does not update an already installed copy.

## Remove

Uninstall **Redis Shared Memory — Editor** in the Plugins directory, then remove
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
| `configuration_missing` | Create the file at the exact path above and fill all five settings. |
| Credential file permission or owner error | Confirm the file belongs to the signed-in OS user and run `chmod 600 ~/.config/redis-shared-memory/editor.env`. |
| `authentication_failed` or `access_denied` | Replace or reissue this user's API key and confirm it can access the configured store. |
| `network_error` | Check the HTTPS endpoint, VPN, DNS, proxy, and enterprise allowlist. |
| `dependency_unavailable` | Retry a read once; if it persists, contact the Redis service owner. Do not blindly retry a write. |
| A repository change is not visible | Upgrade the marketplace, restart the app, and start a new chat. |

For marketplace command details, see OpenAI's
[plugin build and installation documentation](https://developers.openai.com/plugins/build/plugins).
