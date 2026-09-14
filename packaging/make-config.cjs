'use strict';
const fs = require('node:fs');

const [output, role, command] = process.argv.slice(2);
if (!output || !['reader', 'editor'].includes(role) || !command) {
  process.stderr.write('Could not create the role-scoped MCP configuration.\n');
  process.exit(2);
}
const name = `redis-shared-memory-${role}`;
const config = { mcpServers: { [name]: { type: 'stdio', command, args: [] } } };
fs.writeFileSync(output, `${JSON.stringify(config, null, 2)}\n`, { encoding: 'utf8', flag: 'wx', mode: 0o600 });
