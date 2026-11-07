"""Validated configuration and public error mapping."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import socket
from typing import Mapping
from urllib.error import URLError
from urllib.parse import SplitResult, urlsplit

from .layout import DEFAULT_LAYOUT, LAYOUTS


VERSION = "0.13.0"
SLUG = re.compile(r"^[a-zA-Z0-9-]{1,64}$")
PLAYBOOK_ID = re.compile(r"^pb_[0-9a-f]{32}$")
# Redis Cloud store IDs look like st_<32 hex>; local stores may use plain slugs.
STORE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
# Connection settings use the redis-iris SDK names (``IRIS_AGENT_MEMORY_*`` and
# ``IRIS_AGENT_PLAYBOOKS_*``) so the same values work with the ``iris`` CLI.
SETTING_NAMES = (
    "IRIS_AGENT_MEMORY_URL",
    "IRIS_AGENT_MEMORY_STORE_ID",
    "IRIS_AGENT_MEMORY_API_KEY",
    "RAM_NAMESPACE",
    "RAM_PERSONAL_NAMESPACE",
    "RAM_PARTICIPANT",
    "RAM_AGENDA_OWNER_ID",
    "IRIS_AGENT_PLAYBOOKS_URL",
    "IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID",
    "IRIS_AGENT_PLAYBOOKS_API_KEY",
    "RAM_MEMORY_LAYOUT",
)
# Administrator-only credentials. The desktop MCP accepts these names in the
# private file but never copies their values into its runtime Config.
ADMIN_SETTING_NAMES = (
    "IRIS_AGENT_PLAYBOOKS_CONTENT_API_KEY",
    "IRIS_AGENT_PLAYBOOKS_SERVICE_URL",
    "IRIS_AGENT_PLAYBOOKS_SERVICE_TOKEN",
    "IRIS_AGENT_MEMORY_SERVICE_URL",
    "IRIS_AGENT_MEMORY_SERVICE_TOKEN",
)
OPTIONAL_SETTING_NAMES = ("RAM_PERSONAL_NAMESPACE", "RAM_MEMORY_LAYOUT")
REQUIRED_SETTING_NAMES = tuple(
    name for name in SETTING_NAMES if name not in OPTIONAL_SETTING_NAMES
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
    playbook_url: str
    playbook_id: str
    playbook_api_key: str
    # How management records are stored in RAM custom memory types; see layout.py.
    memory_layout: str = DEFAULT_LAYOUT


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
    missing = [name for name in REQUIRED_SETTING_NAMES if not (values.get(name) or "").strip()]
    if missing:
        raise PluginError(
            "configuration_missing",
            f"Complete these local connection settings: {', '.join(missing)}.",
        )

    endpoint, _ = _validated_url(
        "IRIS_AGENT_MEMORY_URL", (values["IRIS_AGENT_MEMORY_URL"] or "").strip()
    )
    playbook_url, playbook_parts = _validated_url(
        "IRIS_AGENT_PLAYBOOKS_URL", (values["IRIS_AGENT_PLAYBOOKS_URL"] or "").strip()
    )
    if playbook_parts.path.strip("/"):
        raise PluginError(
            "configuration_invalid",
            "IRIS_AGENT_PLAYBOOKS_URL must be the data-plane base URL, without the /iris/data/v1/agent-playbooks path.",
        )
    playbook_id = (values["IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID"] or "").strip()
    if not PLAYBOOK_ID.fullmatch(playbook_id):
        raise PluginError(
            "configuration_invalid",
            "IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID must be a playbook ID such as pb_ followed by 32 hex characters.",
        )

    participant = (values["RAM_PARTICIPANT"] or "").strip()
    configured_personal = (values.get("RAM_PERSONAL_NAMESPACE") or "").strip()
    personal_namespace = configured_personal or f"private-{participant}"
    if len(personal_namespace) > 64:
        personal_namespace = f"private-{hashlib.sha256(participant.encode()).hexdigest()[:40]}"

    if not STORE_ID.fullmatch((values["IRIS_AGENT_MEMORY_STORE_ID"] or "").strip()):
        raise PluginError(
            "configuration_invalid",
            "IRIS_AGENT_MEMORY_STORE_ID must contain 1–64 letters, digits, underscores, or hyphens.",
        )
    for name, value in (
        ("RAM_NAMESPACE", values["RAM_NAMESPACE"]),
        ("RAM_PERSONAL_NAMESPACE", personal_namespace),
        ("RAM_PARTICIPANT", participant),
        ("RAM_AGENDA_OWNER_ID", values["RAM_AGENDA_OWNER_ID"]),
    ):
        if not SLUG.fullmatch((value or "").strip()):
            raise PluginError(
                "configuration_invalid",
                f"{name} must contain 1–64 letters, digits, or hyphens.",
            )

    if personal_namespace.lower() == (values["RAM_NAMESPACE"] or "").strip().lower():
        raise PluginError(
            "configuration_invalid",
            "RAM_PERSONAL_NAMESPACE must differ from the shared RAM_NAMESPACE.",
        )

    memory_layout = (values.get("RAM_MEMORY_LAYOUT") or DEFAULT_LAYOUT).strip().lower()
    if memory_layout not in LAYOUTS:
        raise PluginError(
            "configuration_invalid",
            f"RAM_MEMORY_LAYOUT must be one of: {', '.join(LAYOUTS)}.",
        )

    api_key = (values["IRIS_AGENT_MEMORY_API_KEY"] or "").strip()
    playbook_api_key = (values["IRIS_AGENT_PLAYBOOKS_API_KEY"] or "").strip()
    if api_key.startswith("__encrypted__:") or playbook_api_key.startswith("__encrypted__:"):
        raise PluginError(
            "credential_unavailable",
            "A configured service credential is unavailable. Replace it in the local .env file.",
        )

    return Config(
        endpoint=endpoint,
        store_id=(values["IRIS_AGENT_MEMORY_STORE_ID"] or "").strip(),
        namespace=(values["RAM_NAMESPACE"] or "").strip(),
        personal_namespace=personal_namespace,
        participant=participant,
        api_key=api_key,
        agenda_owner_id=(values["RAM_AGENDA_OWNER_ID"] or "").strip(),
        playbook_url=playbook_url,
        playbook_id=playbook_id,
        playbook_api_key=playbook_api_key,
        memory_layout=memory_layout,
    )


def error_chain(error: BaseException) -> list[BaseException]:
    """The error and its explicit causes; SDK retry layers wrap the original."""

    chain: list[BaseException] = []
    item: BaseException | None = error
    while item is not None and len(chain) < 4 and all(item is not seen for seen in chain):
        chain.append(item)
        item = item.__cause__
    return chain


def error_status(error: BaseException) -> int | None:
    """The first HTTP status carried by the error or one of its causes."""

    for item in error_chain(error):
        for attribute in ("status_code", "status"):
            value = getattr(item, attribute, None)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _error_modules(error: BaseException) -> set[str]:
    return {type(item).__module__.split(".")[0] for item in error_chain(error)}


def _is_transport_timeout(error: BaseException) -> bool:
    return "httpx" in _error_modules(error) and any("Timeout" in type(item).__name__ for item in error_chain(error))


def _is_transport_error(error: BaseException) -> bool:
    """httpx transport failures and the SDK's no-response error, without importing httpx."""

    return "httpx" in _error_modules(error) or any(
        type(item).__name__ == "NoResponseError" for item in error_chain(error)
    )


