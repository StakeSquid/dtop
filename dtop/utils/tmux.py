"""Tmux helpers: detect session and reinforce terminal mouse tracking for the TTY."""
import os
import sys


def is_tmux() -> bool:
    """True when running inside a tmux session (``$TMUX`` is set)."""
    return bool(os.environ.get("TMUX"))


def send_mouse_enable_sequences() -> None:
    """Emit XTerm SGR mouse tracking enables so tmux forwards events to the application."""
    sys.stdout.write("\033[?1000h")
    sys.stdout.write("\033[?1002h")
    sys.stdout.write("\033[?1003h")
    sys.stdout.write("\033[?1006h")
    sys.stdout.flush()
