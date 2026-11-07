"""Allowlisted Redis Agent Playbooks reads through the redis-iris SDK.

The SDK reaches the Playbooks REST data plane. Only three reviewed reads are
exposed: discover published entries, load one exact Skill version, and fetch one
resource that a loaded Skill lists. Results keep the shapes the agenda and MCP
tools already consume.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from .config import Config, PluginError, _is_transport_error


ALLOWED_TOOLS = frozenset({"discover_entries", "load_skill", "fetch_resource"})
MAX_RESOURCE_BYTES = 1_048_576
_TEXT_TYPES = ("text/", "application/json", "application/yaml", "application/x-yaml")


# What a 404 means depends on the call: only Skill loads target an entry.
_NOT_FOUND = {
    "playbook": ("playbook_not_found", "The configured Playbook URL or playbook ID was not found."),
    "entry": ("playbook_entry_not_found", "The requested Playbook entry is not published."),
    "resource": ("playbook_resource_not_found", "The requested Playbook resource was not found."),
}
_MISSING = {"discover_entries": "playbook", "load_skill": "entry", "fetch_resource": "resource"}


def _public(error: BaseException, missing: str = "playbook") -> PluginError:
    if isinstance(error, PluginError):
        return error
    # The SDK's retry layer re-raises as PermanentError(...) from the original.
    chain = [item for item in (error, error.__cause__) if item is not None]
    status = next((s for s in (getattr(i, "status_code", None) for i in chain) if s is not None), None)
    names = {type(item).__name__ for item in chain}
    if status in {401, 403}:
        return PluginError("playbook_authentication_failed", "Playbook rejected the configured credential.")
    if status in {408, 429} or (isinstance(status, int) and status >= 500):
        return PluginError("playbook_unavailable", "Playbook is temporarily unavailable.")
    if "EntryNotFound" in names:
        return PluginError(*_NOT_FOUND["entry"])
    if status == 404:
        return PluginError(*_NOT_FOUND[missing])
    if isinstance(status, int):
        return PluginError("playbook_request_rejected", "Playbook rejected the read request.")
    if "ResourceTooLarge" in names:
        return PluginError("playbook_resource_too_large", "The Playbook resource exceeds the read limit.")
    if _is_transport_error(error) or any(isinstance(item, (TimeoutError, ConnectionError)) for item in chain):
        return PluginError("playbook_unavailable", "Playbook is temporarily unavailable.")
    return PluginError("playbook_contract_error", "Playbook returned an incompatible response.")


def _entry(entry: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "entry_type": entry.entry_type,
        "entry_key": entry.entry_key,
        "version": entry.version,
        "score": entry.score,
        "intents": list(entry.intents),
        "pinned": entry.pinned,
    }
    if entry.faq is not None:
        value["faq"] = {"question": entry.faq.question, "answer": entry.faq.answer}
    if entry.skill is not None:
        value["skill"] = {
            "name": entry.skill.name,
            "description": entry.skill.description,
            "uri": entry.skill.uri,
        }
    return value


def _digest_matches(data: bytes, expected: str) -> bool:
    algorithm, separator, value = expected.partition(":")
    if not separator:
        algorithm, value = "sha256", expected
    if algorithm.lower() != "sha256" or not value:
        return False
    return hashlib.sha256(data).hexdigest() == value.lower()


class PlaybookClient:
    """Read-only Playbook client that can call only the reviewed operations."""

    def __init__(self, config: Config, timeout_seconds: float = 20.0, client: Any | None = None) -> None:
        if client is None:
            from redis_iris.agent_playbooks import AgentPlaybooks, AgentPlaybooksSettings

            client = AgentPlaybooks(
                AgentPlaybooksSettings(
                    url=config.playbook_url,
                    playbook_id=config.playbook_id,
                    api_key=config.playbook_api_key,
                    timeout=timeout_seconds,
                )
            )
        self.sdk = client
        # Resource URIs a loaded Skill listed, mapped to their exact identity.
        self._resources: dict[str, dict[str, Any]] = {}

    def inventory(self) -> list[str]:
        """Check the Playbook data plane and return the reviewed operations."""

        try:
            self.sdk.client.get_playbook_health()
        except Exception as error:
            raise _public(error) from None
        return sorted(ALLOWED_TOOLS)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_TOOLS:
            raise PluginError("playbook_operation_denied", "That Playbook operation is not exposed.")
        try:
            if tool == "discover_entries":
                return self._discover(arguments)
            if tool == "load_skill":
                return self._load_skill(arguments)
            return self._fetch_resource(arguments)
        except PluginError:
            raise
        except Exception as error:
            raise _public(error, _MISSING[tool]) from None

    def _discover(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pins = [
            str(pin.get("entry_id") or pin.get("entry_key"))
            for pin in arguments.get("pinned_entries") or []
            if isinstance(pin, dict) and (pin.get("entry_id") or pin.get("entry_key"))
        ]
        found = self.sdk.discover(
            str(arguments["query"]),
            limit=int(arguments.get("limit") or 5),
            pin=pins,
        )
        # Pinned entries first, then ranked discoveries, as one list.
        entries = [_entry(entry) for entry in (*found.pinned, *found.discovered)]
        return {
            "entries": entries,
            "truncated": bool(getattr(found, "truncated", False)),
        }

    def _load_skill(self, arguments: dict[str, Any]) -> dict[str, Any]:
        entry_id = str(arguments["entry_id"])
        version = int(arguments["version"])
        skill = self.sdk.skill(entry_id, version=version)
        if skill.entry_id != entry_id or skill.version != version:
            raise PluginError("playbook_contract_error", "Playbook loaded a different Skill version.")
        resources = []
        for resource in skill.resources:
            descriptor = {
                "resource_id": resource.resource_id,
                "path": resource.path,
                "mime_type": resource.mime_type,
                "size_bytes": resource.size_bytes,
                "uri": resource.uri,
                "digest": resource.digest,
            }
            resources.append(descriptor)
            if resource.uri:
                self._resources[resource.uri] = {
                    "skill": skill,
                    "resource_id": resource.resource_id,
                    "digest": resource.digest,
                    "mime_type": resource.mime_type,
                }
        return {
            "entry_id": skill.entry_id,
            "entry_key": skill.entry_key,
            "version": skill.version,
            "content": {
                "manifest": {"name": skill.name, "description": skill.description},
                "instructions": skill.instructions,
                "resources": resources,
            },
        }

    def _fetch_resource(self, arguments: dict[str, Any]) -> dict[str, Any]:
        uri = str(arguments["uri"])
        listed = self._resources.get(uri)
        if listed is None:
            raise PluginError(
                "playbook_resource_unlisted",
                "Load the Skill that lists this resource before fetching it.",
            )
        content = self.sdk.skill_resource(
            listed["skill"], listed["resource_id"], max_bytes=MAX_RESOURCE_BYTES
        )
        data = bytes(content.data)
        digest = str(listed["digest"] or "")
        if digest and not _digest_matches(data, digest):
            raise PluginError("playbook_digest_mismatch", "A Playbook resource failed digest verification.")
        mime_type = str(content.mime_type or listed["mime_type"] or "application/octet-stream")
        result: dict[str, Any] = {"uri": uri, "digest": digest, "mime_type": mime_type}
        if mime_type.split(";")[0].strip().startswith(_TEXT_TYPES):
            try:
                result["text"] = data.decode("utf-8")
                return result
            except UnicodeDecodeError:
                pass
        result["blob"] = base64.b64encode(data).decode("ascii")
        return result
