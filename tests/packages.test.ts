import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:https';
import { execFileSync, spawn } from 'node:child_process';
import { chmod, mkdir, readFile, writeFile, mkdtemp, rm, stat, symlink } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { once } from 'node:events';
import { openPackage, call } from './package-harness.js';

test('exact artifacts launch outside repo, have independent identities and no embedded secrets/paths', async () => {
  const packages = await Promise.all([openPackage('editor'), openPackage('reader')]);
  try {
    for (const [index, p] of packages.entries()) {
      const role = index === 0 ? 'editor' : 'reader';
      assert.equal(p.client.getServerVersion()?.name, `redis-shared-memory-${role}`);
      assert.equal(p.client.getServerVersion()?.version, p.manifest.version);
      const names = (await p.client.listTools()).tools.map(t => t.name);
      assert.deepEqual(names, role === 'reader' ? ['reader_status', 'reader_search'] : ['editor_status', 'editor_search', 'editor_publish', 'editor_update']);
      assert.equal(p.manifest.role, role);
      assert.deepEqual(p.manifest.tools, names);
      assert.equal(p.manifest.credential_location, `~/.config/redis-shared-memory/${role}.env`);
      const runbook = await readFile(join(p.dir, 'RUNBOOK.md'), 'utf8');
      assert.match(runbook, new RegExp(`# ${role === 'reader' ? 'Reader' : 'Editor'} Runbook`));
      assert.ok(!runbook.includes('/Users/'));
      if (role === 'reader') {
        await assert.rejects(stat(join(p.dir, 'seed.sh')));
        await assert.rejects(stat(join(p.dir, 'bin/seed.cjs')));
        await assert.rejects(stat(join(p.dir, 'bin/redis-memory-seed')));
      } else {
        assert.equal((await stat(join(p.dir, 'seed.sh'))).mode & 0o111, 0o111);
        await stat(join(p.dir, 'bin/seed.cjs'));
        await stat(join(p.dir, 'bin/redis-memory-seed'));
      }
      assert.equal((await call(p.client, `${role}_status`)).data.code, 'configuration_missing');
      execFileSync('/usr/bin/shasum', ['-a', '256', '-c', 'FILES.sha256'], { cwd: p.dir, stdio: 'ignore' });
      const files = execFileSync('/usr/bin/find', [p.dir, '-type', 'f'], { encoding: 'utf8' }).trim().split('\n');
      for (const file of files) {
        const text = await readFile(file, 'utf8');
        assert.ok(!/\/Users\/|\/opt\/homebrew\/|BEGIN (?:RSA )?PRIVATE KEY/.test(text), `Nonportable or secret content: ${file}`);
        assert.ok(!text.includes('test-secret-never-display'));
      }
      assert.equal(p.stderr(), '');
    }
    assert.notEqual(packages[0].manifest.name, packages[1].manifest.name);
    const builds = await Promise.all(packages.map(p => readFile(join(p.dir, 'BUILD.json'), 'utf8').then(JSON.parse)));
    assert.equal(builds[0].source_sha256, builds[1].source_sha256);
  } finally { await Promise.all(packages.map(p => p.close())); }
});

