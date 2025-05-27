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
DEFAULT_COLUMNS = [
    {"name": "NAME", "width": 25, "min_width": 15, "weight": 3, "align": "left"},
    {"name": "IMAGE", "width": 30, "min_width": 15, "weight": 2, "align": "left"},
    {"name": "STATUS", "width": 12, "min_width": 8, "weight": 1, "align": "left"},
    {"name": "CPU%", "width": 8, "min_width": 7, "weight": 0, "align": "right"},
    {"name": "MEM%", "width": 8, "min_width": 7, "weight": 0, "align": "right"},
    {"name": "NET I/O", "width": 20, "min_width": 16, "weight": 0, "align": "right"},
    {"name": "DISK I/O", "width": 20, "min_width": 16, "weight": 0, "align": "right"},
    {"name": "CREATED AT", "width": 21, "min_width": 19, "weight": 0, "align": "left"},
    {"name": "UPTIME", "width": 12, "min_width": 8, "weight": 0, "align": "right"}
]

def load_config():
    """Load column configuration from file or use defaults"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                columns = config.get('columns', DEFAULT_COLUMNS)
                
                # Check if DISK I/O column exists, if not add it
                has_disk_io = any(col['name'] == 'DISK I/O' for col in columns)
                if not has_disk_io:
                    # Find position after NET I/O
                    net_io_idx = next((i for i, col in enumerate(columns) if col['name'] == 'NET I/O'), -1)
                    if net_io_idx >= 0:
                        columns.insert(net_io_idx + 1, 
                            {"name": "DISK I/O", "width": 20, "min_width": 16, "weight": 0, "align": "right"})
                    else:
                        # Add before CREATED AT
                        created_idx = next((i for i, col in enumerate(columns) if col['name'] == 'CREATED AT'), len(columns))
                        columns.insert(created_idx,
                            {"name": "DISK I/O", "width": 20, "min_width": 16, "weight": 0, "align": "right"})
        else:
            columns = DEFAULT_COLUMNS.copy()
    except Exception:
        # If any error occurs, use defaults
        columns = DEFAULT_COLUMNS.copy()
    
    # Ensure at least minimum widths
    for col in columns:
        col['width'] = max(col['width'], col['min_width'])
    
    return columns

def save_config(columns):
    """Save column configuration to file"""
    try:
        config = {
            'columns': columns
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception:
        # Ignore errors in saving config
        pass
