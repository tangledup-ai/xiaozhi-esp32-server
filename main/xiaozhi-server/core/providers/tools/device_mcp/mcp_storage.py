"""Persistence helpers for device MCP tools (self_* tools).

These are used so the MCP tool server can restore previously registered
device MCP tools without a live device session.

Device tool profiles are stored in data/device_mcp_tools/<profile>.json

Profiles are automatically created based on toolset fingerprints - devices
with identical tool sets share the same profile.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import List, Optional, Tuple

from config.config_loader import get_project_dir

# Default profile name (None means auto-select first available)
DEFAULT_PROFILE = None


def _get_profiles_dir() -> str:
    """Return the directory where device tool profiles are stored."""
    base = get_project_dir()
    return os.path.join(base, "data", "device_mcp_tools")


def _storage_path(profile: str) -> str:
    """Return the path to a specific profile's JSON file.
    
    Note: profile must not be None - resolve it first using get_first_available_profile().
    """
    profiles_dir = _get_profiles_dir()
    return os.path.join(profiles_dir, f"{profile}.json")


def compute_toolset_fingerprint(tools: List[dict]) -> str:
    """Compute a fingerprint for a set of tools.
    
    The fingerprint is based on tool names and their input schemas,
    so devices with the same tools get the same fingerprint.
    Returns a short hash string.
    """
    if not tools:
        return "empty"
    
    # Extract canonical representation: sorted list of (name, schema_json)
    canonical = []
    for tool in tools:
        name = tool.get("name", "")
        # Get inputSchema, normalize it
        schema = tool.get("inputSchema", {})
        # Sort keys for consistent hashing
        schema_json = json.dumps(schema, sort_keys=True, ensure_ascii=False)
        canonical.append((name, schema_json))
    
    # Sort by name for consistent ordering
    canonical.sort(key=lambda x: x[0])
    
    # Create a string representation and hash it
    content = json.dumps(canonical, ensure_ascii=False)
    hash_obj = hashlib.sha256(content.encode("utf-8"))
    # Use first 12 chars of hex digest for readability
    return hash_obj.hexdigest()[:12]


def _generate_profile_name(tools: List[dict]) -> str:
    """Generate a profile name based on the toolset.
    
    Uses tool names to create a human-readable prefix, plus a fingerprint.
    """
    fingerprint = compute_toolset_fingerprint(tools)
    
    if not tools:
        return f"empty_{fingerprint}"
    
    # Create a readable prefix from tool names
    tool_names = sorted(t.get("name", "") for t in tools if t.get("name"))
    
    # Take first tool name, clean it up for filename
    if tool_names:
        first_name = tool_names[0]
        # Remove "self." prefix if present
        if first_name.startswith("self."):
            first_name = first_name[5:]
        # Take first part before any dot
        prefix = first_name.split(".")[0]
        # Clean for filename (alphanumeric and underscore only)
        prefix = "".join(c if c.isalnum() else "_" for c in prefix)
        prefix = prefix[:20]  # Limit length
    else:
        prefix = "tools"
    
    return f"{prefix}_{len(tools)}tools_{fingerprint}"


def get_available_profiles() -> List[str]:
    """List all available device tool profiles.
    
    Returns a list of profile names (without .json extension) that actually exist.
    """
    profiles_dir = _get_profiles_dir()
    profiles = set()
    
    # Check the profiles directory
    if os.path.isdir(profiles_dir):
        for filename in os.listdir(profiles_dir):
            if filename.endswith(".json"):
                profiles.add(filename[:-5])  # Remove .json extension
    
    return sorted(profiles)


def get_first_available_profile() -> Optional[str]:
    """Get the first available profile that has tools.
    
    Returns None if no profiles with tools exist.
    """
    profiles = get_available_profiles()
    
    if not profiles:
        return None
    
    # Return the first one (sorted alphabetically)
    return profiles[0]


def find_profile_by_fingerprint(tools: List[dict]) -> Optional[str]:
    """Find an existing profile that matches the given toolset fingerprint.
    
    Returns the profile name if found, None otherwise.
    """
    if not tools:
        return None
    
    target_fingerprint = compute_toolset_fingerprint(tools)
    profiles_dir = _get_profiles_dir()
    
    if not os.path.isdir(profiles_dir):
        return None
    
    for filename in os.listdir(profiles_dir):
        if not filename.endswith(".json"):
            continue
        
        profile_path = os.path.join(profiles_dir, filename)
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                existing_tools = json.load(f)
            if isinstance(existing_tools, list):
                existing_fingerprint = compute_toolset_fingerprint(existing_tools)
                if existing_fingerprint == target_fingerprint:
                    return filename[:-5]  # Remove .json
        except Exception:
            continue
    
    return None


def save_device_tools(
    tools: List[dict], 
    profile: Optional[str] = None,
    auto_profile: bool = False
) -> Tuple[str, bool]:
    """Persist device MCP tools to disk.
    
    Args:
        tools: List of tool definitions to save
        profile: Explicit profile name to use (if not auto_profile)
        auto_profile: If True, automatically find or create a profile based on toolset
        
    Returns:
        Tuple of (profile_name, is_new_profile)
    """
    if not tools:
        return (DEFAULT_PROFILE, False)
    
    is_new = False
    
    if auto_profile:
        # Check if a profile with this exact toolset already exists
        existing_profile = find_profile_by_fingerprint(tools)
        if existing_profile:
            profile = existing_profile
        else:
            # Generate a new profile name
            profile = _generate_profile_name(tools)
            is_new = True
    elif profile is None:
        profile = DEFAULT_PROFILE
    
    path = _storage_path(profile)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tools, f, ensure_ascii=False, indent=2)
    
    return (profile, is_new)


def load_device_tools(profile: Optional[str] = None) -> Tuple[List[dict], Optional[str]]:
    """Load persisted device MCP tools for a specific profile.
    
    Args:
        profile: Profile name to load. If None, auto-selects the first available profile.
        
    Returns:
        Tuple of (tools_list, actual_profile_name).
        If no profiles exist, returns ([], None).
    """
    profiles_dir = _get_profiles_dir()
    
    # Ensure the profiles directory exists
    os.makedirs(profiles_dir, exist_ok=True)
    
    # Auto-select profile if None
    if profile is None:
        profile = get_first_available_profile()
        if profile is None:
            # No profiles available at all
            return ([], None)
    
    path = _storage_path(profile)
    
    if not os.path.exists(path):
        return ([], None)
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return ([d for d in data if isinstance(d, dict)], profile)
        return ([], profile)
    except Exception:
        return ([], profile)






