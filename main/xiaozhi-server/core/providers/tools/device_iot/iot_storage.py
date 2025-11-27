"""Persistence helpers for IoT descriptors.

Used so the MCP tool server and other components can restore IoT tools
without requiring a live device websocket session.
"""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any

from config.config_loader import get_project_dir


def _storage_path() -> str:
    """Return the file path where IoT descriptors are stored."""
    base = get_project_dir()
    return os.path.join(base, "data", "iot_descriptors.json")


def save_descriptors(descriptors: List[Dict[str, Any]]) -> None:
    """Persist IoT descriptors to disk.

    Args:
        descriptors: List of descriptor dicts as used by handleIotDescriptors.
    """
    if not descriptors:
        return

    path = _storage_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(descriptors, f, ensure_ascii=False, indent=2)


def load_descriptors() -> List[Dict[str, Any]]:
    """Load persisted IoT descriptors if present.

    Returns:
        A list of descriptor dicts, or [] if nothing is stored/invalid.
    """
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
        # On any error (corrupt file, bad JSON, etc.) just ignore and return empty.
        return []