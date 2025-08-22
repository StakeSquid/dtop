#!/usr/bin/env python3
"""
dtop - Docker Terminal UI Entry Point
"""
import sys
import os
import docker
import argparse


def main():
    """Main entry point for dtop"""
    parser = argparse.ArgumentParser(description='Docker Terminal UI')
    parser.add_argument(
        '--legacy',
        action='store_true',
        help='Use legacy curses interface instead of Textual'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    
    args = parser.parse_args()
    
    # Check if we should use legacy interface
    if args.legacy or os.environ.get('DTOP_LEGACY', '').lower() == 'true':
        # Use original curses interface
        import curses
        import atexit
        import gc
        
        def cleanup():
            """Cleanup function to ensure stats are properly cleaned up"""
            try:
                from .core.stats import cleanup_stats_sync
                cleanup_stats_sync()
            except:
                pass
        
        # Enable automatic garbage collection optimization
        gc.set_threshold(700, 10, 10)
        
        # Register cleanup function
        atexit.register(cleanup)
        
        try:
            from .core.docker_tui import DockerTUI
            curses.wrapper(DockerTUI().draw)
        except docker.errors.DockerException as e:
            print("Error connecting to Docker daemon:", e)
            print("Make sure Docker is running and you have access to /var/run/docker.sock")
            sys.exit(1)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Unexpected error: {e}")
            print("If the screen isn't restoring properly, try: reset")
            sys.exit(1)
        finally:
            cleanup()
    else:
        # Use new Textual interface (default)
        try:
            from .core.textual_docker_tui import DockerTUIApp
            
            app = DockerTUIApp()
            
            # Enable debug mode if requested
            if args.debug:
                app.run(debug=True)
            else:
                app.run()
                
        except ImportError as e:
            print(f"Error: Textual is not installed. {e}")
            print("Install with: pip install textual rich")
            print("Or use --legacy flag to use the curses interface")
            sys.exit(1)
        except docker.errors.DockerException as e:
            print("Error connecting to Docker daemon:", e)
            print("Make sure Docker is running and you have access to /var/run/docker.sock")
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            if args.debug:
                import traceback
                traceback.print_exc()
            else:
                print(f"Error: {e}")
                print("Run with --debug for more information")
            sys.exit(1)


if __name__ == '__main__':
    main()