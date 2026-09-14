# Editor Runbook

## Seed before installation

Open Terminal in this extracted folder and run one command:

```sh
./seed.sh qa
```

For the presentation namespace instead:

```sh
./seed.sh demo
```

Enter the Endpoint, Store ID, and matching service API key. This command does
not require Editor or Claude to be installed, and it does not save the key.
If it reports `search_pending_ids`, the fixtures are saved; wait briefly and
continue with installation rather than seeding them again.

## Install

Open Terminal in this extracted folder:

```sh
claude --version
node --version
./install.sh
```

Node must be version 20+. Enter the Agent Memory HTTPS endpoint, Store ID, and
matching Store API Key. Never paste the key into Claude or a message.

Use:

```text
Testing namespace:     northstar-pilot-qa
Presentation namespace: northstar-pilot-demo
Participant ID:         hillary
```

Rerun `./install.sh` to correct settings or switch namespace.
If installation warns that a RAM dependency is unavailable, setup still
completed. For an empty store, seed memories before searching.

## Quick check

```sh
node ~/.local/share/redis-shared-memory/editor/current/bin/verify.cjs editor ~/.local/share/redis-shared-memory/editor/current/bin/run-server.sh
```

## Seed or restore fixtures

From the extracted ZIP, even before installation:

```sh
./seed.sh qa
./seed.sh demo
```

Or, after Editor is installed:

```sh
~/.local/bin/redis-memory-seed reset qa
~/.local/bin/redis-memory-seed reset demo
```

`reset` creates missing fixtures and restores the six baseline facts. It does
not delete other records. To clear the demo first, use the Agent Memory
Console's supported memory-clear action, then seed once. Never run `FLUSHDB`,
`FLUSHALL`, or delete backing keys through Redis Insight; that can remove the
managed search index while leaving Agent Memory unusable.

## Test or demo

```sh
~/.local/bin/redis-memory-editor
```

Paste one prompt at a time:

```text
Run editor_status. Report role, connection, namespace, participant, and permissions.
```

```text
Use editor_search to find Northstar Retail's pilot region requirement. Return the exact memory ID and fact.
```

```text
Publish this shared QA fact: "Package rehearsal: the demo rollout owner is Hillary."
```

```text
Find the Package rehearsal memory and update that exact ID to: "Package rehearsal: the demo rollout owner is Hillary and status is ready." Do not create a new memory.
```

For the presentation, use `northstar-pilot-demo` and paste:

```text
Find Northstar Retail's pilot region memory and update that exact memory: the pilot must now deploy in Tokyo. Preserve unrelated requirements. Return the memory ID and outcome.
```

Continue only after `saved_and_searchable`. Exit Claude with `/exit`.

## Uninstall

```sh
~/.local/share/redis-shared-memory/editor/current/uninstall.sh
```

This removes Editor and its local credential, not Reader or RAM records.

## Troubleshooting

- No results: confirm endpoint, Store ID/key pair, and namespace; rerun installer.
- `access_denied`: generate a new Agent Memory service API key in Redis Cloud,
  copy the Endpoint and Store ID from the same service's Configuration tab, and
  rerun `./install.sh`. Redis displays a newly generated key only once.
- `dependency_unavailable`: if the Agent Memory Console shows an empty store,
  seed it once and retry search. If Redis Insight already shows the fixtures,
  do not reseed;
  wait and retry or check the Agent Memory service. For
  `database_out_of_memory`, contact the Redis service owner.
- `saved_search_pending`: wait and search again; do not republish.
- `write_unverified`: search and reconcile; do not retry automatically.
- Security software blocks a file: do not bypass it; capture the message for IT.
