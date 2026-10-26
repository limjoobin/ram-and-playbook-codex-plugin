"""Allowlisted Streamable HTTP MCP client for Redis Agent Playbook."""

from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

from .config import Config, PluginError


ALLOWED_TOOLS = frozenset({"discover_entries", "load_skill", "fetch_resource"})
PROTOCOL_VERSION = "2025-06-18"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _json_payload(payload: bytes, content_type: str) -> dict[str, Any]:
    """Decode a JSON or server-sent-event MCP response."""

    candidates: list[str]
    text = payload.decode("utf-8")
    if "text/event-stream" in content_type:
        candidates = [
            line[5:].strip()
            for line in text.splitlines()
            if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}
        ]
    else:
        candidates = [text]
    for candidate in reversed(candidates):
        decoded = json.loads(candidate)
        if isinstance(decoded, dict):
            return decoded
    raise PluginError("playbook_contract_error", "Playbook returned an incompatible MCP response.")


class PlaybookClient:
    """A minimal MCP client that can call only the reviewed Playbook read tools."""

    def __init__(self, config: Config, timeout_seconds: float = 20.0) -> None:
        self.url = config.playbook_mcp_url
        self.api_key = config.playbook_api_key
        self.timeout_seconds = timeout_seconds
        self.session_id: str | None = None
        self._initialized = False
        self._next_id = 1
        self._opener = build_opener(
            _RejectRedirects(), HTTPSHandler(context=ssl.create_default_context())
        )

    def _request(self, message: dict[str, Any], expect_response: bool = True) -> dict[str, Any]:
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["MCP-Session-Id"] = self.session_id
        request = Request(self.url, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                self.session_id = response.headers.get("MCP-Session-Id") or self.session_id
                payload = response.read(1_048_576)
                content_type = response.headers.get("Content-Type", "application/json")
        except HTTPError as error:
            if error.code in {401, 403}:
                raise PluginError(
                    "playbook_authentication_failed",
                    "Playbook rejected the configured credential.",
                ) from None
            if error.code in {408, 429} or error.code >= 500:
                raise PluginError("playbook_unavailable", "Playbook is temporarily unavailable.") from None
            raise PluginError("playbook_request_rejected", "Playbook rejected the read request.") from None
        except (TimeoutError, URLError, OSError):
            raise PluginError("playbook_unavailable", "Playbook is temporarily unavailable.") from None
        if not expect_response:
            return {}
        if not payload:
            raise PluginError(
                "playbook_contract_error", "Playbook returned an incompatible MCP response."
            )
        try:
            decoded = _json_payload(payload, content_type)
        except (UnicodeError, json.JSONDecodeError):
            raise PluginError(
                "playbook_contract_error", "Playbook returned an incompatible MCP response."
            ) from None
        error = decoded.get("error")
        if isinstance(error, dict):
            raise PluginError("playbook_request_rejected", "Playbook rejected the read request.")
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise PluginError("playbook_contract_error", "Playbook returned an incompatible MCP response.")
        return result

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        identifier = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": identifier,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        return self._request(message)

    def _initialize(self) -> None:
        if self._initialized:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "redis-shared-memory-editor", "version": "1"},
            },
        )
        self._request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            expect_response=False,
        )
        self._initialized = True

    def inventory(self) -> list[str]:
        self._initialize()
        result = self._rpc("tools/list")
        tools = result.get("tools")
        if not isinstance(tools, list) or any(not isinstance(tool, dict) for tool in tools):
            raise PluginError("playbook_contract_error", "Playbook returned an incompatible tool list.")
        return sorted(
            tool["name"]
            for tool in tools
            if isinstance(tool.get("name"), str)
        )

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_TOOLS:
            raise PluginError("playbook_operation_denied", "That Playbook operation is not exposed.")
        self._initialize()
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError") is True:
            raise PluginError("playbook_request_rejected", "Playbook rejected the read request.")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    try:
                        parsed = json.loads(item["text"])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
        raise PluginError("playbook_contract_error", "Playbook returned no structured result.")

