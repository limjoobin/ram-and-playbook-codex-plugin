"""Offline tests for the private redis-iris runtime launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"


class LauncherTests(unittest.TestCase):
    def test_requirements_are_exact_pins_including_the_sdk(self):
        lines = [
            line.strip()
            for line in (SERVER_ROOT / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertTrue(lines)
        self.assertTrue(all("==" in line and not line.startswith("-") for line in lines))
        names = {line.split("==")[0].lower() for line in lines}
        self.assertTrue({"redis-iris", "redis-agent-memory", "redis-agent-playbook"} <= names)

    @unittest.skipIf(os.name == "nt", "the launcher targets macOS and Linux")
    def test_install_check_and_exec_use_a_private_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "server"
            server.mkdir()
            shutil.copy(SERVER_ROOT / "launch.py", server / "launch.py")
            # No pins: exercises venv creation and the ready marker without a network.
            (server / "requirements.txt").write_text("# no packages\n", encoding="utf-8")
            (server / "main.py").write_text(
                "import json, sys\n"
                "print(json.dumps({'executable': sys.executable, 'isolated': sys.flags.isolated, 'argv': sys.argv[1:]}))\n",
                encoding="utf-8",
            )
            data = Path(directory) / "plugin-data"
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": directory, "PLUGIN_DATA": str(data)}
            launcher = [sys.executable, "-I", str(server / "launch.py")]

            check = subprocess.run([*launcher, "--check"], env=env, capture_output=True, timeout=30)
            self.assertEqual(check.returncode, 1)

            install = subprocess.run(
                [*launcher, "--install"], env=env, capture_output=True, text=True, timeout=180
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(install.stdout, "")  # stdout stays reserved for MCP
            runtimes = list((data / "runtime").iterdir())
            venvs = [path for path in runtimes if path.is_dir()]
            self.assertEqual(len(venvs), 1)
            self.assertTrue((venvs[0] / ".ready").is_file())
            self.assertTrue(venvs[0].name.startswith(f"py{sys.version_info.major}{sys.version_info.minor}-"))

            check = subprocess.run([*launcher, "--check"], env=env, capture_output=True, timeout=30)
            self.assertEqual(check.returncode, 0)

            run = subprocess.run(
                [*launcher, "extra-arg"], env=env, capture_output=True, text=True, timeout=60
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            started = json.loads(run.stdout)
            self.assertTrue(Path(started["executable"]).is_relative_to(venvs[0]))
            self.assertEqual(started["isolated"], 1)
            self.assertEqual(started["argv"], ["extra-arg"])

            # A changed pin set selects a new runtime instead of reusing the old one.
            (server / "requirements.txt").write_text("# changed\n", encoding="utf-8")
            check = subprocess.run([*launcher, "--check"], env=env, capture_output=True, timeout=30)
            self.assertEqual(check.returncode, 1)


if __name__ == "__main__":
    unittest.main()
