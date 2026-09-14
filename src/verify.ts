import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const [role, command] = process.argv.slice(2);
if (!['reader', 'editor'].includes(role) || !command) {
  process.stderr.write('Usage: verify.cjs <reader|editor> <server-command>\n');
  process.exit(2);
}

const childEnv: Record<string, string> = {};
for (const name of ['HOME', 'PATH', 'TMPDIR', 'NODE_EXTRA_CA_CERTS', 'REDIS_SHARED_MEMORY_CONFIG']) {
  const value = process.env[name];
  if (value) childEnv[name] = value;
}

async function main() {
  let stderr = '';
  const transport = new StdioClientTransport({ command, env: childEnv, stderr: 'pipe' });
  transport.stderr?.on('data', chunk => { stderr += chunk.toString(); });
  const client = new Client({ name: 'redis-shared-memory-installer', version: '1' });

  try {
    await client.connect(transport);
    const expected = role === 'reader'
      ? ['reader_status', 'reader_search']
      : ['editor_status', 'editor_search', 'editor_publish', 'editor_update'];
    const actual = (await client.listTools()).tools.map(tool => tool.name);
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('role_tool_mismatch');
    const response = await client.callTool({ name: `${role}_status`, arguments: {} }, undefined, { timeout: 30_000 });
    const block = (response.content as Array<{ type: string; text?: string }>).find(item => item.type === 'text');
    const status = block?.text ? JSON.parse(block.text) as Record<string, unknown> : response.structuredContent as Record<string, unknown>;
    const code = typeof status?.code === 'string' ? status.code : 'verification_failed';
    if (code === 'dependency_unavailable') {
      const dependency = status?.dependency_type === 'database_out_of_memory' ? 'database capacity' : 'the search resource';
      process.stdout.write(`Verified ${role} MCP configuration. RAM reports ${dependency} unavailable; installation can continue. If the store is empty, seed it once. If Redis Insight already shows the memories, do not reseed; wait and retry search or check the Agent Memory service.\n`);
    } else if (response.isError || status?.ok !== true || status?.connection !== 'verified') {
      const message = typeof status?.message === 'string' ? status.message : 'RAM did not verify the connection.';
      process.stderr.write(`Connection check failed (${code}): ${message}\n`);
      process.exitCode = 1;
    } else {
      process.stdout.write(`Verified ${role} connection to namespace ${String(status.namespace)}.\n`);
    }
  } catch {
    process.stderr.write(stderr.trim() ? 'The local MCP server did not pass its startup check.\n' : 'The local MCP verification could not complete.\n');
    process.exitCode = 1;
  } finally {
    await client.close().catch(() => undefined);
  }
}

void main();
