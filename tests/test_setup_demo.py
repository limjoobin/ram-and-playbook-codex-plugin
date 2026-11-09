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


    def test_trusts_the_folder_once(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[projects."/elsewhere"]\ntrust_level = "trusted"\n')
            folder = Path("/Users/someone/ram-and-playbook-codex-plugin")
            self.assertFalse(setup_demo.folder_trusted(config, folder))
            self.assertEqual(setup_demo.trust_folder(config, folder), "changed")
            self.assertTrue(setup_demo.folder_trusted(config, folder))
            self.assertEqual(setup_demo.trust_folder(config, folder), "unchanged")
            data = tomllib.loads(config.read_text())
            self.assertEqual(data["projects"]["/elsewhere"], {"trust_level": "trusted"})

    def test_a_table_spelled_differently_is_never_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            original = "[projects.'/Users/someone/project']\ntrust_level = \"untrusted\"\n"
            config.write_text(original)
            outcome = setup_demo.trust_folder(config, Path("/Users/someone/project"))
            self.assertEqual(outcome, "manual")
            self.assertEqual(config.read_text(), original)

    def test_invalid_toml_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text("[broken\n")
            self.assertEqual(setup_demo.disable_account_wide(config), "manual")
            self.assertEqual(config.read_text(), "[broken\n")


class Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class InstallTests(unittest.TestCase):
    def _fake(self, *, other_source: bool = False):
        calls: list[list[str]] = []
        state = {"other": other_source}

        def run(command, **kwargs):
            arguments = command[1:]
            calls.append(arguments)
            if arguments[:3] == ["plugin", "marketplace", "add"] and state["other"]:
                return Completed(1, stderr="Error: marketplace 'redis-field-engineering' is already added from a different source")
            if arguments[:3] == ["plugin", "marketplace", "remove"]:
                state["other"] = False
            return Completed()

        return run, calls

    def test_adds_the_list_and_installs(self):
        run, calls = self._fake()
        self.assertEqual(setup_demo.install_plugin("codex", run=run), (True, "installed"))
        self.assertEqual(calls, [
            ["plugin", "marketplace", "add", str(setup_demo.ROOT)],
            ["plugin", "add", PLUGIN],
        ])

    def test_switches_a_list_from_another_copy_only_when_asked(self):
        run, calls = self._fake(other_source=True)
        ok, _ = setup_demo.install_plugin("codex", run=run, ask_switch=lambda question: False)
        self.assertFalse(ok)
        self.assertNotIn(["plugin", "marketplace", "remove", "redis-field-engineering"], calls)

        run, calls = self._fake(other_source=True)
        ok, _ = setup_demo.install_plugin("codex", run=run, ask_switch=lambda question: True)
        self.assertTrue(ok)
        self.assertIn(["plugin", "marketplace", "remove", "redis-field-engineering"], calls)
        self.assertEqual(calls[-1], ["plugin", "add", PLUGIN])


if __name__ == "__main__":
    unittest.main()
