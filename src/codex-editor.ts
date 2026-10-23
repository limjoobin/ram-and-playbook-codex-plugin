import { homedir } from 'node:os';
import { join } from 'node:path';
import { loadCredentialFile } from './credential-file.js';
import { createRAMClient, SharedMemory } from './memory.js';
import { start } from './server.js';

const credentialFile = process.env.REDIS_SHARED_MEMORY_CONFIG?.trim()
  || join(homedir(), '.config', 'redis-shared-memory', 'editor.env');

void start('editor', () => {
  const config = loadCredentialFile(credentialFile);
  return new SharedMemory('editor', config, createRAMClient(config));
}).catch(() => {
  process.stderr.write('Redis Shared Memory for Codex could not start. Check the local plugin installation.\n');
  process.exitCode = 1;
});
