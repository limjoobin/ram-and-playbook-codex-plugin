# Management-state reconciliation

## Contract

Organizational observations are immutable. Current state is a rebuildable
`organizational_state_projection` produced by the versioned projector and
`ami-es2002-state-families-v3` policy. Reconciliation never treats the
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

The same projector performs one deliberately narrow automatic resolution: it
may derive `fulfills` from a later terminal observation to an unresolved action
only when it contains every normalized concept token from the action's
canonical state ID and the action has at least two such tokens. This is exact deterministic
coverage, not fuzzy similarity or a model judgement. It needs no per-edge
human confirmation, is rebuilt on every run, and is not written back into
immutable observations. Legacy explicit `supersedes_state_ids` values are
honored in the same pass. Ambiguous and partial matches remain open.

The repository exposes one administrator job:

```sh
python3 scripts/reconcile_management_state.py
```

Without `--apply`, the command reads all scoped observations and projections
and reports how many projections would change. It does not write.

After an explicitly confirmed candidate is promoted and RAM MemoryETL has
extracted its shared observation, run:

```sh
python3 scripts/reconcile_management_state.py \
  --apply \
  --wait-for-candidate candidate-0123456789abcdef0123456789abcdef0123456789abcdef \
  --timeout-seconds 420
```

The candidate ID is returned by `memory_state_update_propose` and
`memory_candidate_promote`. The job polls only for that extracted source, then
runs the canonical projector and upserts changed projections by deterministic
ID. `awaiting_extraction` means no write occurred; do not promote the candidate
again.

## Production trigger

For the current PoC, this is an explicit administrator command. A production
deployment should invoke the same job from the RAM MemoryETL output-completion
webhook or its queue consumer. It must run centrally, not independently in
every user's desktop plugin. That avoids concurrent per-client projection
writers and keeps one reconciliation implementation.

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
- Only changed projections are written and every write is read back.
- Missing promoted extraction returns `awaiting_extraction` without changing
  current state.
- This first job does not retire obsolete projections during a policy upgrade;
  upgrades continue to use the reviewed bootstrap migration path.
