'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const [action, role] = process.argv.slice(2);
if (!['add', 'remove'].includes(action) || !['reader', 'editor'].includes(role)) {
  process.stderr.write('Usage: configure-desktop.cjs <add|remove> <reader|editor>\n');
  process.exit(2);
}

const home = os.homedir();
const configDir = path.join(home, 'Library/Application Support/Claude');
const configPath = path.join(configDir, 'claude_desktop_config.json');
const name = `redis-shared-memory-${role}`;
const runner = path.join(home, `.local/share/redis-shared-memory/${role}/current/bin/run-server.sh`);

function fail(message) {
  process.stderr.write(`Claude Desktop configuration: ${message}\n`);
  process.exit(1);
}

function readConfig() {
  if (!fs.existsSync(configPath)) return {};
  const metadata = fs.lstatSync(configPath);
  if (!metadata.isFile() || metadata.isSymbolicLink()) fail('the configuration file is not a safe regular file.');
  if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) {
    fail('the configuration file is not owned by the current user.');
  }
  try {
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    if (!config || Array.isArray(config) || typeof config !== 'object') throw new Error();
    return config;
  } catch {
    fail('the existing configuration is not a valid JSON object; it was not changed.');
  }
}

function writeConfig(config) {
  fs.mkdirSync(configDir, { recursive: true });
  if (fs.existsSync(configPath)) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const backup = `${configPath}.backup-${timestamp}`;
    fs.copyFileSync(configPath, backup, fs.constants.COPYFILE_EXCL);
    fs.chmodSync(backup, 0o600);
    process.stdout.write(`Backed up Claude Desktop configuration to ${backup}\n`);
  }
  const temporary = `${configPath}.tmp-${process.pid}`;
  try {
    fs.writeFileSync(temporary, `${JSON.stringify(config, null, 2)}\n`, {
      encoding: 'utf8', flag: 'wx', mode: 0o600,
    });
    fs.renameSync(temporary, configPath);
    fs.chmodSync(configPath, 0o600);
  } finally {
    if (fs.existsSync(temporary)) fs.rmSync(temporary);
  }
}

const config = readConfig();
if (config.mcpServers === undefined) config.mcpServers = {};
if (!config.mcpServers || Array.isArray(config.mcpServers) || typeof config.mcpServers !== 'object') {
  fail('the existing mcpServers value is not a JSON object; it was not changed.');
}

if (action === 'add') {
  if (!fs.existsSync(runner)) fail(`the installed ${role} server was not found; run the role installer first.`);
  const existing = config.mcpServers[name];
  if (existing !== undefined && (!existing || existing.command !== runner)) {
    fail(`refusing to replace an unrelated ${name} entry.`);
  }
  const nodeDirectory = path.dirname(process.execPath);
  const searchPath = [...new Set([nodeDirectory, '/usr/local/bin', '/usr/bin', '/bin'])].join(':');
  config.mcpServers[name] = { command: runner, args: [], env: { PATH: searchPath } };
  writeConfig(config);
  process.stdout.write(`Added ${name} to Claude Desktop.\n`);
} else {
  const existing = config.mcpServers[name];
  if (existing === undefined) process.exit(0);
  if (!existing || existing.command !== runner) {
    fail(`refusing to remove an unrelated ${name} entry.`);
  }
  delete config.mcpServers[name];
  writeConfig(config);
  process.stdout.write(`Removed ${name} from Claude Desktop.\n`);
}
