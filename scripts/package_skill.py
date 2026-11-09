#!/usr/bin/env python3
"""Package the agenda Skill as the Agent Skills ZIP the Redis Cloud console uploads.

Standard library only. Verifies every file against the checked-in Playbook
manifest digests, writes a deterministic ZIP to dist/, and prints the optional
upload settings (alias, retrieval intents, filter attributes) to paste.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "context-models" / "management-agenda" / "v1" / "playbook"
DIST = ROOT / "dist"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def main() -> int:
    manifest = json.loads((PLAYBOOK / "manifest.json").read_text(encoding="utf-8"))
    key = manifest["entryKey"]
    files: list[tuple[str, bytes]] = []
    for resource in manifest["resources"]:
        data = (PLAYBOOK / resource["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != resource["sha256"]:
            print(f"Digest mismatch for {resource['path']}; the Skill does not match its manifest.", file=sys.stderr)
            return 1
        files.append((resource["path"], data))

    DIST.mkdir(exist_ok=True)
    target = DIST / f"{key}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files):
            info = zipfile.ZipInfo(f"{key}/{path}", date_time=FIXED_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)

    print(f"Skill ZIP: {target.relative_to(ROOT)} (version {manifest['version']} contents, {len(files)} files)")
    print()
    print("Paste these into Upload Skill > Optional settings:")
    print(f"  Alias: {key}")
    print("  Retrieval intents:")
    for intent in manifest["intents"]:
        print(f"    {intent}")
    print(f"  Filter attributes: {json.dumps(manifest['attributes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
