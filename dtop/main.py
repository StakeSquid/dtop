#!/usr/bin/env python3
"""
dtop - Docker Terminal UI Entry Point
"""
import curses
import docker
import sys
import atexit


def cleanup():
    """Cleanup function to ensure stats are properly cleaned up"""
    try:
        from .core.stats import cleanup_stats_sync
        cleanup_stats_sync()
    except:
        pass


def main():
    """Main entry point for dtop"""
    # Enable automatic garbage collection optimization
    import gc
    gc.set_threshold(700, 10, 10)  # More aggressive GC
    
    # Register cleanup function
    atexit.register(cleanup)
    
    # Import our modules
    try:
        from . import DockerTUI
        curses.wrapper(DockerTUI().draw)
    except docker.errors.DockerException as e:
        print("Error connecting to Docker daemon:", e)
        print("Make sure Docker is running and you have access to /var/run/docker.sock")
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        pass
    except Exception as e:
        print(f"Unexpected error: {e}")
        print("If the screen isn't restoring properly, try: reset")
    finally:
        # Ensure cleanup happens
        cleanup()


if __name__ == '__main__':
    main()