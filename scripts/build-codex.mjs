import { build } from 'esbuild';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const pluginRoot = resolve(root, 'plugins', 'redis-shared-memory-editor');
const serverRoot = resolve(pluginRoot, 'server');
const pkg = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'));
const manifest = JSON.parse(await readFile(resolve(pluginRoot, 'plugin.json'), 'utf8'));

if (manifest.version !== pkg.version) {
  throw new Error(`Plugin version ${manifest.version} does not match package version ${pkg.version}.`);
}

await mkdir(serverRoot, { recursive: true });
await build({
  entryPoints: [resolve(root, 'src', 'codex-editor.ts')],
  outfile: resolve(serverRoot, 'index.cjs'),
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  minify: true,
  sourcemap: false,
  legalComments: 'external',
});

const paths = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
  cwd: root,
  encoding: 'utf8',
}).trim().split('\n').filter(path => path
  && !path.startsWith('dist/')
  && !path.startsWith('.build/')
  && path !== 'plugins/redis-shared-memory-editor/server/index.cjs'
  && path !== 'plugins/redis-shared-memory-editor/BUILD.json').sort();
const digest = createHash('sha256');
for (const path of paths) {
  digest.update(path);
  digest.update(await readFile(resolve(root, path)));
}
await writeFile(resolve(pluginRoot, 'BUILD.json'), `${JSON.stringify({
  version: pkg.version,
  source_sha256: digest.digest('hex'),
  entry_point: 'server/index.cjs',
}, null, 2)}\n`);

process.stdout.write(`Built Codex desktop plugin ${manifest.name} ${manifest.version}.\n`);
