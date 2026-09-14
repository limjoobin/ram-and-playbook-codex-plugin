import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

export const root = resolve(import.meta.dirname, '..');
export async function openPackage(role: 'editor' | 'reader', env: Record<string, string> = {}) {
  const release = JSON.parse(await readFile(join(root, 'dist/claude-code/release.json'), 'utf8'));
  const artifact = release.artifacts.find((a: { file: string }) => a.file.includes(`-${role}-`));
  const zip = join(root, 'dist/claude-code', artifact.file);
  const digest = createHash('sha256').update(await readFile(zip)).digest('hex');
  if (digest !== artifact.sha256) throw new Error('Release artifact checksum mismatch.');
  const dir = await mkdtemp(join(tmpdir(), `ram-package-${role}-`));
  execFileSync('/usr/bin/unzip', ['-q', zip, '-d', dir]);
  const manifest = JSON.parse(await readFile(join(dir, 'manifest.json'), 'utf8'));
  let stderr = '';
  const transport = new StdioClientTransport({ command: process.execPath,
    args: [join(dir, manifest.server.entry_point)], cwd: dir,
    env: { PATH: '/usr/bin:/bin', ...env }, stderr: 'pipe' });
  transport.stderr?.on('data', data => { stderr += data.toString(); });
  const client = new Client({ name: 'shared-memory-package-test', version: '1' });
  try { await client.connect(transport); }
  catch (e) { await transport.close(); await rm(dir, { recursive: true, force: true }); throw e; }
  return { client, manifest, dir, artifact, digest, stderr: () => stderr,
    close: async () => { await client.close(); await rm(dir, { recursive: true, force: true }); } };
}

export async function call(client: Client, name: string, args: Record<string, unknown> = {}) {
  const result = await client.callTool({ name, arguments: args }, undefined, { timeout: 60000 });
  const text = (result.content as Array<{ type: string; text?: string }>).find(c => c.type === 'text')?.text;
  return { result, data: text ? JSON.parse(text) : result.structuredContent };
}
