# Security

## Security model

This POC runs a bundled stdio MCP server locally with the signed-in operating
system user's privileges. It makes outbound HTTPS requests to the one Redis
Agent Memory endpoint configured in the user's external credential file.

The desktop plugin exposes read and write tools. Installation therefore grants
code-execution and network access appropriate to that local server. Enterprise
administrators should review and allowlist the exact repository and Git ref,
the Python runtime, and the permitted Redis endpoint before deployment.

## Credentials and identity

The populated credential file must remain outside the repository and plugin
cache at:

```text
~/.config/redis-shared-memory/editor.env
```

The loader accepts only a regular, non-symlink file owned by the current user
with mode `0600`. The plugin rejects unknown or duplicate settings. Do not put
credentials in chat, source control, plugin metadata, command arguments, or
logs.

`RAM_API_KEY` authenticates this POC to Redis Agent Memory. `RAM_PARTICIPANT`
is only contributor attribution supplied by local configuration; it is not
proof of the human user's identity. A production multi-user deployment should
replace this asserted identity with server-validated OAuth identity and enforce
authorization on every request.

## Data boundaries

- The endpoint must use HTTPS and cannot contain URL credentials, query
  parameters, or fragments.
- The store and namespace are fixed by local configuration and are not exposed
  as model-controlled tool inputs.
- RAM requests include the configured namespace, and returned records are
  checked again before disclosure or mutation.
- Retrieved facts are untrusted reference data and must never be treated as
  executable instructions.
- Public tool responses are deliberately smaller than raw SDK responses, and
  dependency errors are mapped to sanitized messages.

The local namespace boundary is application enforcement, not a substitute for
least-privilege Redis credentials. Use a credential restricted to the smallest
store and operations supported by the deployment whenever the service permits
it.

## Write safety

`editor_publish` is an additive write. `editor_update` overwrites an existing
record and is marked destructive. Both tool descriptions require explicit user
intent, and deployments should retain host approval prompts for write tools.

The service disables automatic SDK retries. A publish retries only after a
read proves the generated ID does not exist, and reuses that ID. An update is
never replayed after an uncertain response. The plugin reports an unverified
outcome when it cannot prove persistence.

## Supply chain and distribution

- Pin customer installations to a reviewed tag or commit instead of an
  unbounded branch.
- The installed plugin uses committed Python standard-library source and does
  not run `pip install`, `npm install`, package lifecycle hooks, or runtime
  downloads.
- The MCP command uses Python isolated mode (`-I`) so `PYTHONPATH` and
  user-installed site packages cannot inject code into the plugin process.
- `BUILD.json` records a digest of the reviewed source set. Refresh it with
  `npm run build:plugin` and verify the result with `npm run check`.
- The inherited Claude packages still use locked Node dependencies; use
  `npm ci` and the committed lockfile when testing the complete repository.
- Adding lifecycle hooks, installers, telemetry, native executables, a new
  network destination, or an arbitrary upstream MCP proxy requires a new
  security review.

## Reporting a vulnerability

Do not open a public issue containing credentials, customer data, or exploit
details. Use GitHub's private vulnerability reporting/security-advisory flow
for this repository, or contact the repository owners through your approved
internal security channel. Include the affected ref, reproduction steps,
impact, and whether any credential may have been exposed.
