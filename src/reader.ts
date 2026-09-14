import { start } from './server.js';
start('reader').catch(() => { process.stderr.write('Shared Memory Reader could not start. Check the local installation.\n'); process.exitCode = 1; });
