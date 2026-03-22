#!/usr/bin/env python3
"""
Docker TUI - Configuration Module
-----------
Handles loading and saving of TUI configuration.
"""
import os
import json
from typing import Any, Dict, Optional

# Configuration file path in user's home directory
CONFIG_FILE = os.path.expanduser("~/.docker_tui.json")

# Default column configuration
# width/min_width/max_width are measured in monospace character cells.
DEFAULT_COLUMNS = [
    {"name": "NAME", "width": 25, "min_width": 15, "max_width": None, "weight": 3, "align": "left"},
    {"name": "IMAGE", "width": 30, "min_width": 15, "max_width": 50, "weight": 2, "align": "left"},
    {"name": "STATUS", "width": 12, "min_width": 8,  "max_width": 20, "weight": 1, "align": "left"},
    {"name": "CPU%", "width": 8,  "min_width": 7,  "max_width": 10, "weight": 0, "align": "right"},
    {"name": "MEM%", "width": 8,  "min_width": 7,  "max_width": 10, "weight": 0, "align": "right"},
    {"name": "NET I/O", "width": 20, "min_width": 16, "max_width": 26, "weight": 0, "align": "right"},
    {"name": "DISK I/O", "width": 20, "min_width": 16, "max_width": 26, "weight": 0, "align": "right"},
    {"name": "CREATED AT", "width": 21, "min_width": 19, "max_width": 30, "weight": 0, "align": "left"},
    {"name": "UPTIME", "width": 12, "min_width": 8,  "max_width": 16, "weight": 0, "align": "right"},
]

def _merge_with_defaults(columns):
    """Ensure loaded columns include required keys and sensible bounds.

    - Adds any missing columns (e.g., new ones in newer versions)
    - Adds missing keys like min_width/max_width/weight/align/width
    - Ensures width >= min_width and width <= max_width (when provided)
    """
    # Map defaults by name for lookup
    defaults_by_name = {c["name"]: c for c in DEFAULT_COLUMNS}

    # Start with given columns, ensure each has required keys
    merged = []
    for col in columns:
        name = col.get("name")
        if not name:
            # Skip unnamed columns
            continue
        base = defaults_by_name.get(name, {})
        merged_col = {
            "name": name,
            "width": col.get("width", base.get("width", 20)),
            "min_width": col.get("min_width", base.get("min_width", 8)),
            "max_width": col.get("max_width", base.get("max_width", None)),
            "weight": col.get("weight", base.get("weight", 0)),
            "align": col.get("align", base.get("align", "left")),
        }
        # Clamp width inside [min, max]
        try:
            w = int(merged_col["width"])
            mn = int(merged_col["min_width"]) if merged_col.get("min_width") is not None else w
            mx = int(merged_col["max_width"]) if merged_col.get("max_width") is not None else None
            w = max(w, mn)
            if mx is not None:
                w = min(w, mx)
            merged_col["width"] = w
        except Exception:
            # Fallback to default width
            merged_col["width"] = base.get("width", 20)
        merged.append(merged_col)

    # Ensure any new default columns are present (preserve original order as much as possible)
    existing_names = {c["name"] for c in merged}
    for idx, def_col in enumerate(DEFAULT_COLUMNS):
        if def_col["name"] not in existing_names:
            # Try to insert next to related column (e.g., after NET I/O for DISK I/O)
            if def_col["name"] == "DISK I/O":
                try:
                    net_idx = next(i for i, c in enumerate(merged) if c["name"] == "NET I/O")
                    merged.insert(net_idx + 1, def_col.copy())
                except StopIteration:
                    merged.append(def_col.copy())
            else:
                merged.append(def_col.copy())

    return merged

