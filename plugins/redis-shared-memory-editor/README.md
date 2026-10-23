# Redis Shared Memory — Editor for Codex

This is the Codex and ChatGPT desktop counterpart of the local Claude Desktop
Editor integration. It reuses the same MCP implementation and exposes these
write-capable tools:

- `editor_status`
- `editor_search`
- `editor_publish`
- `editor_update`

The plugin has no lifecycle hooks or installer scripts. It runs readable,
dependency-free source with the computer's existing Python 3.10+ runtime and
reads credentials from:

```text
~/.config/redis-shared-memory/editor.env
```

You may override that path with `REDIS_SHARED_MEMORY_CONFIG` when the desktop
process receives that environment variable. The default fixed path is more
reliable for apps launched outside a shell.

Create the file yourself from `.env.example`, make it mode `0600`, and never
place the populated file inside this repository or the Codex plugin cache.

`RAM_PARTICIPANT` is contributor attribution in this POC. The RAM API key is the
actual credential; OAuth-derived user identity is a later authentication phase.

See the repository's `CODEX_INSTALLATION.md` for installation and verification.
Maintainers and coding agents should also read `AGENTS.md`, `SECURITY.md`, and
`docs/adding-tools.md` at the repository root before changing tools or
configuration.
