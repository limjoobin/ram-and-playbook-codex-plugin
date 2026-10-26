"""Validated configuration and public error mapping."""

from __future__ import annotations

from dataclasses import dataclass
import re
import socket
from typing import Mapping
from urllib.error import URLError
from urllib.parse import SplitResult, urlsplit


VERSION = "0.8.0"
SLUG = re.compile(r"^[a-zA-Z0-9-]{1,64}$")
SETTING_NAMES = (
    "RAM_ENDPOINT",
    "RAM_STORE_ID",
    "RAM_NAMESPACE",
    "RAM_PERSONAL_NAMESPACE",
    "RAM_PARTICIPANT",
    "RAM_API_KEY",
    "RAM_AGENDA_OWNER_ID",
    "PLAYBOOK_MCP_URL",
    "PLAYBOOK_API_KEY",
)


class PluginError(Exception):
    """An error that is safe to report to the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Config:
    endpoint: str
    store_id: str
    namespace: str
    personal_namespace: str
    participant: str
    api_key: str
    agenda_owner_id: str
    playbook_mcp_url: str
    playbook_api_key: str


def _validated_url(name: str, value: str) -> tuple[str, SplitResult]:
    try:
        url = urlsplit(value)
        _ = url.port
    except ValueError as error:
        raise PluginError("configuration_invalid", f"{name} must be an HTTP(S) URL.") from error
    loopback = url.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        url.scheme not in ({"https", "http"} if loopback else {"https"})
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise PluginError(
            "configuration_invalid",
            f"{name} must use HTTPS, except for loopback development, and must not contain credentials, a query, or a fragment.",
        )
    return value.rstrip("/"), url


def load_config(values: Mapping[str, str | None]) -> Config:
    missing = [name for name in SETTING_NAMES if not (values.get(name) or "").strip()]
    if missing:
        raise PluginError(
            "configuration_missing",
            f"Complete these local connection settings: {', '.join(missing)}.",
        )

    endpoint, _ = _validated_url("RAM_ENDPOINT", (values["RAM_ENDPOINT"] or "").strip())
    playbook_url, playbook_parts = _validated_url(
        "PLAYBOOK_MCP_URL", (values["PLAYBOOK_MCP_URL"] or "").strip()
    )
    segments = [segment for segment in playbook_parts.path.split("/") if segment]
    if len(segments) != 4 or segments[:2] != ["v1", "playbooks"] or segments[3] != "mcp":
        raise PluginError(
            "configuration_invalid",
            "PLAYBOOK_MCP_URL must identify /v1/playbooks/{playbookId}/mcp.",
        )

    for name in (
        "RAM_STORE_ID",
        "RAM_NAMESPACE",
        "RAM_PERSONAL_NAMESPACE",
        "RAM_PARTICIPANT",
        "RAM_AGENDA_OWNER_ID",
    ):
        if not SLUG.fullmatch((values[name] or "").strip()):
            raise PluginError(
                "configuration_invalid",
                f"{name} must contain 1–64 letters, digits, or hyphens.",
            )

    if (values["RAM_PERSONAL_NAMESPACE"] or "").strip().lower() == (
        values["RAM_NAMESPACE"] or ""
    ).strip().lower():
        raise PluginError(
            "configuration_invalid",
            "RAM_PERSONAL_NAMESPACE must differ from the shared RAM_NAMESPACE.",
        )

    api_key = (values["RAM_API_KEY"] or "").strip()
    playbook_api_key = (values["PLAYBOOK_API_KEY"] or "").strip()
    if api_key.startswith("__encrypted__:") or playbook_api_key.startswith("__encrypted__:"):
        raise PluginError(
            "credential_unavailable",
            "A configured service credential is unavailable. Replace it in the local .env file.",
        )

    return Config(
        endpoint=endpoint,
        store_id=(values["RAM_STORE_ID"] or "").strip(),
        namespace=(values["RAM_NAMESPACE"] or "").strip(),
        personal_namespace=(values["RAM_PERSONAL_NAMESPACE"] or "").strip(),
        participant=(values["RAM_PARTICIPANT"] or "").strip(),
        api_key=api_key,
        agenda_owner_id=(values["RAM_AGENDA_OWNER_ID"] or "").strip(),
        playbook_mcp_url=playbook_url,
        playbook_api_key=playbook_api_key,
    )


def public_error(error: BaseException) -> dict[str, object]:
    """Map internal failures to stable messages without returning raw payloads."""

    if isinstance(error, PluginError):
        return {"code": error.code, "message": str(error)}

    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    error_type = getattr(error, "error_type", None)
    if status == 401:
        return {
            "code": "authentication_failed",
            "message": "RAM rejected the API key. Replace it in the local .env file.",
        }
    if status == 403:
        return {
            "code": "access_denied",
            "message": "RAM denied access. Check that the API key can access the configured store.",
        }
    if status == 404:
        return {
            "code": "not_found",
            "message": "The RAM store or memory was not found. Check the store ID and memory ID.",
        }
    if status == 429:
        return {"code": "rate_limited", "message": "RAM is rate limited. Wait briefly before trying again."}
    if status in (400, 413):
        return {
            "code": "request_rejected",
            "message": "RAM rejected the request. Check the configured store and shorten the fact if necessary.",
        }
    if status == 424:
        if error_type == "/errors/database-out-of-memory":
            return {
                "code": "dependency_unavailable",
                "dependency_type": "database_out_of_memory",
                "message": "RAM reports that database capacity is unavailable. Contact the Redis service owner before retrying.",
            }
        if error_type == "/errors/resource-unavailable":
            return {
                "code": "dependency_unavailable",
                "dependency_type": "resource_unavailable",
                "message": "RAM reports that a required resource is unavailable. Wait briefly, retry a read, or contact the Redis service owner.",
            }
        return {
            "code": "dependency_unavailable",
            "message": "RAM could not complete the request because a dependency is unavailable. Retry a read or contact the Redis service owner.",
        }
    if status == 408 or isinstance(error, (TimeoutError, socket.timeout)):
        return {
            "code": "timeout",
            "message": "RAM did not respond in time. Check connectivity and try a read before retrying a write.",
        }
    if isinstance(status, int) and status >= 500:
        return {"code": "service_unavailable", "message": "RAM is temporarily unavailable. Try again later."}
    if isinstance(error, (URLError, ConnectionError)):
        return {
            "code": "network_error",
            "message": "Cannot reach RAM. Check the endpoint, internet connection, and VPN.",
        }
    return {
        "code": "unexpected_error",
        "message": "The RAM request could not be verified. Check the local connection settings and run the status tool.",
    }
