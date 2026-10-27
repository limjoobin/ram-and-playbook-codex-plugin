# Agenda qualification rules

Agenda qualification rules decide whether an issue deserves management
attention. They are distinct from the agenda-item format, which only defines
how a qualifying issue is presented.

First enumerate current shared RAM projections by project and by every state
kind. A single semantic top-k search is not a complete project-state read. An
optional focus can rank the structured result, but cannot exclude state kinds.

Then classify source-linked shared RAM state into meeting context:

- confirmed decisions: `decision/decided` and `approval/approved`;
- recent completed work: `completed` or `resolved` work inside the lookback;
- open work: `action_item` with `proposed`, `open`, `pending_approval`,
  `in_progress`, or `blocked` lifecycle.

These context records may be reported without a new management question or
material-impact statement. They remain informational unless they separately
meet every qualification rule below.

Retrieve every current action item and every current decision or approval.
Group action items by owner and lifecycle so leaders can see both outstanding
commitments and completed progress. The requested agenda-item maximum does not
truncate either register.

Include a candidate only when current evidence supports all of the following:

1. It is material: it affects a committed outcome, customer obligation,
   cross-team dependency, risk exposure, capacity, cost, or formal approval.
2. It needs a management decision, confirmation, trade-off, or unblock within
   the meeting horizon.
3. It has a named accountable owner or an explicit owner gap that leaders must
   resolve.
4. Its state is current and supported by cited evidence.

Prioritize items with a near decision date, a material change, or a dependency
that crosses accountable teams. Defer routine status, information already
decided, localized work with an empowered owner, and issues that lack a clear
management question.

Do not score urgency from wording alone. A quiet approval, a measured variance,
or a documented dependency can be material; an emphatic but resolved incident
is not.