def public_error(error: BaseException) -> dict[str, object]:
    """Map internal failures to stable messages without returning raw payloads."""

    if isinstance(error, PluginError):
        return {"code": error.code, "message": str(error)}

    chain = error_chain(error)
    status = error_status(error)
    # redis-iris SDK errors carry the RFC 9457 problem in ``data``.
    error_type = next(
        (
            value
            for item in chain
            for value in (getattr(item, "error_type", None), getattr(getattr(item, "data", None), "type", None))
            if value
        ),
        None,
    )
    if not isinstance(status, int) and _is_transport_timeout(error):
        status = 408
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
    if status == 408 or any(isinstance(item, (TimeoutError, socket.timeout)) for item in chain):
        return {
            "code": "timeout",
            "message": "RAM did not respond in time. Check connectivity and try a read before retrying a write.",
        }
    if isinstance(status, int) and status >= 500:
        return {"code": "service_unavailable", "message": "RAM is temporarily unavailable. Try again later."}
    if any(isinstance(item, (URLError, ConnectionError)) for item in chain) or _is_transport_error(error):
        return {
            "code": "network_error",
            "message": "Cannot reach RAM. Check the endpoint, internet connection, and VPN.",
        }
    return {
        "code": "unexpected_error",
        "message": "The RAM request could not be verified. Check the local connection settings and run the status tool.",
    }
