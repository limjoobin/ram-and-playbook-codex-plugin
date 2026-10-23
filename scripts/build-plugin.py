"""Verify the source-only Python plugin and refresh its source digest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "redis-shared-memory-editor"
SERVER_ROOT = PLUGIN_ROOT / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.config import VERSION  # noqa: E402


manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
if manifest["version"] != VERSION:
    raise SystemExit(f"Plugin version {manifest['version']} does not match runtime version {VERSION}.")

paths = sorted(
    path
    for path in subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if path
    and not path.startswith("dist/")
    and not path.startswith(".build/")
    and path != "plugins/redis-shared-memory-editor/BUILD.json"
)
digest = hashlib.sha256()
for relative in paths:
    digest.update(relative.encode("utf-8"))
    digest.update((ROOT / relative).read_bytes())

(PLUGIN_ROOT / "BUILD.json").write_text(
    json.dumps(
        {
            "version": VERSION,
            "source_sha256": digest.hexdigest(),
            "entry_point": "server/main.py",
            "runtime": "python>=3.10",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"Verified Python desktop plugin {manifest['name']} {VERSION}.")
