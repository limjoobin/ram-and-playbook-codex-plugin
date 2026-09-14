# Reader quick start

1. Install Claude Code CLI and Node.js 20+ if they are not already installed.
2. Receive `redis-shared-memory-reader-0.1.1.zip` and `SHA256SUMS` from Hillary;
   receive the API key separately through an approved secret-sharing channel.
3. Verify the Reader line in `SHA256SUMS`, unzip it, and run `./install.sh`.
4. Enter the same RAM endpoint, store ID, and `northstar-pilot-demo` namespace
   as Hillary. Use `demo-reader` as the participant ID.
5. From VS Code's terminal or any terminal, run:

   ```sh
   ~/.local/bin/redis-memory-reader
   ```

6. Ask Claude to run `reader_status`, then ask it to retrieve Northstar Retail's
   pilot requirements and cite the returned memory IDs.

The Reader package exposes no write tool. Its API key remains a writable shared
credential outside this tool-level demo boundary.
