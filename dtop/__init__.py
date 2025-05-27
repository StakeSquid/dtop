"""
dtop - Docker Terminal UI
A high-performance terminal UI for Docker container management.
"""

__version__ = "1.0.0"
__author__ = "StakeSquid"
__description__ = "A high-performance terminal UI for Docker container management"

from .core.docker_tui import DockerTUI

__all__ = ["DockerTUI"]