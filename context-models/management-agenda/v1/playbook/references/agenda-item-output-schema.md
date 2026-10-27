# Agenda-item output schema

Return these top-level evidence-backed context collections before the
decision-ready agenda items:

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

For each qualifying management-decision item, return the following fields:

- `title`: concise decision-oriented topic.
- `management_question`: the decision, confirmation, or unblock requested.
- `why_now`: the time-bound reason management should consider it now.
- `current_state`: a factual, current summary bounded by cited evidence.
- `owner`: accountable person or an explicit owner gap.
- `requested_decision`: precise action requested from management.
- `timebox_minutes`: an integer meeting allocation proportional to the decision.
- `confidence`: high, medium, or low, based on evidence completeness and
  agreement.
- `evidence_references`: identifiers for every evidence record supporting a
  material assertion.

`max_items` applies only to `agenda_items`. It must not truncate
`action_items`, `confirmed_decisions`, `completed_work`, or `open_work_items`.
Context evidence references are source links from the current projection.
Agenda-item evidence references must additionally resolve to non-empty source
passages.

Order the items by management consequence and decision horizon, not retrieval
score alone. Keep the total agenda within the requested maximum. Return
deferred candidates, conflicts, and warnings separately from agenda items.
