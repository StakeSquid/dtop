"""
dtop - Docker Terminal UI
A high-performance terminal UI for Docker container management.
"""

__version__ = "2.2.0"
__author__ = "StakeSquid"
__description__ = "A high-performance terminal UI for Docker container management"

# Import based on available interface
try:
    from .core.textual_docker_tui import DockerTUIApp
    __all__ = ["DockerTUIApp", "DockerTUI"]
except ImportError:
    # Fallback to curses if Textual not available
    pass

# Always expose the legacy interface
from .core.docker_tui import DockerTUI

__all__ = __all__ if '__all__' in locals() else ["DockerTUI"]
