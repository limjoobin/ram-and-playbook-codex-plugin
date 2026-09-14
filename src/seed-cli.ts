import { createHash } from 'node:crypto';
import { AgentMemory } from '@redis-iris/agent-memory';
import type { MemoryRecord } from '@redis-iris/agent-memory/models';
import { createRAMClient } from './memory.js';
import { publicError } from './config.js';
import { loadCredentialFile } from './credential-file.js';

const facts = [
  ['objective', "Northstar Retail's pilot will help support agents find approved troubleshooting guidance."],
  ['region', "Northstar Retail's pilot must deploy in the Singapore region."],
  ['duration', "Northstar Retail's pilot will run for four weeks."],
  ['participants', 'Twenty Northstar Retail support agents will evaluate the pilot.'],
  ['data', "Only synthetic support tickets are permitted in Northstar Retail's pilot."],
  ['evaluation', 'Northstar Retail will evaluate the pilot on answer correctness and accurate source references.'],
] as const;

function uuidBytes(uuid: string) { return Buffer.from(uuid.replaceAll('-', ''), 'hex'); }
function uuid5(name: string) {
  const digest = createHash('sha1').update(uuidBytes('6ba7b811-9dad-11d1-80b4-00c04fd430c8')).update(name).digest().subarray(0, 16);
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  const hex = digest.toString('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function records(namespace: string) {
  return facts.map(([key, text]) => ({ id: `fixture-${uuid5(`${namespace.toLowerCase()}/${key}`)}`,
    text, namespace, ownerId: 'northstar-demo', memoryType: 'semantic' as const,
    topics: ['northstar-pilot', 'fixture', key] }));
}

async function main() {
  const [action, target, credentialPath] = process.argv.slice(2);
  if (!['seed', 'reset'].includes(action) || !['qa', 'demo'].includes(target) || !credentialPath) {
    process.stderr.write('Usage: redis-memory-seed <seed|reset> <qa|demo>\n');
    process.exitCode = 2;
    return;
  }
  const namespace = target === 'qa' ? 'northstar-pilot-qa' : 'northstar-pilot-demo';
  let stage = 'configuration';
  try {
    const config = loadCredentialFile(credentialPath);
    const client = createRAMClient(config) as AgentMemory;
    const desired = records(namespace);
    const existing = new Map<string, MemoryRecord>();
    const missing = [];
    stage = 'fixture-read';
    for (const record of desired) {
      try {
        const item = await client.getLongTermMemory(record.id);
        if (item.namespace?.toLowerCase() !== namespace) throw new Error('scope_mismatch');
        existing.set(record.id, item);
      } catch (error) {
        if (publicError(error).code !== 'not_found') throw error;
        missing.push(record);
      }
    }
    if (missing.length) {
      stage = 'fixture-create';
      const result = await client.bulkCreateLongTermMemories({ memories: missing });
      const failed = missing.filter(record => !result.created.includes(record.id));
      if (result.errors?.length || failed.length) stage = `fixture-create-${missing.length}-${result.created.length}-${result.errors?.length ?? 0}`;
      if (result.errors?.length || failed.length) throw new Error('fixture_create_failed');
    }
    if (action === 'reset') {
      stage = 'fixture-reset';
      for (const record of desired) {
        const before = existing.get(record.id);
        if (!before || before.text === record.text) continue;
        await client.updateLongTermMemory(record.id, { text: record.text, namespace,
          ownerId: before.ownerId, sessionId: before.sessionId ?? '', memoryType: 'semantic', topics: record.topics });
      }
    }
    stage = 'fixture-readback';
    const persisted = new Set<string>();
    for (const expected of desired) {
      const item = await client.getLongTermMemory(expected.id);
      if (item.namespace?.toLowerCase() !== namespace || item.text !== expected.text) throw new Error('fixture_readback_mismatch');
      persisted.add(item.id);
    }
    const deadline = Date.now() + 10_000;
    let visible = new Set<string>();
    stage = 'fixture-verify';
    do {
      try {
        const result = await client.searchLongTermMemory({ filter: { namespace: { eq: namespace } }, limit: 100 });
        visible = new Set(result.items.filter(item => desired.some(record => record.id === item.id && record.text === item.text)).map(item => item.id));
      } catch (error) {
        if (publicError(error).code !== 'dependency_unavailable') throw error;
      }
      if (visible.size === desired.length) break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    } while (Date.now() < deadline);
    const pending = desired.filter(record => !visible.has(record.id)).map(record => record.id);
    process.stdout.write(`${JSON.stringify({ ok: true, namespace, action, created: missing.length,
      preserved: action === 'seed' ? existing.size : 0, reset: action === 'reset' ? existing.size : 0,
      verified_ids: [...persisted], searchable_ids: [...visible], search_pending_ids: pending,
      ...(pending.length ? { next_step: 'Fixtures are saved. Wait briefly, then retry search; do not seed again.' } : {}) }, null, 2)}\n`);
  } catch (error) {
    const safe = publicError(error);
    const errorName = error instanceof Error ? error.name.replace(/[^a-zA-Z0-9-]/g, '').toLowerCase() : 'unknown';
    const code = safe.code === 'unexpected_error' ? `${stage}-${errorName || 'unknown'}-failed` : safe.code;
    process.stderr.write(`${JSON.stringify({ ok: false, code, message: 'Fixture setup did not finish. Check the Editor connection and retry only after verifying the store and namespace.' })}\n`);
    process.exitCode = 1;
  }
}

void main();
