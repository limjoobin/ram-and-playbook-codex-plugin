---
name: prepare-management-review-agenda
description: Prepare a decision-focused management review agenda from current, cited evidence.
license: Synthetic PoC
compatibility: Requires the linked management-agenda resources and cited RAM evidence.
metadata:
  owner: management-operations
---

# Prepare a management review agenda

Use the linked materials as the sole business-policy source for this task:

- [Meeting charter and audience](references/meeting-charter.md)
- [Agenda qualification rules](references/agenda-qualification-rules.md)
- [Agenda-item output schema](references/agenda-item-output-schema.md)
- [Evidence lifecycle and conflicts](references/evidence-lifecycle.md)
- [Abstention and escalation](references/abstention-and-escalation.md)

Search the shared Redis Agent Memory current-state layer before preparing the
agenda. Do not use private personal memory as organizational truth. Enumerate
current projections with separate structured `project_id` plus `state_kind`
searches for `action_item`, `decision`, `approval`, `risk`, `issue`,
`dependency`, and `conflict`. Do not rely on one broad semantic top-k search;
an optional focus may rank the complete structured result but must not define
its scope. Report a retrieval-bound warning rather than silently treating a
capped result as complete.

Retrieve the RAM vocabulary explicitly:

- `decision/decided` and `approval/approved` as confirmed decisions;
- recent `action_item/completed` and resolved work as progress;
- `action_item` records in `proposed`, `open`, `pending_approval`,
  `in_progress`, or `blocked` as open work; and
- current `risk`, `issue`, `dependency`, `approval`, `decision`, or
  `action_item` records as candidates for management qualification.

Return every current action item in a compact owner-grouped register, then
separate its open and recently completed subsets. Return every current
confirmed decision and approval; the agenda-item maximum applies only to
decision-ready items, never to these context registers.

Apply the lifecycle rules first, then the qualification rules. Source-link the
context registers, but open and verify the evidence passages only for material
assertions selected into the agenda. Confirmed decisions, completed work, and
open work provide meeting context; they do not automatically become
management-decision items. Do not turn a routine update into a management item.
Emit only the output fields in the schema, cite every material assertion, and
use the abstention rules whenever the available evidence cannot support a
decision-ready item.
