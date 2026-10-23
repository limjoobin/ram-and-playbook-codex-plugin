import { lstatSync, readFileSync } from 'node:fs';
import { DemoError, loadConfig, type Config } from './config.js';

const allowed = new Set(['RAM_ENDPOINT', 'RAM_STORE_ID', 'RAM_NAMESPACE', 'RAM_PARTICIPANT', 'RAM_API_KEY']);

export function loadCredentialFile(path: string): Config {
  let metadata;
  try { metadata = lstatSync(path); }
  catch { throw new DemoError('configuration_missing', 'Create the local Redis Shared Memory .env file before using this plugin.'); }
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new DemoError('credential_file_invalid', 'The local Redis Shared Memory .env must be a regular file, not a symlink.');
  }
  if ((metadata.mode & 0o777) !== 0o600) {
    throw new DemoError('credential_file_permissions', 'Set the local Redis Shared Memory .env permissions to 0600.');
  }
  if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) {
    throw new DemoError('credential_file_owner', 'The local Redis Shared Memory .env must be owned by the current user.');
  }

  const values: NodeJS.ProcessEnv = {};
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    if (!line) continue;
    const separator = line.indexOf('=');
    const key = separator < 0 ? line : line.slice(0, separator);
    if (!allowed.has(key) || values[key] !== undefined) {
      throw new DemoError('credential_file_contents', 'The local Redis Shared Memory .env contains an unexpected or duplicate setting.');
    }
    values[key] = separator < 0 ? '' : line.slice(separator + 1);
  }
  return loadConfig(values);
}
