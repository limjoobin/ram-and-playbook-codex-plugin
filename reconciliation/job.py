"""Administrator entry point onto the plugin's reconciliation code.

The plugin ships the same projector and policy, byte for byte, so a confirmed
promotion can update the current view at once. This wrapper runs that code with
the versioned context-model bundle instead.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

_SERVER_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "redis-shared-memory-editor" / "server"
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from ram_plugin.reconcile import (  # noqa: E402
    OBSERVATION_SCHEMA,
    OBSERVATION_SCHEMAS,
    OBSERVATION_TYPE,
    PROJECTION_SCHEMA,
    PROJECTION_TYPE,
    ReconciliationError,
    ReconciliationJob as _PluginJob,
    adopt_unnamespaced,
    move_into_namespace,
)

__all__ = [
    "OBSERVATION_SCHEMA",
    "OBSERVATION_SCHEMAS",
    "OBSERVATION_TYPE",
    "PROJECTION_SCHEMA",
    "PROJECTION_TYPE",
    "ReconciliationError",
    "ReconciliationJob",
    "adopt_unnamespaced",
    "move_into_namespace",
]


class ReconciliationJob(_PluginJob):
    """The plugin job, driven by the bundle's projector and policy."""

    def __init__(self, config: Any, ram: Any, bundle: Any) -> None:
        super().__init__(config, ram, bundle.projector(), bundle.projection_policy())
        self.bundle = bundle
