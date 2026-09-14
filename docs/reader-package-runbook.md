# Reader Runbook

## Install

Open Terminal in this extracted folder:

```sh
claude --version
node --version
./install.sh
```

Node must be version 20+. Enter the **same** Agent Memory HTTPS endpoint, Store
ID, Store API Key, and namespace as Editor. Never paste the key into Claude or a
message.

Use:

```text
Testing namespace:      northstar-pilot-qa
Presentation namespace: northstar-pilot-demo
Participant ID:         demo-reader
```

Rerun `./install.sh` to correct settings or switch namespace.
If installation warns that a RAM dependency is unavailable, setup still
completed. Ask the Editor user to seed an empty store before searching.

## Quick check

```sh
node ~/.local/share/redis-shared-memory/reader/current/bin/verify.cjs reader ~/.local/share/redis-shared-memory/reader/current/bin/run-server.sh
```

## Test or demo

```sh
~/.local/bin/redis-memory-reader
```

Paste one prompt at a time:

```text
Run reader_status. Report role, connection, namespace, participant, and permissions.
```

```text
Use reader_search to find Northstar Retail's pilot region requirement. Return the exact memory ID and fact.
```

```text
Use shared memory to prepare Northstar Retail's pilot plan. Include region, duration, participants, data constraints, and success criteria. Cite the exact memory IDs.
```

Read-only check:

```text
Change the shared pilot duration to six weeks.
```

Expected: Reader has only status/search and cannot perform the change. Exit
Claude with `/exit`.

## Uninstall

```sh
~/.local/share/redis-shared-memory/reader/current/uninstall.sh
```

This removes Reader and its local credential, not Editor or RAM records.

## Troubleshooting

- No results: confirm endpoint, Store ID/key pair, and namespace; rerun installer.
- `access_denied`: ask the demo owner for a valid Agent Memory service API key,
  Endpoint, and Store ID copied from the same Redis Cloud service, then rerun
  `./install.sh`. Never send the key through chat or email.
- `dependency_unavailable`: ask the Editor user to seed an empty store,
  using `./seed.sh qa` or `./seed.sh demo` from the extracted Editor ZIP, then
  retry search. If Redis Insight already shows the fixtures, do not reseed;
  wait and retry or check the Agent Memory service. For
  `database_out_of_memory`, contact the service owner.
- Connection fails: check internet/VPN and the Agent Memory endpoint.
- Security software blocks a file: do not bypass it; capture the message for IT.
