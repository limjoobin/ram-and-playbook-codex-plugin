from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("setup_demo", ROOT / "scripts" / "setup_demo.py")
setup_demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup_demo)
PLUGIN = "redis-shared-memory-editor@redis-field-engineering"


class PluginScopeTests(unittest.TestCase):
    def _run(self, text: str) -> tuple[str, dict, int]:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(text)
            os.chmod(config, 0o600)
            outcome = setup_demo.disable_account_wide(config)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            backups = len(list(Path(directory).glob("config.toml.backup-*")))
            return outcome, tomllib.loads(config.read_text()), backups

    def test_turns_the_plugin_off_and_leaves_other_settings(self):
        outcome, data, backups = self._run(
            f'model = "x"\n\n[plugins."{PLUGIN}"]\nenabled = true\n\n[plugins."other@m"]\nenabled = true\n'
        )
        self.assertEqual((outcome, backups), ("changed", 1))
        self.assertEqual(data["plugins"][PLUGIN], {"enabled": False})
        self.assertEqual(data["plugins"]["other@m"], {"enabled": True})
        self.assertEqual(data["model"], "x")

    def test_adds_the_setting_when_missing_and_is_idempotent(self):
        outcome, data, _ = self._run('[plugins."other@m"]\nenabled = true\n')
        self.assertEqual(outcome, "changed")
        self.assertEqual(data["plugins"][PLUGIN], {"enabled": False})
        outcome, _, backups = self._run(f'[plugins."{PLUGIN}"]\nenabled = false\n')
        self.assertEqual((outcome, backups), ("unchanged", 0))

    def test_missing_codex_config_is_left_alone(self):
        self.assertEqual(setup_demo.disable_account_wide(Path("/nonexistent/config.toml")), "missing")

    def test_the_repository_enables_the_plugin_for_this_project(self):
        data = tomllib.loads((ROOT / ".codex" / "config.toml").read_text())
        self.assertEqual(data["plugins"][PLUGIN], {"enabled": True})


if __name__ == "__main__":
    unittest.main()
