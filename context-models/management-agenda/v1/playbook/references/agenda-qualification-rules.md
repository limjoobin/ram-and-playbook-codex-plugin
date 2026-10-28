# Agenda qualification rules

Agenda selection rules decide which current topics should appear first in a
human-editable management draft. They are distinct from the agenda-item format,
which only defines how a selected topic is presented.

First enumerate current shared RAM projections by project and by every state
kind. A single semantic top-k search is not a complete project-state read. An
optional focus can rank the structured result, but cannot exclude state kinds.

Then classify source-linked shared RAM state into meeting context:

- confirmed decisions: `decision/decided` and `approval/approved`;
- recent completed work: `completed` or `resolved` work inside the lookback;
- open work: `action_item` with `proposed`, `open`, `pending_approval`,
  `in_progress`, or `blocked` lifecycle.

These context records may be reported without a new management question,
material-impact statement, or owner.

Retrieve every current action item and every current decision or approval.
Group action items by owner and lifecycle so leaders can see both outstanding
commitments and completed progress. The requested agenda-item maximum does not
truncate either register.

First-pass candidates are non-terminal current states with source links. Do not
reject a candidate merely because `requested_decision`, `impact`, `due_at`, or
`accountable_entity_id` is empty. Those gaps remain visible for human review.

Before ordering the draft, run a bounded second pass over first-pass conflicts:

1. Search the same project for later confirmed decisions relevant to each
   conflict topic. Reuse one query for duplicate topic terms and cap each query.
2. Prefer an explicit confirmed `resolves` or `supersedes` relation.
3. Otherwise accept a later `decided`, `approved`, `completed`, or `resolved`
   state only when its source-grounded text covers the conflict's specific topic.
4. Verify traversable evidence for both the conflict and the later state.
5. Label the agenda view `resolved_by_later_evidence`, `unresolved`, or
   `ambiguous`. Do not mutate the RAM projection from this read path.

Prioritize unresolved conflicts, blocked work, pending approvals, risks, issues,
dependencies, proposed decisions, and then ordinary open action updates. Apply
`max_items` after ordering. Return lower-ranked source-backed states as deferred
for agenda capacity so the human chair can restore or combine them.

Do not score urgency from wording alone. A quiet approval, a measured variance,
or a documented dependency can matter; an emphatic but reconciled conflict is
not current merely because RAM still registers the older conflict projection.
