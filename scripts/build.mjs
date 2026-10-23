import { build } from 'esbuild';
import { chmod, cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { relative, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const pkg = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'));
const dist = resolve(root, 'dist', 'claude-code');
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });

const sources = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
  cwd: root, encoding: 'utf8',
}).trim().split('\n').filter(path => path
  && !path.startsWith('reports/')
  && path !== 'plugins/redis-shared-memory-editor/server/index.cjs'
  && path !== 'plugins/redis-shared-memory-editor/BUILD.json').sort();
const sourceHash = createHash('sha256');
for (const path of sources) {
  sourceHash.update(path);
  sourceHash.update(await readFile(resolve(root, path)));
}
const sourceDigest = sourceHash.digest('hex');

async function walk(directory) {
  const output = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) output.push(...await walk(path));
    else output.push(path);
  }
  return output.sort();
}

async function renderTemplate(source, destination, replacements) {
  let contents = await readFile(source, 'utf8');
  for (const [token, value] of Object.entries(replacements)) contents = contents.replaceAll(`@@${token}@@`, value);
  await writeFile(destination, contents);
  await chmod(destination, 0o755);
}

const artifacts = [];
for (const role of ['editor', 'reader']) {
  const name = `redis-shared-memory-${role}`;
  const title = role === 'editor' ? 'Editor' : 'Reader';
  const stage = resolve(root, '.build', 'claude-code', `${name}-${pkg.version}`);
  await rm(stage, { recursive: true, force: true });
  await mkdir(resolve(stage, 'server'), { recursive: true });
  await mkdir(resolve(stage, 'bin'), { recursive: true });
  await mkdir(resolve(stage, 'demo-workspace'), { recursive: true });

  const serverBuild = await build({
    entryPoints: [resolve(root, `src/${role}.ts`)], outfile: resolve(stage, 'server/index.cjs'),
    bundle: true, platform: 'node', format: 'cjs', target: 'node20', minify: true,
    sourcemap: false, legalComments: 'external', metafile: true,
  });
  const verifyBuild = await build({
    entryPoints: [resolve(root, 'src/verify.ts')], outfile: resolve(stage, 'bin/verify.cjs'),
    bundle: true, platform: 'node', format: 'cjs', target: 'node20', minify: true,
    sourcemap: false, legalComments: 'external', metafile: true,
  });
  let seedBuild;
  if (role === 'editor') {
    seedBuild = await build({
      entryPoints: [resolve(root, 'src/seed-cli.ts')], outfile: resolve(stage, 'bin/seed.cjs'),
      bundle: true, platform: 'node', format: 'cjs', target: 'node20', minify: true,
      sourcemap: false, legalComments: 'external', metafile: true,
    });
  }

  const replacements = { ROLE: role, TITLE: title, VERSION: pkg.version };
  await renderTemplate(resolve(root, 'packaging/install.sh'), resolve(stage, 'install.sh'), replacements);
  await renderTemplate(resolve(root, 'packaging/uninstall.sh'), resolve(stage, 'uninstall.sh'), replacements);
  await renderTemplate(resolve(root, 'packaging/run-server.sh'), resolve(stage, 'bin/run-server.sh'), replacements);
  await renderTemplate(resolve(root, 'packaging/launcher.sh'), resolve(stage, 'bin', `redis-memory-${role}`), replacements);
  if (role === 'editor') {
    await renderTemplate(resolve(root, 'packaging/seed-demo.sh'), resolve(stage, 'bin/redis-memory-seed'), replacements);
    await renderTemplate(resolve(root, 'packaging/seed-standalone.sh'), resolve(stage, 'seed.sh'), replacements);
  }
  await cp(resolve(root, 'packaging/make-config.cjs'), resolve(stage, 'bin/make-config.cjs'));
  await cp(resolve(root, 'packaging/configure-desktop.cjs'), resolve(stage, 'bin/configure-desktop.cjs'));
  await cp(resolve(root, 'docs', `${role}-project-instructions.md`), resolve(stage, 'demo-workspace/CLAUDE.md'));
  await cp(resolve(root, 'docs', `${role}-guide.md`), resolve(stage, 'README.md'));
  await cp(resolve(root, 'docs', `${role}-package-runbook.md`), resolve(stage, 'RUNBOOK.md'));

  const toolNames = role === 'reader'
    ? ['reader_status', 'reader_search']
    : ['editor_status', 'editor_search', 'editor_publish', 'editor_update'];
  const manifest = {
    format_version: 1,
    name,
    display_name: `Redis Shared Memory — ${title}`,
    version: pkg.version,
    role,
    platform: 'darwin',
    node: '>=20',
    server: { transport: 'stdio', entry_point: 'server/index.cjs' },
    tools: toolNames,
    ...(role === 'editor' ? { utilities: ['seed.sh', 'redis-memory-seed'] } : {}),
    credential_location: `~/.config/redis-shared-memory/${role}.env`,
    ...(role === 'reader' ? { read_only_boundary: 'MCP tools only; the shared API credential may permit direct writes.' } : {}),
  };
  await writeFile(resolve(stage, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  await writeFile(resolve(stage, 'BUILD.json'), `${JSON.stringify({
    version: pkg.version, role, source_sha256: sourceDigest,
  }, null, 2)}\n`);

  const licenseInputs = { ...serverBuild.metafile.inputs, ...verifyBuild.metafile.inputs,
    ...(seedBuild?.metafile.inputs ?? {}) };
  const licenses = [];
  const seen = new Set();
  for (const input of Object.keys(licenseInputs)) {
    const match = input.match(/^(.*node_modules\/(?:@[^/]+\/)?[^/]+)\//);
    if (!match || seen.has(match[1])) continue;
    seen.add(match[1]);
    for (const filename of ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'license']) {
      try {
        licenses.push(`${match[1].replace(/^.*node_modules\//, '')}\n${await readFile(resolve(root, match[1], filename), 'utf8')}`);
        break;
      } catch {}
    }
  }
  await writeFile(resolve(stage, 'THIRD-PARTY-LICENSES.txt'), licenses.join('\n\n'));

  const files = (await walk(stage)).filter(path => !path.endsWith('/FILES.sha256'));
  const checksums = [];
  for (const path of files) {
    const digest = createHash('sha256').update(await readFile(path)).digest('hex');
    checksums.push(`${digest}  ${relative(stage, path)}`);
  }
  await writeFile(resolve(stage, 'FILES.sha256'), `${checksums.join('\n')}\n`);

  const artifact = resolve(dist, `${name}-${pkg.version}.zip`);
  await rm(artifact, { force: true });
  execFileSync('/usr/bin/zip', ['-q', '-r', artifact, '.'], { cwd: stage });
  artifacts.push({
    file: relative(dist, artifact),
    sha256: createHash('sha256').update(await readFile(artifact)).digest('hex'),
    role,
  });
}

await writeFile(resolve(dist, 'SHA256SUMS'), `${artifacts.map(a => `${a.sha256}  ${a.file}`).join('\n')}\n`);
await writeFile(resolve(dist, 'release.json'), `${JSON.stringify({
  version: pkg.version, source_sha256: sourceDigest, artifacts,
}, null, 2)}\n`);
process.stdout.write(`Built Claude Code Reader and Editor ZIPs from source digest ${sourceDigest}\n`);
