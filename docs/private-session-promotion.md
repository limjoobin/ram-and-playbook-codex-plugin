# Private session capture and shared promotion

## Boundary

The plugin has one local Python MCP. It does not introduce a second service or
a second organizational-state reconciler.

The active `UserPromptSubmit` and `SessionEnd` hooks append bounded events to
`RAM_PERSONAL_NAMESPACE`. A hook is a short-lived standard-library process: it
records the event in the private local ledger, queues the exact RAM session
event in the private outbox (`promotion/outbox/` under the plugin data
directory), and returns without loading the SDK or opening a connection. The
long-running MCP server delivers queued events with each event's RAM
idempotency key, records the returned RAM event ID in the ledger, and delivers
any backlog before the promotion tools read provenance. A candidate's private
event IDs are resolved when it is read, so delivery after capture is safe.
`PostToolUse` and `Stop` are intentionally
unregistered for the current reduced-capture experiment. RAM owns session
memory and any configured personal long-term-memory extraction. A local
append-only ledger retains private capture metadata and any earlier review
candidates.

The reduced mode does not create candidates automatically. When a user prompt
looks like a lifecycle report, `UserPromptSubmit` supplies agent context to
retrieve the exact current state and call `memory_state_update_propose`. The
tool accepts the exact captured prompt, verifies the current `state_id` and
lifecycle, and creates a private review candidate. This avoids restoring the
broader `PostToolUse` and `Stop` capture paths.

Nothing captured by a hook is shared. A candidate becomes shared only when the
agent first lists and inspects it, shows the evidence to the user, receives an
explicit confirmation, and calls `memory_candidate_promote` with
`confirmed: true`. A state-update candidate already contains the exact proposed
observation shown during inspection. The model cannot replace that proposal in
the promotion call. Older candidates retain the explicit-observation input for
compatibility.

Promotion creates the reviewed immutable `organizational-state-v3` record
directly in `RAM_NAMESPACE`, under `RAM_AGENDA_OWNER_ID`, with a deterministic
memory ID and private candidate/event references retained as provenance. The
write is read back by exact ID before success is returned. MemoryETL is not
used for this already-structured, human-confirmed update. The private source is
referenced, not moved, updated, or deleted.

The promoted record is also a first-class evidence source. Because it has no
document source traversal, callers use `ram_get_evidence` with its exact
`memory_id` and omit `source_id`. The service returns it only when the record
matches the configured owner, namespace, memory type, schema, and confirmed
candidate provenance. Agenda output can therefore cite the completion report
instead of falling back to the earlier assignment evidence.

Legacy v2 lifecycle observations remain readable during the v3 relation-model
migration and contain no relationship assertion. Explicit generic
relationships remain immutable v3 observation data; lifecycle hooks must not
invent them. The central projector may independently derive a narrow exact
`fulfills` edge from later terminal evidence without mutating either source.

## RAM prerequisites

- The RAM session worker and its model provider must be running.
- The store must enable the intended personal-memory extraction for private
  sessions.
- `RAM_AGENDA_OWNER_ID` must remain the management-state owner lane used by the
  existing projection/reconciliation implementation.
- A confirmed promotion is immediately available through
  `ram_search_state(view="history")`. The shared central projector—not this
  plugin—must process that observation before it appears in `current` or
  `conflicts`. This preserves one reconciliation implementation.

## Identity and isolation

The shared endpoint, store, namespace, management owner, and Playbook are group
configuration. `RAM_PARTICIPANT`, `RAM_PERSONAL_NAMESPACE`, and preferably both
API keys are per-user. Participant is attribution, not authenticated identity;
server-side API-key policy remains the authorization boundary.

Candidate IDs include participant, source session, turn, and subject. The
shared observation ID is derived from that candidate ID. A retry therefore
returns the prior exact observation instead of creating duplicate state; a
different record at that ID fails closed.

## Hook trust

Plugin hooks execute local code as the signed-in operating-system user. Codex
does not run non-managed plugin hooks until the user reviews/trusts them. Review
`hooks/hooks.json` and `hooks/capture.py` before enabling them. The SessionEnd
transcript path is treated as unstable and untrusted: only its digest is kept;
the transcript is never opened or executed.

OpenAI documents plugin hook discovery in the
[plugin build guide](https://developers.openai.com/plugins/build/plugins) and
the event contracts and trust flow in the
[hooks documentation](https://learn.chatgpt.com/docs/hooks).

## Manual acceptance for reduced capture

1. Send a non-sensitive prompt and end the session. Verify RAM receives one
   user event and one end marker only in the personal namespace.
2. Verify no tool output or assistant response was captured and no new
   promotion candidate was created.
3. Verify shared organizational state is unchanged.
4. Report completion of one known current action with an explicit completion
   time and request publication. Verify the hook tells the agent not merely to
   acknowledge the report and instead suggests `memory_state_update_propose`.
   Verify the proposal retains the exact private statement, existing
   `state_id`, capture time, and explicit `resolved_at`, while current shared
   state remains unchanged.
5. Inspect and explicitly confirm the candidate, then promote it. Verify one
   shared immutable observation exists, its candidate provenance is retained,
   and the private record remains intact.
6. Read the promoted observation through `ram_get_evidence` using its exact
   memory ID and no source ID. Verify its lifecycle, owner, and resolution time
   match the confirmed update.
7. Include a token-shaped value and a malicious transcript-path string in a
   test session. Verify neither appears in the local ledger or MCP output.
