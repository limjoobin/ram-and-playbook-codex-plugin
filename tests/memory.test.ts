import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import type { CreateMemoryRecord, MemoryRecord, SearchLongTermMemoryRequestContent, UpdateLongTermMemoryRequestContent } from '@redis-iris/agent-memory/models';
import { SharedMemory, RAMClient } from '../src/memory.js';
import { Config, loadConfig, publicError } from '../src/config.js';
import { createServer } from '../src/server.js';

const config: Config = { endpoint: 'https://example.test', apiKey: 'test-secret-never-display', storeId: 'store', namespace: 'northstar-pilot-qa', participant: 'hillary' };
function record(id = 'region', namespace = config.namespace, text = 'Singapore'): MemoryRecord {
  return { id, namespace, text, ownerId: 'another-person', createdAt: new Date(), updatedAt: new Date() };
}
class FakeRAM implements RAMClient {
  records = new Map<string, MemoryRecord>();
  creates: string[] = []; updates = 0; searches: SearchLongTermMemoryRequestContent[] = [];
  hideSearch = false; failGet = false; dropWrite = false; timeoutAfterSave = false; failFirstCreate = false; indexingFailures = 0;
  async searchLongTermMemory(request?: SearchLongTermMemoryRequestContent) {
    this.searches.push(request ?? {});
    if (this.indexingFailures-- > 0) throw { statusCode: 424, name: 'FailedDependencyErrorResponseContent' };
    return { items: this.hideSearch ? [] : [...this.records.values()].filter(r => r.namespace === request?.filter?.namespace?.eq) };
  }
  async getLongTermMemory(id: string) {
    if (this.failGet) throw { name: 'ConnectionError' };
    const m = this.records.get(id); if (!m) throw { statusCode: 404 };
    return { ...m };
  }
  async bulkCreateLongTermMemories({ memories }: { memories: CreateMemoryRecord[] }) {
    this.creates.push(memories[0].id);
    if (this.failFirstCreate && this.creates.length === 1) throw { name: 'ConnectionError' };
    if (!this.dropWrite) for (const m of memories) this.records.set(m.id, { ...m, createdAt: new Date(), updatedAt: new Date() });
    if (this.timeoutAfterSave) throw { name: 'RequestTimeoutError' };
    return { created: this.dropWrite ? [] : memories.map(m => m.id), errors: this.dropWrite ? [{ id: memories[0].id, error: 'rejected' }] : [] };
  }
  async updateLongTermMemory(id: string, body?: UpdateLongTermMemoryRequestContent) {
    this.updates++;
    const before = await this.getLongTermMemory(id);
    if (!this.dropWrite) this.records.set(id, { ...before, text: body?.text ?? before.text, updatedAt: new Date() });
    if (this.timeoutAfterSave) throw { name: 'RequestTimeoutError' };
    return this.getLongTermMemory(id);
  }
}
const service = (role: 'editor' | 'reader', ram = new FakeRAM()) => new SharedMemory(role, config, ram, 0, 0);

