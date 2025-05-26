#!/usr/bin/env python3
"""
Docker TUI - Main Entry Point
-----------
Launches the Docker TUI application.

A high-performance terminal UI for managing Docker containers:
- Fast parallel stats collection
- Properly separated columns with resizable widths  
- Mouse support for navigation
- Reliable log display with normalization and line wrapping
- Text search in logs with highlighted results
- Log filtering (grep-like functionality)
- Configuration saving

Controls:
  - ↑/↓/Mouse    : Navigate containers
  - Enter/Click   : Show action menu
  - L            : View logs for selected container
  - F            : Toggle log follow mode
  - N            : Toggle log normalization
  - W            : Toggle log line wrapping
  - /            : Search in logs
  - \            : Filter logs (grep)
  - n/N          : Next/previous search result
  - Q            : Quit

Dependencies:
  pip install docker
"""
import curses
import docker
import sys
import atexit

def cleanup():
    """Cleanup function to ensure stats are properly cleaned up"""
    try:
        from stats import cleanup_stats_sync
        cleanup_stats_sync()
    except:
        pass

def main():
    # ADDED: Enable automatic garbage collection optimization
    import gc
    gc.set_threshold(700, 10, 10)  # More aggressive GC
    
    # Register cleanup function
    atexit.register(cleanup)
    
    # Determine the correct import paths
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    
    # Now import our modules
    try:
        from docker_tui import DockerTUI
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