test('packaged SDKs perform HTTPS editor-to-reader operations and enforce reader/scope errors', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ram-https-test-'));
  await writeFile(join(dir, 'openssl.cnf'), '[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n');
  execFileSync('/usr/bin/openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-config', join(dir, 'openssl.cnf'), '-keyout', join(dir, 'key.pem'), '-out', join(dir, 'cert.pem')], { stdio: 'ignore' });
  const records = new Map<string, Record<string, unknown>>();
  let writes = 0;
  let indexingPending = false;
  const service = createServer({ key: await readFile(join(dir, 'key.pem')), cert: await readFile(join(dir, 'cert.pem')) }, async (req, res) => {
    const send = (code: number, data: unknown) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); };
    if (req.headers.authorization !== 'Bearer qa-test-only-key') return send(401, { title: 'Invalid key', status: 401 });
    let raw = ''; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : {};
    const base = '/v1/stores/qa-store/long-term-memory';
    if (req.url === `${base}/search`) {
      if (indexingPending) return send(424, { title: 'Search dependency unavailable', status: 424, type: '/errors/resource-unavailable' });
      return send(200, { items: [...records.values()].filter(r => r.namespace === body.filter?.namespace?.eq) });
    }
    if (req.url === base && req.method === 'POST') {
      writes++;
      for (const r of body.memories) records.set(r.id, { ...r, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() });
      return send(201, { created: body.memories.map((r: { id: string }) => r.id), errors: [] });
    }
    const id = req.url?.slice(base.length + 1) ?? '';
    if (!records.has(id)) return send(404, { title: 'Missing', status: 404 });
    if (req.method === 'PATCH') {
      writes++; records.set(id, { ...records.get(id), ...body, updatedAt: new Date().toISOString() });
    }
    return send(200, records.get(id));
  });
  service.listen(0, '127.0.0.1'); await once(service, 'listening');
  const env = { RAM_ENDPOINT: `https://localhost:${(service.address() as { port: number }).port}`,
    RAM_STORE_ID: 'qa-store', RAM_NAMESPACE: 'northstar-pilot-qa', RAM_PARTICIPANT: 'editor-user',
    RAM_API_KEY: 'qa-test-only-key', NODE_EXTRA_CA_CERTS: join(dir, 'cert.pem'), AGENT_MEMORY_DEBUG: 'true' };
  const packages: Awaited<ReturnType<typeof openPackage>>[] = [];
  try {
    const editor = await openPackage('editor', env); packages.push(editor);
    const reader = await openPackage('reader', { ...env, RAM_PARTICIPANT: 'different-reader' }); packages.push(reader);
    assert.equal((await call(reader.client, 'reader_status')).data.connection, 'verified');
    assert.deepEqual((await call(reader.client, 'reader_search', { query: 'pilot' })).data.memories, []);
    const created = (await call(editor.client, 'editor_publish', { fact: 'QA pilot in Singapore' })).data;
    assert.equal(created.outcome, 'saved_and_searchable');
    const id = created.memory.memory_id;
    assert.equal((await call(reader.client, 'reader_search', { query: 'pilot' })).data.memories[0].memory_id, id);
    const updated = (await call(editor.client, 'editor_update', { memory_id: id, fact: 'QA pilot in Tokyo' })).data;
    assert.equal(updated.outcome, 'saved_and_searchable');
    assert.equal((await call(reader.client, 'reader_search', { query: 'region' })).data.memories[0].fact, 'QA pilot in Tokyo');

    const installRoot = await mkdtemp(join(tmpdir(), 'ram-install-test-'));
    try {
      const fakeBin = join(installRoot, 'bin');
      const fakeHome = join(installRoot, 'home');
      await mkdir(fakeBin, { recursive: true });
      await mkdir(fakeHome, { recursive: true });
      await symlink(process.execPath, join(fakeBin, 'node'));
      const fakeClaude = join(fakeBin, 'claude');
      await writeFile(fakeClaude, `#!/bin/bash
if [[ "\${1:-}" = '--version' ]]; then printf '2.1.267 (Claude Code)\\n'; exit 0; fi
: > "$CLAUDE_CAPTURE"
previous=''
for argument in "$@"; do
  printf '%s\\n' "$argument" >> "$CLAUDE_CAPTURE"
  if [[ "$previous" = '--mcp-config' ]]; then /bin/cp "$argument" "$CLAUDE_MCP_CAPTURE"; fi
  previous="$argument"
done
`, { mode: 0o755 });
      await chmod(fakeClaude, 0o755);
      const installEnv = {
        ...process.env,
        HOME: fakeHome,
        PATH: `${fakeBin}:/usr/bin:/bin`,
        NODE_EXTRA_CA_CERTS: join(dir, 'cert.pem'),
      };
      indexingPending = true;
      const standaloneSeed = await new Promise<string>((resolve, reject) => {
        const child = spawn('/bin/bash', [join(editor.dir, 'seed.sh'), 'qa'], { env: installEnv });
        let stdout = '', stderr = '';
        child.stdout.on('data', chunk => { stdout += chunk.toString(); });
        child.stderr.on('data', chunk => { stderr += chunk.toString(); });
        child.once('error', reject);
        child.once('exit', code => code === 0 ? resolve(stdout) : reject(new Error(`${stderr}\n${stdout}`)));
        child.stdin.end(`${env.RAM_ENDPOINT}\nqa-store\nqa-test-only-key\n`);
      });
      const standaloneResult = JSON.parse(standaloneSeed.slice(standaloneSeed.indexOf('{')));
      assert.equal(standaloneResult.ok, true);
      assert.equal(standaloneResult.verified_ids.length, 6);
      assert.equal(standaloneResult.search_pending_ids.length, 6);
      assert.match(standaloneResult.next_step, /do not seed again/i);
      indexingPending = false;
      const install = (p: Awaited<ReturnType<typeof openPackage>>, role: 'reader' | 'editor') => {
        const participant = role === 'reader' ? 'teammate' : 'hillary';
        return new Promise<string>((resolve, reject) => {
          const child = spawn('/bin/bash', [join(p.dir, 'install.sh')], { env: installEnv });
          let stdout = '', stderr = '';
          child.stdout.on('data', chunk => { stdout += chunk.toString(); });
          child.stderr.on('data', chunk => { stderr += chunk.toString(); });
          child.once('error', reject);
          child.once('exit', code => code === 0 ? resolve(stdout) : reject(new Error(`${stderr}\n${stdout}`)));
          child.stdin.end(`${env.RAM_ENDPOINT}\nqa-store\nnorthstar-pilot-qa\n${participant}\nqa-test-only-key\n`);
        });
      };
      assert.match(await install(reader, 'reader'), /Installed and verified/);
      assert.match(await install(editor, 'editor'), /Installed and verified/);
      indexingPending = true;
      assert.match(await install(reader, 'reader'), /do not reseed/i);
      indexingPending = false;
      assert.equal((await stat(join(fakeHome, '.config/redis-shared-memory/reader.env'))).mode & 0o777, 0o600);
      assert.equal((await stat(join(fakeHome, '.config/redis-shared-memory/editor.env'))).mode & 0o777, 0o600);

      const desktopDir = join(fakeHome, 'Library/Application Support/Claude');
      const desktopConfig = join(desktopDir, 'claude_desktop_config.json');
      await mkdir(desktopDir, { recursive: true });
      await writeFile(desktopConfig, JSON.stringify({ mcpServers: {
        existing: { command: '/usr/bin/true', args: [] },
      } }), { mode: 0o644 });
      for (const role of ['reader', 'editor'] as const) {
        execFileSync(process.execPath, [
          join(fakeHome, `.local/share/redis-shared-memory/${role}/current/bin/configure-desktop.cjs`),
          'add', role,
        ], { env: installEnv });
      }
      const desktopText = await readFile(desktopConfig, 'utf8');
      const desktop = JSON.parse(desktopText);
      assert.equal(desktop.mcpServers.existing.command, '/usr/bin/true');
      for (const role of ['reader', 'editor'] as const) {
        assert.equal(desktop.mcpServers[`redis-shared-memory-${role}`].command,
          join(fakeHome, `.local/share/redis-shared-memory/${role}/current/bin/run-server.sh`));
      }
      assert.equal(desktopText.includes('qa-test-only-key'), false);
      assert.equal((await stat(desktopConfig)).mode & 0o777, 0o600);

      const seedOutput = await new Promise<string>((resolve, reject) => {
        const child = spawn(join(fakeHome, '.local/bin/redis-memory-seed'), ['reset', 'qa'], { env: installEnv });
        let stdout = '', stderr = '';
        child.stdout.on('data', chunk => { stdout += chunk.toString(); });
        child.stderr.on('data', chunk => { stderr += chunk.toString(); });
        child.once('error', reject);
        child.once('exit', code => code === 0 ? resolve(stdout) : reject(new Error(`${stderr}\n${stdout}`)));
      });
      const seedResult = JSON.parse(seedOutput);
      assert.equal(seedResult.namespace, 'northstar-pilot-qa');
      assert.equal(seedResult.verified_ids.length, 6);
      assert.deepEqual(seedResult.search_pending_ids, []);
      assert.ok([...records.values()].some(record => record.text === "Northstar Retail's pilot must deploy in the Singapore region."));

      for (const role of ['reader', 'editor'] as const) {
        const capture = join(installRoot, `${role}-args.txt`);
        const mcpCapture = join(installRoot, `${role}-mcp.json`);
        execFileSync(join(fakeHome, `.local/bin/redis-memory-${role}`), [], {
          env: { ...installEnv, CLAUDE_CAPTURE: capture, CLAUDE_MCP_CAPTURE: mcpCapture },
        });
        const args = (await readFile(capture, 'utf8')).split('\n');
        assert.ok(args.includes('--restricted'));
        assert.ok(args.includes('--strict-mcp-config'));
        assert.ok(args.includes('--tools'));
        const toolsIndex = args.indexOf('--tools');
        const allowedTools = args[toolsIndex + 1];
        assert.ok(allowedTools.includes(`mcp__redis-shared-memory-${role}__${role}_status`));
        assert.ok(allowedTools.includes(`mcp__redis-shared-memory-${role}__${role}_search`));
        assert.equal(allowedTools.includes('Bash'), false);
        assert.equal(allowedTools.includes('Read'), false);
        assert.equal(allowedTools.includes('WebFetch'), false);
        assert.equal(allowedTools.includes('publish'), role === 'editor');
        assert.equal(allowedTools.includes('update'), role === 'editor');
        const permissionIndex = args.indexOf('--permission-mode');
        assert.equal(args[permissionIndex + 1], role === 'reader' ? 'auto' : 'manual');
        const mcp = await readFile(mcpCapture, 'utf8');
        assert.ok(mcp.includes(`redis-shared-memory-${role}`));
        assert.ok(mcp.includes('run-server.sh'));
        assert.ok(!mcp.includes('qa-test-only-key'));
      }

      const editorUninstall = join(fakeHome, '.local/share/redis-shared-memory/editor/current/uninstall.sh');
      execFileSync('/bin/bash', [editorUninstall], { env: installEnv });
      await stat(join(fakeHome, '.local/bin/redis-memory-reader'));
      await assert.rejects(stat(join(fakeHome, '.local/bin/redis-memory-seed')));
      assert.equal(JSON.parse(await readFile(desktopConfig, 'utf8')).mcpServers['redis-shared-memory-editor'], undefined);
      assert.ok(JSON.parse(await readFile(desktopConfig, 'utf8')).mcpServers['redis-shared-memory-reader']);
      assert.equal(records.get(id)?.text, 'QA pilot in Tokyo');
      const readerUninstall = join(fakeHome, '.local/share//redis-shared-memory/reader/current/uninstall.sh');
      execFileSync('/bin/bash', [readerUninstall], { env: installEnv });
      await assert.rejects(stat(join(fakeHome, '.config/redis-shared-memory/reader.env')));
      const finalDesktop = JSON.parse(await readFile(desktopConfig, 'utf8'));
      assert.equal(finalDesktop.mcpServers['redis-shared-memory-reader'], undefined);
      assert.equal(finalDesktop.mcpServers.existing.command, '/usr/bin/true');
    } finally {
      await rm(installRoot, { recursive: true, force: true });
    }

    const before = writes;
    assert.equal((await reader.client.callTool({ name: 'editor_publish', arguments: { fact: 'Denied' } })).isError, true);
    assert.equal((await reader.client.callTool({ name: 'reader_update', arguments: { memory_id: id, fact: 'Denied' } })).isError, true);
    records.set('outside', { ...records.get(id), id: 'outside', namespace: 'other-project' });
    assert.equal((await call(editor.client, 'editor_update', { memory_id: 'outside', fact: 'Denied' })).data.code, 'scope_denied');
    assert.equal(writes, before);
    const invalid = await openPackage('reader', { ...env, RAM_API_KEY: 'invalid-test-only-secret' }); packages.push(invalid);
    const invalidResult = (await call(invalid.client, 'reader_status')).data;
    assert.equal(invalidResult.code, 'authentication_failed');
    assert.ok(!JSON.stringify(invalidResult).includes('invalid-test-only-secret'));
    for (const p of packages) assert.equal(p.stderr(), '');
    service.closeAllConnections(); await new Promise<void>(resolve => service.close(() => resolve()));
    assert.equal((await call(reader.client, 'reader_status')).data.code, 'network_error');
  } finally {
    await Promise.all(packages.map(p => p.close()));
    if (service.listening) { service.closeAllConnections(); await new Promise<void>(resolve => service.close(() => resolve())); }
    await rm(dir, { recursive: true, force: true });
  }
});