test('reader rejects both mutation methods before accessing RAM', async () => {
  const ram = new FakeRAM(), reader = service('reader', ram);
  await assert.rejects(reader.publish('change'), /only reads/);
  await assert.rejects(reader.update('region', 'change'), /only reads/);
  assert.equal(ram.creates.length + ram.updates, 0);
});
test('shared search includes another contributor and always sends namespace filter', async () => {
  const ram = new FakeRAM(); ram.records.set('region', record());
  const result = await service('reader', ram).search('deployment');
  assert.equal(result.memories[0].fact, 'Singapore');
  assert.deepEqual(ram.searches[0].filter, { namespace: { eq: config.namespace } });
});
test('empty results remain empty and status performs a RAM read', async () => {
  const ram = new FakeRAM(), reader = service('reader', ram);
  assert.deepEqual((await reader.search('missing')).memories, []);
  assert.equal((await reader.status()).contains_memories, false);
  assert.equal(ram.searches.length, 2);
});
test('search tolerates a transient indexing dependency rebuild', async () => {
  const ram = new FakeRAM(); ram.records.set('region', record()); ram.indexingFailures = 2;
  const reader = new SharedMemory('reader', config, ram, 1000, 0);
  assert.equal((await reader.search('region')).memories[0].memory_id, 'region');
});
test('update rejects a different namespace without a write', async () => {
  const ram = new FakeRAM(); ram.records.set('outside', record('outside', 'other-project'));
  await assert.rejects(service('editor', ram).update('outside', 'Tokyo'), /outside/);
  assert.equal(ram.updates, 0);
});
test('unexpected out-of-scope search results are not disclosed', async () => {
  const ram = new FakeRAM(); ram.searchLongTermMemory = async () => ({ items: [record('outside', 'other')] });
  await assert.rejects(service('reader', ram).search('anything'), /outside/);
});
test('publish and update become visible to an independent reader on the same ID', async () => {
  const ram = new FakeRAM(), editor = service('editor', ram), reader = service('reader', ram);
  const created = await editor.publish('Northstar pilot in Singapore');
  assert.equal(created.outcome, 'saved_and_searchable');
  const id = ram.creates[0];
  assert.equal((await editor.update(id, 'Northstar pilot in Tokyo')).outcome, 'saved_and_searchable');
  assert.equal((await reader.search('region')).memories[0].fact, 'Northstar pilot in Tokyo');
  assert.equal(ram.records.size, 1);
});
test('retry after definite absence reuses the same publish ID', async () => {
  const ram = new FakeRAM(); ram.failFirstCreate = true;
  assert.equal((await service('editor', ram).publish('fact')).outcome, 'saved_and_searchable');
  assert.equal(ram.creates.length, 2); assert.equal(ram.creates[0], ram.creates[1]);
});
test('timeout after save reconciles without duplicate creation or update replay', async () => {
  const ram = new FakeRAM(); ram.timeoutAfterSave = true;
  const editor = service('editor', ram);
  assert.equal((await editor.publish('Singapore')).outcome, 'saved_and_searchable');
  assert.equal(ram.creates.length, 1);
  assert.equal((await editor.update(ram.creates[0], 'Tokyo')).outcome, 'saved_and_searchable');
  assert.equal(ram.updates, 1);
});
test('failed readback and partial create rejection never report success', async () => {
  const ram = new FakeRAM(); ram.dropWrite = true;
  const result = await service('editor', ram).publish('fact');
  assert.equal(result.ok, false); assert.equal(result.outcome, 'write_unverified');
  ram.records.set('region', record());
  assert.equal((await service('editor', ram).update('region', 'Tokyo')).ok, false);
});
test('verified persistence but invisible search is reported separately', async () => {
  const ram = new FakeRAM(); ram.hideSearch = true;
  assert.equal((await service('editor', ram).publish('fact')).outcome, 'saved_search_pending');
});
test('unknown persistence does not trigger a blind second publish', async () => {
  const ram = new FakeRAM(); ram.timeoutAfterSave = true; ram.failGet = true;
  const result = await service('editor', ram).publish('fact');
  assert.equal(result.ok, false); assert.equal(result.outcome, 'write_unverified');
  assert.equal(ram.creates.length, 1);
});
test('configuration rejects missing settings and credential-bearing endpoints', () => {
  assert.throws(() => loadConfig({}), /Complete these/);
  assert.throws(() => loadConfig({ RAM_ENDPOINT: 'https://user:secret@example.test', RAM_STORE_ID: 'store', RAM_NAMESPACE: 'ns', RAM_PARTICIPANT: 'me', RAM_API_KEY: 'secret' }), /without credentials/);
});
test('errors do not disclose SDK headers, credentials, or payloads', () => {
  for (const statusCode of [401, 403, 404, 408, 429, 500]) {
    const result = publicError({ statusCode, message: config.apiKey, headers: { authorization: config.apiKey } });
    assert.ok(!JSON.stringify(result).includes(config.apiKey));
  }
  assert.equal(publicError({ statusCode: 401 }).code, 'authentication_failed');
  assert.deepEqual(publicError({ statusCode: 424, type: '/errors/resource-unavailable' }), {
    code: 'dependency_unavailable', dependency_type: 'resource_unavailable',
    message: 'RAM reports that a required resource is unavailable. If this store is empty or was flushed, seed memories and then retry search; otherwise wait briefly and retry.',
  });
  assert.equal(publicError({ statusCode: 424, type: '/errors/database-out-of-memory' }).dependency_type, 'database_out_of_memory');
  assert.equal(publicError({ statusCode: 424, detail: config.apiKey }).code, 'dependency_unavailable');
  assert.ok(!JSON.stringify(publicError({ statusCode: 424, detail: config.apiKey })).includes(config.apiKey));
  assert.equal(publicError({ name: 'ConnectionError' }).code, 'network_error');
});
test('MCP reader listing and direct call cannot access editor writes; rejects extra scope arguments', async () => {
  const ram = new FakeRAM();
  const server = createServer('reader', () => service('reader', ram));
  const [a, b] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'test', version: '1' });
  await server.connect(a); await client.connect(b);
  try {
    assert.deepEqual((await client.listTools()).tools.map(t => t.name), ['reader_status', 'reader_search']);
    const denied = await client.callTool({ name: 'editor_publish', arguments: { fact: 'change' } });
    assert.equal(denied.isError, true);
    const invalid = await client.callTool({ name: 'reader_search', arguments: { query: 'pilot', namespace: 'other' } });
    assert.equal(invalid.isError, true);
    assert.equal(ram.creates.length + ram.updates + ram.searches.length, 0);
  } finally { await client.close(); await server.close(); }
});
