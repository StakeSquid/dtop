#!/usr/bin/env python3
"""
Docker TUI - Utility Functions
-----------
Shared formatting and helper functions for the Docker TUI.
"""
import curses
import datetime

def format_timedelta(td):
    """Format a timedelta into HH:MM:SS format"""
    seconds = int(td.total_seconds())
    hours, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hours:02}:{mins:02}:{secs:02}"

def format_bytes(num_bytes, suffix='B'):
    """Format bytes into human-readable format with units"""
    for unit in ['', 'K', 'M', 'G', 'T', 'P']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f}{unit}{suffix}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}Y{suffix}"

def get_speed_color(bytes_per_sec):
    """Get color pair for speed based on bytes per second
    Returns curses color pair number:
    - 11: Green for KB/s (< 1MB/s)
    - 12: Yellow for MB/s (1MB/s - 300MB/s)
    - 13: Dark orange for 300MB/s+ (300MB/s - 1GB/s)
    - 14: Red for GB/s (>= 1GB/s)
    """
    if bytes_per_sec < 1024 * 1024:  # < 1 MB/s
        return 11  # Green
    elif bytes_per_sec < 300 * 1024 * 1024:  # < 300 MB/s
        return 12  # Yellow
    elif bytes_per_sec < 1024 * 1024 * 1024:  # < 1 GB/s
        return 13  # Dark orange
    else:  # >= 1 GB/s
        return 14  # Red

def format_datetime(dt_str):
    """Format ISO datetime string to human-readable format"""
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return dt_str

def format_column(text, width, align='left'):
    """Format text to fit in column with padding"""
    text_str = str(text)
    if len(text_str) > width - 2:
        text_str = text_str[:width - 3] + "…"
    
    if align == 'left':
        return text_str.ljust(width - 1) + " "
    elif align == 'right':
        return " " + text_str.rjust(width - 1)
    else:  # center
        return text_str.center(width)

def safe_addstr(win, y, x, text, attr=0):
    """Add string only if within bounds; ignore errors"""
    h, w = win.getmaxyx()
    if 0 <= y < h and x < w:
        try:
            # Convert to string and truncate
            text_str = str(text)[:max(0, w-x)]
            win.addstr(y, x, text_str, attr)
        except curses.error:
            pass
