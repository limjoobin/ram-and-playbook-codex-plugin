# Agenda-item output schema

Return these top-level evidence-backed context collections before the ordered
management topics:

- `action_item_summary`: total action items plus counts by lifecycle and owner;
- `action_items`: every current action-item projection, grouped by owner and
  lifecycle order;
- `confirmed_decisions`: current decisions and approvals already finalized;
- `completed_work`: completed or resolved work inside the lookback;
- `open_work_items`: proposed, open, pending, active, or blocked action items.

Each context record contains `state_id`, `state_kind`, `lifecycle_status`,
`subject`, `owner`, `due_at`, `valid_at`, and `evidence_references`. Missing
owners are explicit empty values, not inferred identities. Context records do
not require a new management question or material-impact statement.

For each selected management topic, return the following fields:

- `state_id`: exact current-state identifier.
- `title`: concise topic copied from current state.
- `agenda_purpose`: progress update, unblock, approval, risk/issue/dependency
  review, conflict resolution, or decision review.
- `state_kind` and `lifecycle_status`: controlled RAM values.
- `why_now`: a source-bounded due-date, conflict, or current-status reason.
- `current_state`: a factual, current summary bounded by cited evidence.
- `owner`: accountable person or an explicit empty owner gap.
- `due_at`: recorded due date or an explicit empty value.
- `timebox_minutes`: an integer meeting allocation.
- `confidence`: high, medium, or low, based on evidence completeness and
  agreement.
- `evidence_references`: identifiers for every evidence record supporting a
  material assertion.

`max_items` applies only to `agenda_items`. It must not truncate
`action_items`, `confirmed_decisions`, `completed_work`, or `open_work_items`.
Context evidence references are source links from the current projection.
Agenda-item evidence references must additionally resolve to non-empty source
passages.

Return `registered_conflicts` with every first-pass RAM conflict and its
agenda-level reconciliation status. Return only unresolved or ambiguous entries
under `conflicts`, and place conflicts supported as resolved by later evidence
under `reconciled_conflicts`. Include bounded query counts under
`reconciliation`; none of these fields implies that RAM was mutated.

Order the items by conflict and lifecycle priority, not retrieval score alone.
Keep the total agenda within the requested maximum. Return deferred candidates
and warnings separately from agenda items.
