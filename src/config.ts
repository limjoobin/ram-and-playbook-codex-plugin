export type Role = 'editor' | 'reader';
export const VERSION = '0.1.1';
export const SLUG = /^[a-zA-Z0-9-]{1,64}$/;

export class DemoError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

export interface Config {
  endpoint: string; storeId: string; namespace: string; participant: string; apiKey: string;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const names = ['RAM_ENDPOINT', 'RAM_STORE_ID', 'RAM_NAMESPACE', 'RAM_PARTICIPANT', 'RAM_API_KEY'] as const;
  const missing = names.filter(name => !env[name]?.trim());
  if (missing.length) throw new DemoError('configuration_missing', `Complete these local connection settings: ${missing.join(', ')}.`);
  const endpoint = env.RAM_ENDPOINT!.trim();
  let url: URL;
  try { url = new URL(endpoint); } catch { throw new DemoError('configuration_invalid', 'RAM endpoint must be an HTTPS URL.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new DemoError('configuration_invalid', 'Use an HTTPS endpoint without credentials, query parameters, or fragments.');
  }
  for (const name of ['RAM_STORE_ID', 'RAM_NAMESPACE', 'RAM_PARTICIPANT'] as const) {
    if (!SLUG.test(env[name]!.trim())) throw new DemoError('configuration_invalid', `${name} must contain 1–64 letters, digits, or hyphens.`);
  }
  if (env.RAM_API_KEY!.startsWith('__encrypted__:')) throw new DemoError('credential_unavailable', 'The configured RAM credential is unavailable. Replace it in the local .env file.');
  return { endpoint: endpoint.replace(/\/+$/, ''), storeId: env.RAM_STORE_ID!.trim(),
    namespace: env.RAM_NAMESPACE!.trim(), participant: env.RAM_PARTICIPANT!.trim(), apiKey: env.RAM_API_KEY!.trim() };
}

// Never return raw SDK exceptions: they can contain HTTP headers or payloads.
export type PublicError = { code: string; message: string; dependency_type?: 'resource_unavailable' | 'database_out_of_memory' };

export function publicError(error: unknown): PublicError {
  if (error instanceof DemoError) return { code: error.code, message: error.message };
  const e = error as { statusCode?: number; status?: number; name?: string; type?: string; response$?: { status?: number } } | null;
  const status = e?.statusCode ?? e?.status ?? e?.response$?.status;
  if (status === 401) return { code: 'authentication_failed', message: 'RAM rejected the API key. Replace it in the local .env file.' };
  if (status === 403) return { code: 'access_denied', message: 'RAM denied access. Check that the API key can access the configured store.' };
  if (status === 404) return { code: 'not_found', message: 'The RAM store or memory was not found. Check the store ID and memory ID.' };
  if (status === 429) return { code: 'rate_limited', message: 'RAM is rate limited. Wait briefly before trying again.' };
  if (status === 400 || status === 413) return { code: 'request_rejected', message: 'RAM rejected the request. Check the configured store and shorten the fact if necessary.' };
  if (status === 424 || /FailedDependency/.test(e?.name ?? '')) {
    if (e?.type === '/errors/database-out-of-memory') return { code: 'dependency_unavailable', dependency_type: 'database_out_of_memory',
      message: 'RAM reports that database capacity is unavailable. Contact the Redis service owner before seeding or retrying.' };
    if (e?.type === '/errors/resource-unavailable') return { code: 'dependency_unavailable', dependency_type: 'resource_unavailable',
      message: 'RAM reports that a required resource is unavailable. If this store is empty or was flushed, seed memories and then retry search; otherwise wait briefly and retry.' };
    return { code: 'dependency_unavailable', message: 'RAM could not complete the request because a dependency is unavailable. If this store is empty or was flushed, seed memories and then retry search; otherwise check the Redis service.' };
  }
  if (status === 408 || /Timeout|Abort/.test(e?.name ?? '')) return { code: 'timeout', message: 'RAM did not respond in time. Check connectivity and try a read before retrying a write.' };
  if (status && status >= 500) return { code: 'service_unavailable', message: 'RAM is temporarily unavailable. Try again later.' };
  if (/Connection|TypeError/.test(e?.name ?? '')) return { code: 'network_error', message: 'Cannot reach RAM. Check the endpoint, internet connection, and VPN.' };
  return { code: 'unexpected_error', message: 'The RAM request could not be verified. Check the local connection settings and run the status tool.' };
}
