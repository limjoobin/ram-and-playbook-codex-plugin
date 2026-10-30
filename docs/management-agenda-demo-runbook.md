# Management agenda demo runbook

## Goal

Demonstrate one shared Redis Agent Memory and Redis Agent Playbook surface in
ChatGPT or Codex:

1. retrieve source-grounded organizational state;
2. identify one employee's current actions;
3. publish a human-confirmed completion through the private-candidate flow;
4. let the central projector reconcile the current state; and
5. prepare a Playbook-governed management-review agenda with traversable
   evidence.

The demo proves a quality and workflow claim, not production scale. Context
Retriever is not deployed or evaluated.

## Story and evidence boundary

Real Reaction is a fictional four-person team designing a remote control. The
source corpus follows four AMI ES2002 meetings from product brief to final
design. The final product is a colourful snowman-shaped remote with physical
buttons, a scroll wheel, conventional batteries, and a production cost of
12.40 euros.

The shared state was extracted from 15 text-only AMI artifacts: four
transcripts, four minutes documents, a final report, an agenda, and five
presentations. The artifacts are all dated 13 December 2004. Human-confirmed
updates created during this demo have current timestamps and are additional
observations, not claims that the historical project happened in 2026.

Keep three layers distinct when presenting results:

- **Evidence:** immutable source-linked observations and confirmed human
  reports.
- **Current view:** deterministic `organizational_state_projection` records.
- **Agenda:** a Playbook-governed, human-editable view over current state.

The plugin installation does not seed or reset RAM or publish Playbook content.
An administrator must hydrate the shared environment before the demo.

## Preflight

Use a fresh chat after installing or updating the plugin. Confirm that the
installed plugin and the central scheduler are pinned to the same reviewed Git
commit.

Ask:

> Check the Redis Shared Memory connection status.

Expected:

- plugin version `0.12.6` or the currently approved successor;
- RAM and Playbook both available;
- namespace `sboai-test` for the prepared PoC environment;
- role `editor`; and
- the intended participant, such as `andrew`.

Stop if RAM or Playbook is unavailable, the namespace is unexpected, or the
participant does not match the employee being demonstrated.

As a behavioral sanity check, confirm that the current view and immutable
history are both readable, document evidence can be traversed, and terminal or
superseded observations are not presented as current. Do not use exact
projection counts as an acceptance gate; they change when extraction,
relationships, policy, or confirmed human updates change.

## Demo 1 — Source-grounded project recall

Ask:

> What discussions and decisions were made around the colour of the Real
> Reaction remote-control design? Distinguish settled design choices from
> unresolved validation.

Expected answer:

- the team was initially unsure of the official corporate colour;
- yellow was inferred from the website and selected as the predominant design
  colour;
- the final report specifies yellow, blue, and red plastic; and
- official corporate-colour verification, palette flexibility, and market
  acceptance should remain caveats.

This is a useful contrast between a settled product choice and an unresolved
premise. Do not claim that selecting yellow proves the corporate-colour
specification was formally verified.

## Demo 2 — Employee action view

With `RAM_PARTICIPANT=andrew`, ask:

> What are my current action items? Separate open, in-progress, and completed
> work, and include evidence references.

The agent should resolve Andrew to
`employee-andrew-marketing-expert`, call `ram_search_state`, and avoid a broad
unfiltered semantic search.

For the current snapshot, Andrew's projected state includes:

- in progress: conduct the design evaluation;
- open: determine the remote-control requirements; and
- completed: trend watching, submission of evaluation criteria, and writing
  the evaluation results on the board.

The exact set will change as the demo records more confirmed completions.

## Demo 3 — Private capture and confirmed promotion

Choose one action that is still open in the current projection. Do not reuse an
already completed action. Say, for example:

> I completed the remote-control requirements artifact. Please publish this
> update to the Real Reaction shared memory, but show me the exact update first.

Expected flow:

1. `UserPromptSubmit` privately records the exact statement.
2. The agent retrieves one exact current action.
3. `memory_state_update_propose` creates a private candidate; shared state is
   unchanged.
4. `memory_candidate_inspect` shows the action, owner, old and new lifecycle,
   project, and completion time.
5. The human explicitly confirms.
6. `memory_candidate_promote` writes and reads back one deterministic,
   immutable shared observation.
