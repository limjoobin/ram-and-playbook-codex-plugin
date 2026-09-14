"""Run the exact-package live RAM test; collect the credential with terminal echo disabled."""
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
env = os.environ.copy()
for key, label in [("RAM_ENDPOINT", "RAM HTTPS endpoint"), ("RAM_STORE_ID", "RAM store ID")]:
    if not env.get(key):
        env[key] = input(label + ": ").strip()
env["RAM_NAMESPACE"] = "northstar-pilot-qa"
env.setdefault("RAM_PARTICIPANT", "hillary")
if not env.get("RAM_API_KEY"):
    env["RAM_API_KEY"] = getpass.getpass("RAM API key (hidden; used only for this process): ")
node = shutil.which("node")
if not node:
    sys.exit("Node is required for development and for the packaged Claude Code integration.")
sys.exit(subprocess.call([node, "--import", "tsx", "scripts/live-test.ts"], cwd=root, env=env))
