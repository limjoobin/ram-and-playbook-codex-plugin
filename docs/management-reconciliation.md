# Management-state reconciliation

## Contract

Organizational observations are immutable. Current state is a rebuildable
`organizational_state_projection` produced by the versioned projector and
`ami-es2002-state-families-v4` policy. Reconciliation never treats the
read-only action audit as an ingestion source and never closes a
"probably completed" action without a new explicit observation.

The v3 observation contract carries optional generic relationships under
`relations.edges`. Every edge points from its observation's `state_id` to one
canonical `target_state_id`. The supported predicates are `fulfills`,
`resolves`, `supersedes`, `blocks`, `depends_on`, `conflicts_with`, and
`supports`. Only `assertion_status: confirmed` is actionable. Proposed and
rejected edges remain visible audit data.

The policy maps confirmed `fulfills` to a completed action, confirmed
`resolves` to a resolved risk, issue, or conflict, and confirmed `supersedes`
to a superseded target. The other predicates add relation evidence without
changing lifecycle status. A relationship older than the target's current
frontier cannot close or supersede a later state.

The same projector performs two deliberately narrow automatic resolutions. It
may derive `fulfills` from a later terminal observation to an unresolved action
only when it contains every normalized concept token from the action's
canonical state ID and the action has at least two such tokens. This is exact deterministic
coverage, not fuzzy similarity or a model judgement. It needs no per-edge
human confirmation, is rebuilt on every run, and is not written back into
immutable observations. The context policy can also declare reviewed source-family,
predicate, and target-family triples for relationships that exact token matching
cannot express. Those links still require a later terminal source before their
lifecycle effect is applied. The current AMI policy uses this for final-artifact
fulfilments, later decisions that resolve issues or dependencies, and decisions
that supersede obsolete state. Legacy explicit `supersedes_state_ids` values are
honored in the same pass. Ambiguous and partial matches remain open.

The repository exposes one administrator job. Run it from the development
environment that has the pinned redis-iris SDK installed (see `AGENTS.md`):

```sh
.venv/bin/python scripts/reconcile_management_state.py
```

Without `--apply`, the command reads all scoped observations and projections
and reports how many projections would change. It does not write.

After an explicitly confirmed candidate is promoted and its direct shared
observation has been verified, run:

```sh
.venv/bin/python scripts/reconcile_management_state.py \
  --apply \
  --wait-for-candidate candidate-0123456789abcdef0123456789abcdef0123456789abcdef \
  --timeout-seconds 420
```

The candidate ID is returned by `memory_state_update_propose` and
`memory_candidate_promote`. The job checks for that source, then runs the
canonical projector and upserts changed projections by deterministic ID.
`awaiting_observation` means the source is not visible; inspect the confirmed
promotion instead of blindly publishing it again.

## Production trigger

RAM's current ingestion webhook is a blocking decision hook before generated
memories are applied, not a completion notification. The PoC therefore runs
the same idempotent administrator command from one central scheduler every five
minutes:

```sh
.venv/bin/python scripts/reconcile_management_state.py --apply --quiet-no-changes
```

On macOS, install this command as one user LaunchAgent with `RunAtLoad` enabled
and `StartInterval` set to `300`. Do not install it through every user's desktop
plugin. A future supported MemoryETL completion event can replace the scheduler
without changing the reconciliation implementation.
Human-confirmed promotions do not wait for MemoryETL; they are picked up by the
same next scheduled run.

Run the scheduler from a clean checkout detached at the same reviewed commit
or tag used to install the desktop plugin. Do not leave the scheduler on an
older branch checkout. For an approved commit SHA:

```sh
git -C "/path/to/central/ram-and-playbook-codex-plugin" fetch origin <approved-sha>
git -C "/path/to/central/ram-and-playbook-codex-plugin" switch --detach <approved-sha>
test "$(git -C "/path/to/central/ram-and-playbook-codex-plugin" rev-parse HEAD)" = "<approved-sha>"
```

After switching, kick the LaunchAgent once and confirm its last exit status is
zero before relying on the five-minute schedule.

The plugin therefore performs the human interaction and confirmed shared
promotion, while this job owns deterministic relationship resolution and
projection. The two active hooks
remain `UserPromptSubmit` and `SessionEnd`; no additional Codex lifecycle hook
is required.

## Safety and idempotency

- Store, namespace, management owner, and credentials come only from the
  private editor configuration.
- Both named records in the configured namespace and legacy unnamespaced
  management records must match the exact owner, memory type, and schema.
- v3 and legacy v2 observations are read together during migration; new
  relationship assertions require the v3 custom-memory field contract.
- Pagination is exhausted before projection.
- Stable projection IDs make repeated runs idempotent.
- Automatic fulfilment requires a later terminal source, the same project,
  and exact concept coverage; it cannot act on topical similarity.
- Policy-derived links are explicit, versioned, source-grounded, chronological,
  and applied by the same projector; no fuzzy resolver or second job is involved.
- Only changed projections are written and every write is read back.
- A missing promoted observation returns `awaiting_observation` without
  changing current state.
- This first job does not retire obsolete projections during a policy upgrade;
  upgrades continue to use the reviewed bootstrap migration path.
