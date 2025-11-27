"""Persistence helpers for device MCP tools (self_* tools).

These are used so the MCP tool server can restore previously registered
device MCP tools without a live device session.
"""

from __future__ import annotations

import json
import os
from typing import Any, List

from config.config_loader import get_project_dir


def _storage_path() -> str:
    base = get_project_dir()
    return os.path.join(base, "data", "device_mcp_tools.json")


def save_device_tools(tools: List[dict]) -> None:
    """Persist device MCP tools to disk."""
    if not tools:
        return
    path = _storage_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tools, f, ensure_ascii=False, indent=2)


def load_device_tools() -> List[dict]:
    """Load persisted device MCP tools if present."""
    path = _storage_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []
    except Exception:
        return []






