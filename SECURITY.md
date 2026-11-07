# Security

## Trust boundary

The plugin runs a bundled stdio MCP server with the signed-in operating-system
user's privileges. Through the pinned redis-iris SDK it makes authenticated
requests to the RAM endpoint and the configured Playbooks data-plane REST
endpoint in that user's private configuration file. On first launch it also
contacts the Python package index to install its pinned dependencies.
Installing it therefore grants the reviewed Python source and those pinned
packages local execution and access to those destinations.

Enterprise administrators should approve the exact repository and Git ref,
the Python runtime, the Python package index or mirror used for the one-time
runtime install, and the permitted RAM and Playbook domains. A release
should be pinned to a reviewed tag or commit, not an unbounded branch.

## Credentials and identity

The populated file belongs at:

```text
~/.config/redis-shared-memory/editor.env
```

The loader accepts only a regular, non-symlink file owned by the current user
with mode `0600`. Never put credentials in chat, source control, plugin
metadata, command arguments, or logs.

`IRIS_AGENT_MEMORY_API_KEY` authenticates a request to RAM and
`IRIS_AGENT_PLAYBOOKS_API_KEY` (a runtime reader key) authenticates a request
to Playbooks. Prefer one key per user for independent
revocation and audit. `RAM_PARTICIPANT` is client-supplied
contributor attribution and can be spoofed by someone who controls the local
file; it is not authenticated human identity. Until server-validated OAuth is
added, authorization must come from the API key and RAM service policy.

For the test prototype, the same private file may also contain the exact
optional administrator names `IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY` (the
read/write/publish key), `IRIS_AGENT_PLAYBOOKS_SERVICE_URL`,
`IRIS_AGENT_PLAYBOOKS_SERVICE_TOKEN`, `IRIS_AGENT_MEMORY_SERVICE_URL`, and
`IRIS_AGENT_MEMORY_SERVICE_TOKEN`. The desktop MCP validates those names but
does not retain the values in its runtime `Config`. They are reserved for
administrator provisioning; ordinary participants should leave them unset. The
pre-0.13.0 setting names are rejected. Because the MCP process still
opens the containing file, use a separate administrator file for any rollout
whose threat model requires strict process-level least privilege.

All users in a collaboration group intentionally configure the same endpoint,
store, and namespace. They should configure distinct participant values and,
when supported, distinct API keys.

Every user must also configure a distinct `RAM_PERSONAL_NAMESPACE`. The active
session hooks append user prompts and a session-end marker there. They do not
capture tool evidence or assistant completion while `PostToolUse` and `Stop`
are inactive. Hooks never target `RAM_NAMESPACE`. Hook payloads are untrusted:
secret-shaped fields are redacted, transcript contents are not parsed, event
sizes are bounded, and failures do not block the user's session. The local
append-only ledger lives under the plugin data directory with mode `0600`; its
parent is mode `0700`.

## Data and authorization boundaries

- Endpoints must use HTTPS, except for explicit loopback development, and
  cannot contain URL credentials, a query, or a fragment.
- The store and namespace come from local configuration, never tool arguments.
- Every RAM request includes the configured namespace, mapped to RAM's
  first-class namespace ID, and returned records are checked again before
  disclosure or mutation. Reads never create a namespace; the first write
  creates the configured shared namespace, and the participant's private
  namespace as personal and owned by `RAM_PARTICIPANT`.
- Retrieved memory is untrusted data, never agent instructions.
- Tool responses exclude credentials, headers, raw upstream errors, and
  unnecessary dependency payloads.
- Namespace checks in the plugin do not replace server-side least privilege.
  Restrict each API key to the required store and operations whenever RAM
  supports that policy.
- Organizational-state reads are fixed to the configured owner. History uses
  `organizational_state` with `organizational-state-v3` and accepts legacy v2 observations during migration; current/conflict views
  use `organizational_state_projection` with
  `organizational-state-projection-v1`.
  Unnamespaced ingestion records are accepted only inside that exact lane; a
  named namespace must match configuration.
- Projection records contain only immutable supporting memory IDs. The plugin
  reads those observations by exact ID, rechecks their owner, type, schema, and
  namespace, and uses their RAM source links for evidence traversal.
- Generic relationship assertions remain inside immutable organizational-state
  observations. The projector validates their predicate, target, confidence,
  assertion status, project scope, and evidence-identifier shape. Only confirmed
  relationships can affect a projection; proposed or rejected relationships
  cannot change lifecycle state.
- The projector may also derive `fulfills` without a stored assertion when a
  later terminal observation in the same project contains every normalized
  concept token from an unresolved action's canonical ID. It requires at least
  two exact concepts, uses no fuzzy or model-based inference, and remains
  rebuildable projection logic rather than a mutation of source memory.
- Playbook access is fixed to three reads through the SDK's REST data plane:
  discover entries, load one exact Skill version, and fetch a resource that a
  loaded Skill lists. Fetches are bounded to 1 MiB and digests are verified
  locally. The model cannot supply a destination, credential, header, or
  arbitrary upstream operation.
