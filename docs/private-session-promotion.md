# Private session capture and shared promotion

## Boundary

The plugin has one local Python MCP. It does not introduce a second service or
a second organizational-state reconciler.

The active `UserPromptSubmit` and `SessionEnd` hooks append bounded events to
`RAM_PERSONAL_NAMESPACE`. `PostToolUse` and `Stop` are intentionally
unregistered for the current reduced-capture experiment. RAM owns session
memory and any configured personal long-term-memory extraction. A local
append-only ledger retains private capture metadata and any earlier review
candidates.

Because candidate creation previously ran from `Stop`, this reduced mode does
not create new promotion candidates. The MCP candidate tools remain available
for candidates captured before the two hooks were deactivated. Restoring
automatic candidate creation requires an explicit design decision about what
evidence the plugin should retain.

Nothing captured by a hook is shared. A candidate becomes shared only when the
agent first lists and inspects it, shows the evidence to the user, receives an
explicit confirmation, and calls `memory_candidate_promote` with
`confirmed: true` and a complete observation.

Promotion appends a new session in `RAM_NAMESPACE`: an owner-lane bootstrap
event followed by the participant's confirmed JSON envelope. The envelope uses
`personal-to-shared-promotion-v1` and emits the immutable
`organizational-state-v2` fields. RAM's existing custom extractor then creates
the source-linked shared `organizational_state` memory asynchronously. The
private source is referenced, not moved, updated, or deleted.

## RAM prerequisites

- The RAM session worker and its model provider must be running.
- The store must enable the intended personal-memory extraction for private
  sessions.
- The `organizational_state` custom extractor must accept the confirmed
  `personal-to-shared-promotion-v1` envelope and copy its observation exactly.
- `RAM_AGENDA_OWNER_ID` must remain the management-state owner lane used by the
  existing projection/reconciliation implementation.
- Session extraction first makes the observation available through
  `ram_search_state(view="history")`. The shared central projector—not this
  plugin—must process that observation before it appears in `current` or
  `conflicts`. This preserves one reconciliation implementation.

## Identity and isolation

The shared endpoint, store, namespace, management owner, and Playbook are group
configuration. `RAM_PARTICIPANT`, `RAM_PERSONAL_NAMESPACE`, and preferably both
API keys are per-user. Participant is attribution, not authenticated identity;
server-side API-key policy remains the authorization boundary.

Candidate IDs include participant, source session, turn, and subject. Shared
session IDs, event markers, and RAM idempotency keys are deterministic. A retry
therefore returns the prior submission instead of creating duplicate state.

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
4. Include a token-shaped value and a malicious transcript-path string in a
   test session. Verify neither appears in the local ledger or MCP output.
