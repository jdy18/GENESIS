"""Access declarations for models and configured retrieval tools."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfiguredTool:
    """Attach a source name, switch and access declaration to a tool adapter.

    The backend implements the existing tool protocol. A local MCP endpoint
    that forwards requests to public services still requires external access.
    """

    backend: Any
    name: str
    requires_external_access: bool
    enabled: bool = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)


def tool_allowed(tool: Any, allow_external_requests: bool) -> bool:
    """Undeclared tools are omitted when external requests are disabled."""
    return (
        getattr(tool, "enabled", True) is True
        and (
            allow_external_requests
            or getattr(tool, "requires_external_access", None) is False
        )
    )


def require_local_model(model: Any, role: str) -> None:
    """Validate before any patient information is sent to a model."""
    if model is not None and getattr(model, "requires_external_access", None) is not False:
        raise ValueError(
            f"{role} must declare requires_external_access=False when "
            "allow_external_requests=False. Use a locally hosted model."
        )