def load_config():
    """Load column configuration from file or use defaults"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                columns = config.get('columns', DEFAULT_COLUMNS)
                # Merge with defaults to ensure new keys/columns exist
                columns = _merge_with_defaults(columns)
        else:
            columns = [c.copy() for c in DEFAULT_COLUMNS]
    except Exception:
        # If any error occurs, use defaults
        columns = DEFAULT_COLUMNS.copy()
    
    # Ensure at least minimum widths and respect max
    for col in columns:
        try:
            col['width'] = max(int(col['width']), int(col['min_width']))
            if col.get('max_width') is not None:
                col['width'] = min(int(col['width']), int(col['max_width']))
        except Exception:
            pass
    
    return columns

def save_config(columns):
    """Save column configuration to file"""
    try:
        # Preserve existing config keys (e.g. theme)
        existing = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                existing = json.load(f)
        existing['columns'] = columns
        with open(CONFIG_FILE, 'w') as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


DEFAULT_THEME = "textual-dark"
CUSTOM_THEME_NAME = "dtop-custom"

# App semantic colors used in runtime-generated rich/text styles.
DEFAULT_SEMANTIC_COLORS = {
    "status_running": "green",
    "status_stopped": "red",
    "status_paused": "yellow",
    "connection_ok": "green",
    "connection_error": "red",
    "warning_text": "yellow",
    "error_text": "red",
    "info_text": "blue",
    "muted_text": "dim",
    "timestamp_text": "dim cyan",
    "inspect_bool": "cyan",
    "inspect_number": "magenta",
    "inspect_string": "green",
    "search_highlight": "reverse yellow",
    "search_highlight_case": "reverse bold yellow",
}


def _read_existing_config() -> Dict[str, Any]:
    """Read config JSON, returning an empty dict on failure."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _write_config(config: Dict[str, Any]) -> None:
    """Write full config JSON, swallowing filesystem/serialization errors."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def load_theme():
    """Load theme name from config, default to textual-dark."""
    try:
        config = _read_existing_config()
        theme = config.get("theme", DEFAULT_THEME)
        return theme if isinstance(theme, str) and theme else DEFAULT_THEME
    except Exception:
        pass
    return DEFAULT_THEME


def save_theme(theme_name):
    """Save theme name to config without touching other keys."""
    try:
        existing = _read_existing_config()
        existing["theme"] = theme_name
        _write_config(existing)
    except Exception:
        pass


def _sanitize_theme_variables(variables: Any) -> Dict[str, str]:
    """Keep only string key/value variables for Textual Theme.variables."""
    if not isinstance(variables, dict):
        return {}
    cleaned: Dict[str, str] = {}
    for key, value in variables.items():
        if isinstance(key, str) and key and isinstance(value, str):
            cleaned[key] = value
    return cleaned


def _sanitize_semantic_colors(colors: Any) -> Dict[str, str]:
    """Return semantic runtime colors with defaults and user overrides."""
    out = DEFAULT_SEMANTIC_COLORS.copy()
    if not isinstance(colors, dict):
        return out
    for key, value in colors.items():
        if key in out and isinstance(value, str) and value:
            out[key] = value
    return out


def load_custom_theme() -> Optional[Dict[str, Any]]:
    """Load and normalize custom theme config, or None if not configured."""
    try:
        config = _read_existing_config()
        raw = config.get("custom_theme")
        if not isinstance(raw, dict):
            return None

        normalized: Dict[str, Any] = {}
        string_fields = (
            "primary",
            "secondary",
            "warning",
            "error",
            "success",
            "accent",
            "foreground",
            "background",
            "surface",
            "panel",
            "boost",
        )
        for field in string_fields:
            value = raw.get(field)
            if isinstance(value, str) and value:
                normalized[field] = value

        # Required by textual.theme.Theme
        normalized["primary"] = normalized.get("primary", "#0178D4")

        dark = raw.get("dark", True)
        normalized["dark"] = bool(dark)

        try:
            normalized["luminosity_spread"] = float(raw.get("luminosity_spread", 0.15))
        except Exception:
            normalized["luminosity_spread"] = 0.15

        try:
            normalized["text_alpha"] = float(raw.get("text_alpha", 0.95))
        except Exception:
            normalized["text_alpha"] = 0.95

        normalized["variables"] = _sanitize_theme_variables(raw.get("variables", {}))
        normalized["semantic_colors"] = _sanitize_semantic_colors(raw.get("semantic_colors", {}))
        return normalized
    except Exception:
        return None


def load_performance_settings() -> Dict[str, Any]:
    """Optional tuning for high-latency Docker (e.g. WSL2 + Docker Desktop).

    Reads ~/.docker_tui.json key ``performance``:
    - low_connection_mode (bool): use polling-only stats and smaller aiohttp pools.
    - max_concurrent_stats_streams (int|null): cap long-lived stats streams; excess
      containers use one-shot polling. Ignored when low_connection_mode is true.
    """
    try:
        cfg = _read_existing_config()
        perf = cfg.get("performance")
        if not isinstance(perf, dict):
            perf = {}
        low = bool(perf.get("low_connection_mode", False))
        raw_max = perf.get("max_concurrent_stats_streams")
        max_streams: Optional[int]
        if raw_max is None or raw_max == "":
            max_streams = None
        else:
            try:
                max_streams = int(raw_max)
                if max_streams < 1:
                    max_streams = None
            except (TypeError, ValueError):
                max_streams = None
        return {
            "low_connection_mode": low,
            "max_concurrent_stats_streams": None if low else max_streams,
        }
    except Exception:
        return {"low_connection_mode": False, "max_concurrent_stats_streams": None}


def save_custom_theme(custom_theme: Dict[str, Any], activate: bool = False) -> None:
    """Persist custom theme payload; optionally activate it as the current theme."""
    try:
        existing = _read_existing_config()
        existing["custom_theme"] = custom_theme
        if activate:
            existing["theme"] = CUSTOM_THEME_NAME
        _write_config(existing)
    except Exception:
        pass
