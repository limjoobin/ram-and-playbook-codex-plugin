import { lstatSync, readFileSync } from 'node:fs';
import { loadConfig, type Config } from './config.js';

const allowed = new Set(['RAM_ENDPOINT', 'RAM_STORE_ID', 'RAM_NAMESPACE', 'RAM_PARTICIPANT', 'RAM_API_KEY']);

export function loadCredentialFile(path: string): Config {
  const metadata = lstatSync(path);
  if (!metadata.isFile() || metadata.isSymbolicLink()) throw new Error('credential_file_invalid');
  if ((metadata.mode & 0o777) !== 0o600) throw new Error('credential_file_permissions');
  if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) throw new Error('credential_file_owner');

  const values: NodeJS.ProcessEnv = {};
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    if (!line) continue;
    const separator = line.indexOf('=');
    const key = separator < 0 ? line : line.slice(0, separator);
    if (!allowed.has(key) || values[key] !== undefined) throw new Error('credential_file_contents');
    values[key] = separator < 0 ? '' : line.slice(separator + 1);
  }
  return loadConfig(values);
}