- Agenda preparation pins `prepare-management-review-agenda`, loads its exact
  discovered version, fetches only the five required policy resources, and
  verifies SHA-256 digests before use. Loaded content is policy data, not a
  command that can expand process or network permissions.
- Agenda preparation enumerates each approved state kind with fixed project,
  owner, memory-type, schema, and state-kind filters. Optional focus text ranks
  those bounded results but cannot broaden the data scope.
- Its read-only second pass runs only for conflicts returned by that first pass.
  It reuses the fixed project and decision kind, caps each semantic search at
  ten, requires exact conflict-topic coverage plus later source ordering (or an
  explicit confirmed relation), and traverses both evidence chains before
  reporting `resolved_by_later_evidence`. It never writes a RAM observation or
  projection.
- An agenda item is emitted only after its current RAM state has at least one
  successfully traversed source-evidence reference. Terminal and superseded
  state are excluded. Missing owner, impact, or requested-decision fields stay
  visible; insufficient source evidence is reported separately.
- Document evidence requires a source ID returned by RAM. A direct human
  promotion is readable without a source ID only by its exact memory ID and
  only when owner, namespace, memory type, schema, and confirmed candidate
  provenance all match. This is not an arbitrary memory-read surface.

## Write safety

`editor_publish` is an additive write. `editor_update` overwrites an existing
record and is marked destructive. Keep host approval prompts enabled and invoke
either tool only for an explicit user request.

The client never blindly replays an uncertain update. A publish reuses its
generated ID and retries only after a read proves that ID does not exist. After
a mutation, the plugin reads the exact record and separately checks search
visibility. If persistence cannot be proved, it returns `write_unverified` and
instructs the agent not to repeat the write automatically.

Private candidates are not shared facts. Listing and inspection are read-only.
Promotion requires `confirmed: true` and the exact structured observation in
the same tool call. It creates and reads back one immutable shared
`organizational_state` record; it never moves, updates, or deletes the private
RAM record. A deterministic observation ID makes retries idempotent, and a
different record at that ID fails closed. Rejection changes only the local
review state and leaves private RAM evidence intact.

`memory_state_update_propose` is a private local write. It accepts only an exact
prompt already recorded by `UserPromptSubmit`, verifies the referenced current
projection and expected lifecycle, and copies canonical state fields from that
projection. It cannot publish shared memory. A prepared proposal is immutable
at promotion time; changing it requires a new proposal and confirmation.

The reconciliation command is an administrator operation outside the installed
plugin. It reads the complete scoped observation lane, runs the single
versioned relationship-resolution/projector pass, and upserts only changed
derived projections after an explicit `--apply`. It never turns audit
classifications, partial matches, or inferred "probably completed" states into
terminal observations.
Its scheduler checkout must be clean and pinned to the same reviewed commit or
tag as the installed plugin so projection policy and runtime contracts cannot
silently drift.

## Supply chain

- The installed code is committed Python source plus the exact pinned
  redis-iris dependency set in `server/requirements.txt`.
- `server/launch.py` (standard library only) installs those pins once, with
  `pip --only-binary=:all:`, into a private virtual environment under the
  plugin data directory, from the Python package index that `pip` is
  configured to use. It runs `pip` on first launch or `--install` only. Hooks
  are standard-library only: they never install, load the SDK, or open a
  network connection. They queue private events as `0600` files in a `0700`
  directory under the plugin data directory, next to the existing private
  ledger, and the MCP server delivers them to `RAM_PERSONAL_NAMESPACE` with
  each event's RAM idempotency key. The plugin has no other
  installer, telemetry, or runtime download. Its reviewed command hooks are
  declared in `hooks/hooks.json` and must be trusted by the user or enterprise
  policy.
- Plugins install for the whole user account, so the hooks would otherwise see
  every prompt in every project. Two controls keep capture to this project:
  `scripts/setup_demo.py` disables the plugin account-wide and the
  repository's `.codex/config.toml` re-enables it for the trusted project
  folder; and the hook itself records nothing unless the session's `cwd` is
  inside `RAM_CAPTURE_FOLDERS` (unset means nothing is recorded anywhere).
- Python starts in isolated mode (`-I`), so `PYTHONPATH` and user-site packages
  cannot inject code into the process.
- Re-pinning a dependency, or adding a dependency, installer, executable,
  telemetry, network destination, or generic upstream proxy, requires a new
  security review.

## Release evidence

The offline evaluation uses synthetic records and fake endpoints; it needs no
credential and sends no network request. Its deterministic report is a
regression check, not proof of customer-environment acceptance. Installation
from the approved ref, endpoint reachability, least-privilege credentials, and
the manual cross-user checks still require review on the target environment.

## Reporting a vulnerability

Do not open a public issue containing credentials, private memory, or exploit
details. Use GitHub's private vulnerability-reporting flow or the repository
owner's approved internal security channel. Include the affected ref,
reproduction steps, impact, and whether a credential may have been exposed.