7. The central scheduler runs the canonical projector. Current state changes
   on that reconciliation pass.

The `SessionEnd` hook records a private session-end marker. It does not infer a
completion or publish shared state by itself.

If history shows the completion while current state remains open, wait for the
five-minute scheduler or have the administrator run the central reconciliation
command. Do not promote the same candidate again.

Verify the confirmed observation with `ram_get_evidence` using its exact
`memory_id` and no `source_id`. It should expose the lifecycle, owner,
resolution time, and private-candidate locator. This is the citable completion
report; document-derived evidence continues to use both `memory_id` and
`source_id`.

## Demo 4 — Management agenda

Ask:

> Prepare an evidence-backed management review agenda for the Real Reaction
> project for 15 November 2026. Use at most eight management topics. Keep the
> action register, completed work, confirmed decisions, conflicts, and agenda
> topics separate.

Allow roughly two minutes for the current PoC. Call `agenda_prepare` once and
wait for it. Its `max_items` contract accepts 1 through 20; do not pass 100.

Expected:

- the exact Playbook Skill version and resource digests are attested;
- all current state kinds are retrieved with project, owner, memory-type, and
  schema filters;
- completed human updates cite their direct RAM observation first;
- document-derived entries retain source evidence references;
- registered conflicts are separated into reconciled and unresolved groups;
  and
- the management-topic draft contains no more than eight items, while the
  context registers remain complete.

## How to present the agenda accurately

Use these labels:

- **“Action projections”**, not “unquestionably current tasks.”
- Separate active and completed actions and include the applicable data-quality
  caveat.
- **“Decision projections”**, not “unique current decisions.”
- **“Historical project-process observations”** for collaboration and meeting
  problems recorded during the final retrospective.

The action projection is intentionally conservative. Several nominally open
actions have later artifacts that suggest the work happened, including
functional requirements, interface and technical-function concepts, trend
research, meeting minutes, the product evaluation, and the final design. Until
an explicit relation or human-confirmed completion reconciles them, describe
these as **open in RAM, with possible later fulfilment evidence**, not as known
unfinished work.

Similarly, the decision projections contain duplicate formulations and
historical choices. Kinetic power with battery backup, plastic and rubber
materials, and earlier interface concepts should be presented as decision
history when later evidence replaces them. The final report is authoritative
for the final batteries-only, plastic, no-LCD design.

The selling-price basis is a legitimate unresolved conflict: the transcript
asks whether 25 euros is wholesale or retail and never records a firm answer.
The slogan-treatment conflict is reasonably resolved by the final report. The
corporate-colour scheme and specification should remain caveated: later
evidence confirms a yellow-led product, but not necessarily formal
verification of the company's official colour policy.

## Expected close-out

End the demo with three observations:

1. RAM retains source-grounded organizational history and a deterministic
   current view.
2. A person can safely add a completion through private capture, review, and
   explicit promotion; the next agenda cites that report directly.
3. Playbook governs the agenda workflow, but the output remains a draft for a
   human to trim and correct where the organizational state is conservative or
   ambiguous.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Plugin still shows an older version | Refresh the installed plugin, restart ChatGPT desktop, and use a fresh chat. |
| Hook does not run | Verify the installed plugin exposes active `UserPromptSubmit` and `SessionEnd` hooks and that they are trusted. An `@` mention alone does not enable hooks. |
| Completion is visible in history but not current state | Wait for the central scheduler or run the administrator reconciliation command once. Do not promote again. |
| Agenda call rejects the request immediately | Keep `max_items` between 1 and 20. |
| Agenda takes a long time | Wait for the single call; avoid launching compensating broad searches unless the call actually fails. |
| Agenda reports stale open work | Present it as projection state and inspect later artifacts or request an explicit human completion. Do not silently rewrite RAM in the answer layer. |
| RAM or Playbook is unavailable | Stop the demo and check credentials, service availability, and whether the prepared store was reset or flushed. |

## Post-demo record

Record the plugin version, Git commit, participant, namespace, Playbook
version, promoted candidate and observation IDs, scheduler result, and any
agenda caveats. Do not record credentials, raw private prompts beyond the
approved demo statement, or unnecessary document content.
