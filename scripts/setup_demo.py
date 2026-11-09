#!/usr/bin/env python3
"""Guided setup for the Redis Shared Memory + Playbook demo.

Run it from the repository root after creating the Agent Memory service and the
Playbook in the Redis Cloud console (see README.md):

    python3 scripts/setup_demo.py

It asks for the values the console shows, typing keys hidden, and then:

1. writes ~/.config/redis-shared-memory/editor.env (mode 0600), saving a copy of
   any existing file first;
2. checks that Agent Memory and the published Playbook Skill are reachable;
3. loads the demo documents through the MemoryETL extractor, moves them into
   the project's shared namespace, and builds the current state; and
4. installs (or updates) the plugin in ChatGPT, limits it to this folder,
   offers to trust the folder, and prepares the plugin's helper program.

Quit ChatGPT before running it. ``--remove`` uninstalls the plugin again.

It never prints a key. Run it again at any time: existing values are offered as
defaults and documents that are already loaded are skipped.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
VENV = ROOT / ".venv"
REQUIREMENTS = SERVER / "requirements.txt"
PLUGIN_ID = "redis-shared-memory-editor-redis-field-engineering"
DEMO_PARTICIPANTS = ("andrew", "craig", "david", "laura")


def say(message: str = "") -> None:
    print(message, flush=True)


def step(number: int, title: str) -> None:
    say()
    say(f"Step {number}: {title}")
    say("-" * (len(title) + 8))


# Environment -----------------------------------------------------------------


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_environment(argv: list[str]) -> None:
    """Create .venv with the pinned SDK once, then continue inside it."""

    if sys.version_info < (3, 11):
        say(f"Python 3.11 or newer is required; this is Python {sys.version.split()[0]}.")
        say("Install it from https://www.python.org/downloads/ and run this command again.")
        raise SystemExit(1)
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    python = venv_python()
    if not python.is_file():
        say("Preparing a private Python environment for setup (one time, about a minute)...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    try:
        subprocess.run(
            [str(python), "-c", "import redis_agent_memory, redis_agent_playbook"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        say("Installing the pinned redis-iris SDK...")
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-r", str(REQUIREMENTS)]
        )
        if result.returncode != 0:
            say("The SDK could not be installed. Check your network access to pypi.org, then run this again.")
            raise SystemExit(1)
    os.execv(str(python), [str(python), str(Path(__file__).resolve()), *argv])


# Prompts ---------------------------------------------------------------------


def _clean(value: str) -> str:
    return value.strip().strip("'\"").strip()


def ask(label: str, *, default: str = "", check=None, secret: bool = False, hint: str = "") -> str:
    while True:
        if hint:
            say(f"  {hint}")
        if secret:
            suffix = " (press Return to keep the saved key)" if default else ""
            raw = getpass.getpass(f"{label}{suffix}: ")
        else:
            suffix = f" [{default}]" if default else ""
            raw = input(f"{label}{suffix}: ")
        value = _clean(raw) or default
        if not value:
            say("  This value is required.")
            continue
        if check is None:
            return value
        problem, fixed = check(value)
        if problem is None:
            return fixed
        say(f"  {problem}")


def _https_base(value: str, *, playbook: bool = False) -> tuple[str | None, str]:
    value = value.rstrip("/")
    match = re.match(r"^(https://[^/\s?#]+)(/.*)?$", value)
    if not match:
        return "Paste the full address starting with https://", value
    if playbook and match.group(2):
        return None, match.group(1)  # drop a pasted /iris/data/... path
    if match.group(2):
        return "Paste only the base address, with nothing after .redis.io", value
    return None, match.group(1)


def _pattern(pattern: str, message: str):
    def check(value: str) -> tuple[str | None, str]:
        return (None, value) if re.fullmatch(pattern, value) else (message, value)

    return check


def _key(value: str) -> tuple[str | None, str]:
    if len(value) < 16 or any(c.isspace() for c in value):
        return "That does not look like a complete key. Copy it again from the console.", value
    return None, value


# Settings file ---------------------------------------------------------------


def config_path(argument: str | None) -> Path:
    if argument:
        return Path(argument).expanduser()
    configured = (os.environ.get("REDIS_SHARED_MEMORY_CONFIG") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".config" / "redis-shared-memory" / "editor.env"


EXTRACTOR_COMMENT = "# MemoryETL extractor used by scripts/setup_demo.py: "


def read_existing(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(EXTRACTOR_COMMENT):
            values["_EXTRACTOR_ID"] = line[len(EXTRACTOR_COMMENT):].strip()
        elif line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_settings(path: Path, values: dict[str, str], extractor_id: str = "") -> Path | None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.backup-{datetime.now():%Y%m%d-%H%M%S}")
        os.replace(path, backup)
        os.chmod(backup, 0o600)
    lines = [
        "# Redis Shared Memory + Playbook settings, written by scripts/setup_demo.py.",
        "# Keep this file private. Never paste a key into a chat or commit this file.",
    ]
    if extractor_id:
        # A comment, because the plugin accepts only the settings it uses.
        lines.append(f"{EXTRACTOR_COMMENT}{extractor_id}")
    lines += [f"{name}={value}" for name, value in values.items()]
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return backup


def collect(existing: dict[str, str]) -> tuple[dict[str, str], str]:
    step(1, "Enter the values from the Redis Cloud console")
    say("Copy each value from the console and paste it here. Keys are not shown as you type.")
    say()
    say("Agent Memory (Agent Memory > your service > Configuration):")
    memory_url = ask(
        "  Agent Memory endpoint",
        default=existing.get("IRIS_AGENT_MEMORY_URL", ""),
        check=_https_base,
        hint="The URL List address, for example https://agent-memory.public....redis.io",
    )
    store_id = ask(
        "  Store ID",
        default=existing.get("IRIS_AGENT_MEMORY_STORE_ID", ""),
        check=_pattern(r"st_[0-9a-f]{32}", "A store ID looks like st_ followed by 32 letters and digits."),
    )
    memory_key = ask(
        "  Agent Memory API key",
        default=existing.get("IRIS_AGENT_MEMORY_API_KEY", ""),
        check=_key,
        secret=True,
    )
    extractor_id = ask(
        "  MemoryETL extractor ID",
        default=existing.get("_EXTRACTOR_ID", ""),
        check=_pattern(r"ex_[0-9a-f]{32}", "An extractor ID looks like ex_ followed by 32 letters and digits."),
        hint="On the MemoryETL tab, in the extractor's REST API example (\"extractorId\").",
    )
    say()
    say("Agent Playbooks (Agent Playbooks > your playbook > Configuration):")
    playbook_url = ask(
        "  Playbook agent endpoint",
        default=existing.get("IRIS_AGENT_PLAYBOOKS_URL", ""),
        check=lambda value: _https_base(value, playbook=True),
    )
    playbook_id = ask(
        "  Playbook ID",
        default=existing.get("IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID", ""),
        check=_pattern(r"pb_[0-9a-f]{32}", "A playbook ID looks like pb_ followed by 32 letters and digits."),
    )
    playbook_key = ask(
        "  Playbook API key",
        default=existing.get("IRIS_AGENT_PLAYBOOKS_API_KEY", ""),
        check=_key,
        secret=True,
    )
    say()
    say("You:")
    participant = ask(
        "  Your participant name",
        default=existing.get("RAM_PARTICIPANT", "andrew"),
        check=_pattern(r"[A-Za-z0-9-]{1,64}", "Use letters, digits, or hyphens only."),
        hint=f"The demo has work for {', '.join(DEMO_PARTICIPANTS)}. Pick one to see their work in the tour.",
    ).lower()
    namespace = existing.get("RAM_NAMESPACE", "real-reaction")
    values = {
        "IRIS_AGENT_MEMORY_URL": memory_url,
        "IRIS_AGENT_MEMORY_STORE_ID": store_id,
        "IRIS_AGENT_MEMORY_API_KEY": memory_key,
        "RAM_NAMESPACE": namespace,
        "RAM_PERSONAL_NAMESPACE": f"private-{participant}",
        "RAM_PARTICIPANT": participant,
        # Earlier versions wrote the demo under this one owner; it is used only
        # to find those records and move them into the namespace.
        "RAM_AGENDA_OWNER_ID": existing.get("RAM_AGENDA_OWNER_ID", "ami-project-office"),
        "RAM_MEMORY_LAYOUT": existing.get("RAM_MEMORY_LAYOUT", "compact"),
        # The private-capture hooks record only sessions in this project.
        "RAM_CAPTURE_FOLDERS": existing.get("RAM_CAPTURE_FOLDERS", str(ROOT)),
        "IRIS_AGENT_PLAYBOOKS_URL": playbook_url,
        "IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID": playbook_id,
        "IRIS_AGENT_PLAYBOOKS_API_KEY": playbook_key,
    }
    return values, extractor_id


# Plugin scope ----------------------------------------------------------------

PLUGIN_SELECTOR = "redis-shared-memory-editor@redis-field-engineering"
MARKETPLACE = "redis-field-engineering"
# ChatGPT ships its own codex; prefer it so the plugin is managed by the same version.
BUNDLED_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")


def _set_in_table(config_toml: Path, section: str, name: str, key: str, value: object) -> str:
    """Set ``[section."name"] key = value`` in a Codex config.toml, safely.

    Returns "changed", "unchanged", "missing" (no file yet), or "manual" when
    the file cannot be edited without risking a malformed or duplicate table.
    """

    import json
    import tomllib

    try:
        text = config_toml.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing"
    try:
        current = tomllib.loads(text).get(section, {}).get(name)
    except tomllib.TOMLDecodeError:
        return "manual"
    if isinstance(current, dict) and current.get(key) == value:
        return "unchanged"
    header = f"[{section}.{json.dumps(name)}]"
    literal = json.dumps(value)
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        if current is not None:
            return "manual"  # the table exists but is spelled differently
        lines += ["", header, f"{key} = {literal}"]
    else:
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
            len(lines),
        )
        found = [i for i in range(start + 1, end) if re.match(rf"\s*{re.escape(key)}\s*=", lines[i])]
        if found:
            lines[found[0]] = f"{key} = {literal}"
        else:
            lines.insert(start + 1, f"{key} = {literal}")
    updated = "\n".join(lines) + "\n"
    try:
        if tomllib.loads(updated).get(section, {}).get(name, {}).get(key) != value:
            return "manual"
    except tomllib.TOMLDecodeError:
        return "manual"
    backup = config_toml.with_name(f"{config_toml.name}.backup-{datetime.now():%Y%m%d-%H%M%S}")
    backup.write_text(text, encoding="utf-8")
    os.chmod(backup, config_toml.stat().st_mode & 0o777)
    temporary = config_toml.with_name(f".{config_toml.name}.setup")
    temporary.write_text(updated, encoding="utf-8")
    os.chmod(temporary, config_toml.stat().st_mode & 0o777)
    os.replace(temporary, config_toml)
    return "changed"


def disable_account_wide(config_toml: Path) -> str:
    """Turn the plugin off in the user's Codex config; the project turns it on.

    The repository's .codex/config.toml enables the plugin, so it runs only in
    this project (once the project is trusted).
    """

    return _set_in_table(config_toml, "plugins", PLUGIN_SELECTOR, "enabled", False)


def trust_folder(config_toml: Path, folder: Path) -> str:
    """Mark the project folder trusted, so Codex reads its .codex/config.toml."""

    return _set_in_table(config_toml, "projects", str(folder), "trust_level", "trusted")


def folder_trusted(config_toml: Path, folder: Path) -> bool:
    import tomllib

    try:
        data = tomllib.loads(config_toml.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return False
    return data.get("projects", {}).get(str(folder), {}).get("trust_level") == "trusted"


def find_codex() -> str | None:
    import shutil

    if BUNDLED_CODEX.is_file():
        return str(BUNDLED_CODEX)
    return shutil.which("codex")


def chatgpt_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "ChatGPT"], capture_output=True).returncode == 0
    except OSError:
        return False


def confirm(question: str, default: bool = True) -> bool:
    answer = input(f"  {question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer.startswith("y")


def install_plugin(codex: str, run=subprocess.run, ask_switch=confirm) -> tuple[bool, str]:
    """Add this folder as the plugin list and install (or refresh) the plugin.

    Installing again refreshes ChatGPT's cached copy, so this also updates it.
    """

    def codex_run(*arguments: str):
        return run([codex, *arguments], capture_output=True, text=True)

    added = codex_run("plugin", "marketplace", "add", str(ROOT))
    if added.returncode != 0 and "different source" in f"{added.stdout}{added.stderr}":
        say("  ChatGPT's plugin list points at another copy of this project.")
        if not ask_switch("Point it at this folder instead?"):
            return False, "The plugin list still points at the other copy. Run setup from that folder instead."
        codex_run("plugin", "remove", PLUGIN_SELECTOR)
        codex_run("plugin", "marketplace", "remove", MARKETPLACE)
        added = codex_run("plugin", "marketplace", "add", str(ROOT))
    if added.returncode != 0:
        return False, "Codex could not add this folder as a plugin list."
    installed = codex_run("plugin", "add", PLUGIN_SELECTOR)
    if installed.returncode != 0:
        return False, "Codex could not install the plugin."
    return True, "installed"


def remove_plugin(codex: str, run=subprocess.run) -> bool:
    removed = run([codex, "plugin", "remove", PLUGIN_SELECTOR], capture_output=True, text=True)
    listed = run([codex, "plugin", "marketplace", "remove", MARKETPLACE], capture_output=True, text=True)
    return removed.returncode == 0 or listed.returncode == 0


def wait_for_chatgpt_to_quit() -> None:
    for _ in range(3):
        if not chatgpt_running():
            return
        say("ChatGPT is open. Setup installs the plugin into it, so quit ChatGPT now:")
        input("click its window, press ⌘ Q, then press Return here. ")
    if chatgpt_running():
        say("ChatGPT is still open. Setup continues; quit and reopen ChatGPT when it finishes.")


# Service steps ---------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="Settings file to write (default: ~/.config/redis-shared-memory/editor.env)")
    parser.add_argument("--skip-load", action="store_true", help="Do not load the demo documents")
    parser.add_argument("--remove", action="store_true", help="Remove the plugin from ChatGPT and stop")
    args = parser.parse_args(argv)
    if args.remove:
        return remove(args.config)
    ensure_environment(argv)

    sys.path[:0] = [str(ROOT), str(SERVER)]
    from admin_bootstrap.bundle import Bundle
    from admin_bootstrap.context_pipeline import ingestion_documents
    from admin_bootstrap.memory_etl import MemoryETLError, ingest_documents
    from ram_plugin.agenda import _load_policy
    from ram_plugin.config import PluginError, public_error
    from ram_plugin.credentials import load_credential_file
    from ram_plugin.playbook import PlaybookClient
    from ram_plugin.ram import RAMClient
    from reconciliation.job import ReconciliationError, ReconciliationJob, adopt_unnamespaced, move_into_namespace

    say("Redis Shared Memory + Playbook setup")
    wait_for_chatgpt_to_quit()
    path = config_path(args.config)
    existing = read_existing(path)
    if existing and "IRIS_AGENT_MEMORY_URL" not in existing:
        say(f"Your settings file {path} uses an older format. Its values are not reused;")
        say("it is kept as a backup when the new settings are saved.")
        existing = {}
    values, extractor_id = collect(existing)

    step(2, "Save your settings")
    try:
        from ram_plugin.config import load_config

        load_config(values)
    except PluginError as error:
        say(f"  {error}")
        say("  Nothing was saved. Run this command again and correct that value.")
        return 1
    backup = write_settings(path, values, extractor_id)
    config = load_credential_file(path)
    say(f"  Saved to {path} (only your user account can read it).")
    if backup:
        say(f"  Your previous settings were kept in {backup}.")

    step(3, "Check the connection")
    ram = RAMClient(config, timeout_ms=30_000)
    try:
        ram.search({"filter": {"ownerId": {"eq": config.participant}}, "limit": 1})
        say("  ✓ Agent Memory accepted the key.")
    except Exception as error:  # noqa: BLE001 - report the public code only
        say(f"  ✗ Agent Memory: {public_error(error)['message']}")
        return 1
    try:
        policy = _load_policy(PlaybookClient(config))
        say(f"  ✓ Playbook serves the agenda Skill, version {policy['version']}, with every file verified.")
    except Exception as error:  # noqa: BLE001
        detail = str(error) if isinstance(error, PluginError) else public_error(error)["message"]
        say(f"  ✗ Playbook: {detail}")
        say("  Check that the Skill is uploaded with the alias prepare-management-review-agenda and published.")
        return 1

    bundle = Bundle.load(ROOT / "context-models" / "management-agenda" / "v1")
    job = ReconciliationJob(config, ram, bundle)
    if not args.skip_load:
        step(4, "Load the demo documents")
        try:
            # Everything for the project lives in the shared namespace. Records
            # from older setups that have no namespace are moved there first, so
            # they are not mistaken for missing documents and loaded twice.
            adopted = adopt_unnamespaced(config, ram, apply=True)
            if adopted["moved_count"]:
                say(f"  Moved {adopted['moved_count']} earlier record(s) into the {config.namespace} namespace.")
                if not job.wait_until_searchable(adopted["moved_observation_ids"]):
                    say("  ✗ The moved records are not searchable yet. Wait a minute and run this command again.")
                    return 1
            existing_observations = job.load_observations()
        except (ReconciliationError, PluginError) as error:
            say(f"  ✗ {error}")
            return 1
        loaded = {
            str((record.get("attributes") or {}).get("source_artifact_id"))
            for record in existing_observations
        }
        documents = tuple(doc for doc in ingestion_documents(bundle) if doc.document_id not in loaded)
        if not documents:
            say(f"  All demo documents are already loaded ({len(existing_observations)} observations).")
        else:
            if loaded:
                say(f"  {len(loaded)} document(s) already loaded; adding the remaining {len(documents)}.")
            say(f"  Extracting organizational state from {len(documents)} document(s). This takes a few minutes...")
            try:
                result = ingest_documents(
                    ram,
                    documents,
                    owner_id=config.participant,
                    extractor_id=extractor_id,
                    timeout_seconds=900,
                    poll_seconds=5,
                )
                created = [memory_id for item in result.get("artifacts", []) for memory_id in item.get("memoryIds", [])]
                # MemoryETL places its output by the extractor's settings, so move
                # it into the shared namespace explicitly.
                move_into_namespace(config, ram, created)
            except (MemoryETLError, PluginError) as error:
                say(f"  ✗ {error}")
                say("  Check the extractor ID and that the extractor uses the organizational_state type.")
                return 1
            except ReconciliationError as error:
                say(f"  ✗ {error}")
                return 1
            except Exception as error:  # noqa: BLE001
                say(f"  ✗ {public_error(error)['message']}")
                return 1
            outputs = sum(item.get("outputCount", 0) for item in result.get("artifacts", []))
            say(f"  ✓ Extraction finished ({outputs} records).")
            if not job.wait_until_searchable(created):
                say("  ✗ The new records are not searchable yet. Wait a minute and run this command again.")
                return 1
        try:
            applied = job.run(apply=True)
        except ReconciliationError as error:
            say(f"  ✗ {error}")
            return 1
        say(f"  ✓ Current state built: {applied['projection_count']} items from {applied['observation_count']} observations.")

    step(5, "Install the plugin in ChatGPT")
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    codex_config = codex_home / "config.toml"
    from ram_plugin.config import VERSION

    codex = find_codex()
    if codex is None:
        say("  ✗ ChatGPT's codex program was not found. Install the ChatGPT desktop app, then run this again.")
        return 1
    installed, problem = install_plugin(codex)
    if not installed:
        say(f"  ✗ {problem}")
        return 1
    say(f"  ✓ Plugin {VERSION} installed.")

    # Plugins install for the whole account. Switch it off there; the project's
    # own .codex/config.toml switches it back on in this folder.
    scope = disable_account_wide(codex_config)
    if scope in {"changed", "unchanged"}:
        say("  ✓ It runs only in this project folder. Your other projects don't see it.")
    else:
        say(f"  ✗ Could not limit the plugin to this folder; check {codex_config}.")
        return 1

    if folder_trusted(codex_config, ROOT):
        say("  ✓ This folder is trusted, so its settings switch the plugin on here.")
    else:
        say("  ChatGPT reads this folder's settings, which switch the plugin on here,")
        say("  only once you trust the folder. Trusting it lets ChatGPT use this project's")
        say("  .codex settings when you work in this folder.")
        if confirm("Trust this folder now?"):
            outcome = trust_folder(codex_config, ROOT)
            if outcome in {"changed", "unchanged"}:
                say("  ✓ Folder trusted.")
            else:
                say("  ✗ Could not record that; trust the folder when ChatGPT asks.")
        else:
            say("  Not trusted. When you open the project in ChatGPT, choose to trust it.")

    launcher = codex_home / "plugins" / "cache" / MARKETPLACE / "redis-shared-memory-editor" / VERSION / "server" / "launch.py"
    environment = dict(os.environ, PLUGIN_DATA=str(codex_home / "plugins" / "data" / PLUGIN_ID))
    result = subprocess.run([sys.executable, "-I", str(launcher), "--install"], env=environment)
    if result.returncode != 0:
        say("  ✗ The plugin's helper program could not be prepared. It will retry on first use.")
    else:
        say("  ✓ Plugin helper program ready.")

    say()
    say("Setup complete. Open ChatGPT and continue with Step 10 of the README.")
    say("If ChatGPT shows Review hooks, allow the two Redis Shared Memory hooks.")
    return 0


def remove(argv_config: str | None) -> int:
    say("Remove the Redis Shared Memory + Playbook plugin")
    wait_for_chatgpt_to_quit()
    codex = find_codex()
    if codex is None or not remove_plugin(codex):
        say("  ✗ Codex could not remove the plugin. It may already be removed.")
        return 1
    say("  ✓ Plugin and plugin list removed from ChatGPT.")
    say(f"  Your settings file {config_path(argv_config)} and the records in Agent Memory are kept.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        say("\nSetup cancelled. Nothing else was changed.")
        raise SystemExit(130)
