"""Validated configuration and public error mapping."""

from __future__ import annotations

from dataclasses import dataclass
import re
import socket
from typing import Mapping
from urllib.error import URLError
from urllib.parse import urlsplit


VERSION = "0.3.0"
SLUG = re.compile(r"^[a-zA-Z0-9-]{1,64}$")
SETTING_NAMES = (
    "RAM_ENDPOINT",
    "RAM_STORE_ID",
    "RAM_NAMESPACE",
    "RAM_PARTICIPANT",
    "RAM_API_KEY",
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
    participant: str
    api_key: str


def load_config(values: Mapping[str, str | None]) -> Config:
    missing = [name for name in SETTING_NAMES if not (values.get(name) or "").strip()]
    if missing:
        raise PluginError(
            "configuration_missing",
            f"Complete these local connection settings: {', '.join(missing)}.",
        )

    endpoint = (values["RAM_ENDPOINT"] or "").strip()
    try:
        url = urlsplit(endpoint)
        _ = url.port
    except ValueError as error:
        raise PluginError("configuration_invalid", "RAM endpoint must be an HTTPS URL.") from error
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise PluginError(
            "configuration_invalid",
            "Use an HTTPS endpoint without credentials, query parameters, or fragments.",
        )

    for name in ("RAM_STORE_ID", "RAM_NAMESPACE", "RAM_PARTICIPANT"):
        if not SLUG.fullmatch((values[name] or "").strip()):
            raise PluginError(
                "configuration_invalid",
                f"{name} must contain 1–64 letters, digits, or hyphens.",
            )

    api_key = (values["RAM_API_KEY"] or "").strip()
    if api_key.startswith("__encrypted__:"):
        raise PluginError(
            "credential_unavailable",
            "The configured RAM credential is unavailable. Replace it in the local .env file.",
        )

    return Config(
        endpoint=endpoint.rstrip("/"),
        store_id=(values["RAM_STORE_ID"] or "").strip(),
        namespace=(values["RAM_NAMESPACE"] or "").strip(),
        participant=(values["RAM_PARTICIPANT"] or "").strip(),
        api_key=api_key,
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
