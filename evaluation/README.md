# Offline quality gate

Run the fixed 15-case gate before sharing a release:

```sh
python3 evaluation/run.py
```

The corpus contains ten decision-ready cases, three stale or conflicted cases,
and two cases that require abstention. The gate checks:

- RAM recall at 20 is at least 85%;
- agenda precision and recall are each above 80%;
- every emitted item's material fields have traversable evidence;
- no resolved, superseded, or conflicted-only state is included;
- every case uses the expected Playbook entry version and digest; and
- both insufficient-evidence cases abstain.

Wall-clock latency and a deterministic token estimate are reported but do not
gate the build. To refresh the committed deterministic report after an
intentional behavior or fixture change, run:

```sh
python3 evaluation/run.py --write
git diff -- evaluation/cases.json evaluation/results.json
```

Never loosen a threshold merely to make a change pass. Update a case only when
the reviewed product contract changed, and explain the contract change in the
same commit.
