import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { openPackage, call, root } from '../tests/package-harness.js';
import { loadConfig, publicError } from '../src/config.js';

async function main() {
  const config = loadConfig();
  assert.equal(config.namespace, 'northstar-pilot-qa', 'Live integration tests only write to northstar-pilot-qa.');
  const env = { RAM_ENDPOINT: config.endpoint, RAM_STORE_ID: config.storeId, RAM_NAMESPACE: config.namespace,
    RAM_PARTICIPANT: config.participant, RAM_API_KEY: config.apiKey };
  const editor = await openPackage('editor', env);
  let reader: Awaited<ReturnType<typeof openPackage>> | undefined;
  const report: Record<string, unknown> = { tested_at: new Date().toISOString(), namespace: config.namespace,
    editor_sha256: editor.digest, claude_code_session_acceptance: 'tested separately' };
  try {
    reader = await openPackage('reader', { ...env, RAM_PARTICIPANT: 'local-reader-test' });
    report.reader_sha256 = reader.digest;
    assert.equal((await call(editor.client, 'editor_status')).data.connection, 'verified');
    assert.equal((await call(reader.client, 'reader_status')).data.connection, 'verified');
    const marker = randomUUID();
    const first = `QA rehearsal ${marker}: Northstar Retail pilot must deploy in Singapore.`;
    const second = `QA rehearsal ${marker}: Northstar Retail pilot must deploy in Tokyo.`;
    const created = (await call(editor.client, 'editor_publish', { fact: first })).data;
    report.publish = created.outcome;
    assert.equal(created.outcome, 'saved_and_searchable');
    const id = created.memory.memory_id; report.memory_id = id;
    assert.ok((await call(reader.client, 'reader_search', { query: first })).data.memories.some((m: { memory_id: string; fact: string }) => m.memory_id === id && m.fact === first));
    assert.equal((await call(editor.client, 'editor_update', { memory_id: id, fact: second })).data.outcome, 'saved_and_searchable');
    assert.ok((await call(reader.client, 'reader_search', { query: second })).data.memories.some((m: { memory_id: string; fact: string }) => m.memory_id === id && m.fact === second));
    assert.equal((await reader.client.callTool({ name: 'editor_publish', arguments: { fact: 'Should be denied' } })).isError, true);
    report.result = 'passed';
  } catch (e) { report.result = 'failed'; report.error = publicError(e); process.exitCode = 1; }
  finally {
    await editor.close(); if (reader) await reader.close();
    await mkdir(join(root, 'reports'), { recursive: true });
    await writeFile(join(root, 'reports/live-latest.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  }
}
main().catch(e => { console.error(JSON.stringify({ result: 'not_run', ...publicError(e) })); process.exitCode = 1; });
