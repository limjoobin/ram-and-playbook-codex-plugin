# Private session capture and shared promotion

## Boundary

The plugin has one local Python MCP. It does not introduce a second service or
a second organizational-state reconciler.

`UserPromptSubmit`, `PostToolUse`, `Stop`, and `SessionEnd` hooks append bounded
events to `RAM_PERSONAL_NAMESPACE`. RAM owns session memory and any configured
personal long-term-memory extraction. A local append-only ledger holds only the
review queue and deterministic provenance needed for the MCP candidate tools.

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

## Manual acceptance

1. Complete a small task without asking to share it. Verify private RAM events
   use only the personal namespace and shared state remains unchanged.
2. Ask to remember a non-sensitive completed result for the team. List and
   inspect the pending candidate; verify captured evidence and attribution.
3. Refuse or reject it. Verify no shared RAM event or organizational state is
   created.
4. Repeat with a second candidate and explicitly confirm its project, state
   kind, lifecycle, subject, and optional owner/dates. Promote it once.
5. Repeat the identical promotion call. Verify it returns
   `already_submitted` and adds no source event.
6. After RAM extraction, query `ram_search_state` with `view="history"`; verify
   one observation with exact fields, participant attribution, and traversable
   source evidence. Run the central projector, then verify the `current` view.
7. Repeat from a second user with a different participant and personal
   namespace. Verify private candidates stay isolated while both confirmed
   observations enter the same shared namespace.
8. Include a token-shaped value and a malicious transcript-path string in a
   test session. Verify neither appears in the local ledger or MCP output.
