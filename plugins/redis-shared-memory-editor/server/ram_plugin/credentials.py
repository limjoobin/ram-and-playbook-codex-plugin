"""Secure loading for the user-owned plugin credential file."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .config import Config, PluginError, SETTING_NAMES, load_config


def load_credential_file(path: Path) -> Config:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as error:
        raise PluginError(
            "configuration_missing",
            "Create the local Redis Shared Memory .env file before using this plugin.",
        ) from error
    except OSError as error:
        raise PluginError(
            "credential_file_invalid",
            "The local Redis Shared Memory .env must be a regular file, not a symlink.",
        ) from error

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PluginError(
                "credential_file_invalid",
                "The local Redis Shared Memory .env must be a regular file, not a symlink.",
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise PluginError(
                "credential_file_permissions",
                "Set the local Redis Shared Memory .env permissions to 0600.",
            )
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise PluginError(
                "credential_file_owner",
                "The local Redis Shared Memory .env must be owned by the current user.",
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            text = stream.read()
    except UnicodeError as error:
        raise PluginError(
            "credential_file_contents",
            "The local Redis Shared Memory .env must be UTF-8 text.",
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    allowed = set(SETTING_NAMES)
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        key, separator, value = line.partition("=")
        if not separator:
            value = ""
        if key not in allowed or key in values:
            raise PluginError(
                "credential_file_contents",
                "The local Redis Shared Memory .env contains an unexpected or duplicate setting.",
            )
        values[key] = value
    return load_config(values)
