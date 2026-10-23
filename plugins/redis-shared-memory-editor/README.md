# Redis Shared Memory — Editor

This plugin lets multiple ChatGPT desktop users and their agents work from one
Redis Agent Memory store and namespace. It exposes:

- `editor_status`
- `editor_search`
- `editor_publish`
- `editor_update`

The MCP server is dependency-free Python 3.10+ source. It has no lifecycle
hook, installer, package-manager step, or runtime download.

Each user creates a private configuration file at:

```text
~/.config/redis-shared-memory/editor.env
```

Users in one collaboration group configure the same `RAM_ENDPOINT`,
`RAM_STORE_ID`, and `RAM_NAMESPACE`. Each user configures their own
`RAM_PARTICIPANT` and preferably their own `RAM_API_KEY`.

`RAM_API_KEY` authenticates requests. `RAM_PARTICIPANT` is contributor
attribution, not verified identity. Never put the populated file in the
repository, plugin cache, or chat.

See the repository's `CODEX_INSTALLATION.md` for installation and verification.
Maintainers should read `AGENTS.md`, `SECURITY.md`, and
`docs/adding-tools.md` before changing behavior.
