# Agenda-item output schema

For each qualifying item, return the following fields:

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

Order the items by management consequence and decision horizon, not retrieval
score alone. Keep the total agenda within the requested maximum. Return
deferred candidates, conflicts, and warnings separately from agenda items.
