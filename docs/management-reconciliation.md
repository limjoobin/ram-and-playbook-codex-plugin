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

The reconciliation code ships inside the plugin
(`server/ram_plugin/reconcile.py`, with byte-identical copies of `projector.py`
and `projection-policy.json` that a test keeps in step with
`context-models/management-agenda/v1`). The plugin runs it right after every
confirmed promotion, so the published change reaches the current view at once.
The same code is also exposed as one administrator job. Run it from the
development environment that has the pinned redis-iris SDK installed (see
`AGENTS.md`):

```sh
.venv/bin/python scripts/reconcile_management_state.py
```

Without `--apply`, the command reads all scoped observations and projections
and reports how many projections would change, and how many earlier management
records have no namespace. It does not write. With `--apply` it first moves
those records into `RAM_NAMESPACE` (they predate the shared-namespace scope and
are otherwise invisible), then writes the changed projections. Only records
owned by `RAM_AGENDA_OWNER_ID`, the single owner earlier versions used, are
moved; other unnamespaced records in the store are left alone.

Run it by hand only when a promotion reports `projection_status:
pending_reconciliation`, for example because the new observation was not yet
searchable. To wait for one promoted candidate:

```sh
.venv/bin/python scripts/reconcile_management_state.py \
  --apply \
  --wait-for-candidate candidate-0123456789abcdef0123456789abcdef0123456789abcdef \
  --timeout-seconds 420
```

The candidate ID is returned by `memory_state_update_propose` and
`memory_candidate_promote`. The job checks for that source, then runs the
canonical projector and writes changed projections by deterministic ID: new
ones with a create that never overwrites, changed ones with a replace that
names the revision it read and keeps the record's existing owner. If another
participant wrote in between (409 or 412), or a stored projection already cites
an observation this run cannot see yet, the job waits briefly, reads
everything again, and retries, up to three passes.
`awaiting_observation` means the source is not visible; inspect the confirmed
promotion instead of blindly publishing it again.

## Production trigger

Human-confirmed promotions rebuild the current view inside the plugin, so no
scheduler is needed for them. Document ingestion is the remaining trigger:
RAM's current ingestion webhook is a blocking decision hook before generated
memories are applied, not a completion notification. `scripts/setup_demo.py`
therefore rebuilds the current view after it loads documents, and an
administrator who ingests documents another way runs:

```sh
.venv/bin/python scripts/reconcile_management_state.py --apply
```

A future supported MemoryETL completion event can call the same code. The two
active hooks remain `UserPromptSubmit` and `SessionEnd`; no additional Codex
lifecycle hook is required.

## Safety and idempotency

- Store, namespace, and credentials come only from the private editor
  configuration.
- Every management record lives in `RAM_NAMESPACE`. A record is in scope when
  its namespace, memory type, and schema match; its `ownerId` is its author
  (the participant who loaded the document, published the update, or rebuilt
  the projection) and is not part of the scope. Unnamespaced records are out
  of scope until `--apply` moves them.
- A rebuild by a different participant does not rewrite an otherwise
  unchanged projection.
- v3 and legacy v2 observations are read together during migration; new
  relationship assertions require the v3 custom-memory field contract.
- Pagination is exhausted before projection.
- Stable projection IDs make repeated runs idempotent.
- Automatic fulfilment requires a later terminal source, the same project,
  and exact concept coverage; it cannot act on topical similarity.
- Policy-derived links are explicit, versioned, source-grounded, chronological,
  and applied by the same projector; no fuzzy resolver or second job is involved.
- Only changed projections are written, replacements are conditional on the
  revision that was read, and every write is read back.
- A missing promoted observation returns `awaiting_observation` without
  changing current state.
- This first job does not retire obsolete projections during a policy upgrade;
  upgrades continue to use the reviewed bootstrap migration path.
