"""Tmux helpers: detect session and control per-pane mouse for TUI scroll/wheel support."""
import os
import subprocess
import sys
from typing import Optional

_TMUX_TIMEOUT_SEC = 2.0


def is_tmux() -> bool:
    """True when running inside a tmux session (``$TMUX`` is set)."""
    return bool(os.environ.get("TMUX"))


def _tmux_run(*args: str) -> Optional[str]:
    """Run ``tmux`` with the given arguments; return stdout on success, else None."""
    try:
        result = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=_TMUX_TIMEOUT_SEC,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout if result.stdout is not None else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def disable_pane_mouse() -> bool:
    """Turn off mouse for the current pane only so events reach the application TTY."""
    return _tmux_run("set-option", "-p", "mouse", "off") is not None


def unset_pane_mouse() -> bool:
    """Remove per-pane mouse override; pane inherits session/global default again."""
    return _tmux_run("set-option", "-p", "-u", "mouse") is not None


def send_mouse_enable_sequences() -> None:
    """Emit XTerm SGR mouse tracking enables (belt-and-suspenders for the TTY)."""
    sys.stdout.write("\033[?1000h")
    sys.stdout.write("\033[?1002h")
    sys.stdout.write("\033[?1003h")
    sys.stdout.write("\033[?1006h")
    sys.stdout.flush()
