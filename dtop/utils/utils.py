#!/usr/bin/env python3
"""
Docker TUI - Utility Functions
-----------
Shared formatting and helper functions for the Docker TUI.
"""
import curses
import datetime
from typing import Dict, Optional

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


def _looks_like_image_digest(s: str) -> bool:
    s = (s or "").strip()
    if s.startswith("sha256:") and len(s) > 15:
        return True
    if len(s) == 64 and all(c in "0123456789abcdef" for c in s.lower()):
        return True
    return False


def _resolve_digest_with_repo_map(
    raw: str, repo_by_digest: Dict[str, str]
) -> Optional[str]:
    """Return a repo:tag if raw matches a known local image digest key."""
    raw = (raw or "").strip()
    if raw in repo_by_digest:
        return repo_by_digest[raw]
    if raw.startswith("sha256:"):
        tail = raw[7:]
        if tail in repo_by_digest:
            return repo_by_digest[tail]
    else:
        prefixed = f"sha256:{raw}"
        if prefixed in repo_by_digest:
            return repo_by_digest[prefixed]
    return None


def _raw_image_reference_from_attrs(attrs: dict) -> str:
    """Prefer user-facing reference: Config.Image, then list Image, then ImageID."""
    cfg = attrs.get("Config")
    if isinstance(cfg, dict):
        cimg = cfg.get("Image")
        if cimg:
            return str(cimg)
    img = attrs.get("Image")
    if img:
        return str(img)
    iid = attrs.get("ImageID")
    if iid:
        return str(iid)
    return ""


def container_image_label(
    container, repo_by_digest: Optional[Dict[str, str]] = None
) -> str:
    """Image string from attrs; optional digest→repo map from a one-time images.list.

    Avoids docker-py's lazy ``container.image`` (per-row ``images.get``).
    """
    try:
        attrs = getattr(container, "attrs", None)
        if not isinstance(attrs, dict):
            return "<none>"
        raw = _raw_image_reference_from_attrs(attrs)
        if not raw:
            return "<none>"
        if repo_by_digest and _looks_like_image_digest(raw):
            resolved = _resolve_digest_with_repo_map(raw, repo_by_digest)
            if resolved:
                return resolved
        return raw
    except Exception:
        pass
    return "<none>"


def build_image_repo_by_digest(client) -> Dict[str, str]:
    """Map digest variants to a short repo:tag using one ``client.images.list()`` call."""
    out: Dict[str, str] = {}
    try:
        for image in client.images.list():
            tags = list(getattr(image, "tags", None) or [])
            if not tags:
                continue
            tag = min(tags, key=len)
            img_id = getattr(image, "id", "") or ""
            if not img_id:
                continue
            variants = {img_id.strip()}
            if img_id.startswith("sha256:"):
                variants.add(img_id[7:].strip())
            elif len(img_id) == 64 and all(
                c in "0123456789abcdef" for c in img_id.lower()
            ):
                variants.add(f"sha256:{img_id}")
            for v in variants:
                if v and v not in out:
                    out[v] = tag
    except Exception:
        pass
    return out

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
