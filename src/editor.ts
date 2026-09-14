import { start } from './server.js';
start('editor').catch(() => { process.stderr.write('Shared Memory Editor could not start. Check the local installation.\n'); process.exitCode = 1; });
