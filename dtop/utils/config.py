#!/usr/bin/env python3
"""
Docker TUI - Configuration Module
-----------
Handles loading and saving of TUI configuration.
"""
import os
import json

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


def load_theme():
    """Load theme name from config, default to textual-dark."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('theme', DEFAULT_THEME)
    except Exception:
        pass
    return DEFAULT_THEME


def save_theme(theme_name):
    """Save theme name to config without touching other keys."""
    try:
        existing = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                existing = json.load(f)
        existing['theme'] = theme_name
        with open(CONFIG_FILE, 'w') as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass
