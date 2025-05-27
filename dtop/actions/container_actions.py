#!/usr/bin/env python3
"""
Docker TUI - Container Actions Module
-----------
Handles container actions menu and operations.
"""
import curses
import subprocess
import time
from ..utils.utils import safe_addstr

def show_menu(tui, stdscr, container):
    """Show action menu for container with arrow key navigation"""
    try:
        # Determine available actions based on container state
        is_running = container.status == "running"
        is_paused = container.status == "paused"
        
        # Build menu options with keys, labels, and availability
        opts = []
        opts.append(("L", "Logs", True))
        opts.append(("I", "Inspect", True))  # Always available
        opts.append(("S", "Stop" if is_running else "Start", True))
        opts.append(("P", "Unpause" if is_paused else "Pause", is_running and not is_paused))
        opts.append(("R", "Restart", is_running))
        opts.append(("F", "Recreate", True))
        opts.append(("E", "Exec Shell", is_running))
        opts.append(("C", "Cancel", True))
        
        # Calculate dimensions
        h, w = stdscr.getmaxyx()
        menu_width = 30
        menu_height = len(opts) + 4
        
        # Create menu in top-left corner with border
        menu = curses.newwin(menu_height, menu_width, 1, 0)
        menu.keypad(True)  # Enable keypad for arrow keys
        menu.border()
        
        # Draw title
        title = f" Container: {container.name[:20]} "
        safe_addstr(menu, 0, (menu_width - len(title))//2, title)
        
        # Current selection
        current = 0
        
        # Menu loop
        while True:
            # Draw all options
            for i, (key, label, enabled) in enumerate(opts):
                # Format option text
                text = f"{key}: {label}"
                
                # Determine attributes
                if i == current and enabled:
                    attr = curses.color_pair(7) | curses.A_BOLD
                elif i == current:
                    attr = curses.color_pair(6) | curses.A_DIM
                elif enabled:
                    attr = curses.A_NORMAL
                else:
                    attr = curses.A_DIM
                
                # Draw option
                safe_addstr(menu, i + 2, 2, " " * (menu_width - 4), curses.A_NORMAL)
                safe_addstr(menu, i + 2, 2, text, attr)
            
            # Draw help
            help_text = "↑/↓:Navigate | Enter/Click:Select | ESC:Cancel"
            safe_addstr(menu, menu_height - 1, (menu_width - len(help_text))//2, help_text, curses.A_DIM)
            
            menu.refresh()
            
            # Handle input
            c = menu.getch()
            
            if c == curses.KEY_UP and current > 0:
                current = (current - 1) % len(opts)
                # Skip disabled options
                while not opts[current][2] and current > 0:
                    current = (current - 1) % len(opts)
            
            elif c == curses.KEY_DOWN and current < len(opts) - 1:
                current = (current + 1) % len(opts)
                # Skip disabled options
                while not opts[current][2] and current < len(opts) - 1:
                    current = (current + 1) % len(opts)
            
            elif c in (10, curses.KEY_ENTER) and opts[current][2]:
                # Selected an enabled option
                action_key = opts[current][0].lower()
                break
            
            elif c == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, button_state = curses.getmouse()
                    if button_state & curses.BUTTON1_CLICKED:
                        # Check if click was on a menu item
                        for i, (_, _, enabled) in enumerate(opts):
                            if my == i + 2 and enabled:
                                action_key = opts[i][0].lower()
                                break
                        else:
                            # Click not on menu item, continue loop
                            continue
                        break
                except curses.error:
                    pass
            
            elif c == 27:  # ESC
                action_key = 'c'  # Cancel
                break
            
            elif c in range(97, 123):  # a-z
                action_key = chr(c)
                # Check if this key is a valid shortcut
                for key, _, enabled in opts:
                    if key.lower() == action_key and enabled:
                        break
                else:
                    # Not a valid shortcut, continue loop
                    continue
                break
            
            elif c in range(65, 91):  # A-Z
                action_key = chr(c).lower()
                # Check if this key is a valid shortcut
                for key, _, enabled in opts:
                    if key.lower() == action_key and enabled:
                        break
                else:
                    # Not a valid shortcut, continue loop
                    continue
                break
        
        # Clean up
        del menu
        stdscr.touchwin()
        stdscr.refresh()
        
        # Return selected action
        return action_key
                
    except Exception as e:
        # Show error and wait for key
        h, w = stdscr.getmaxyx()
        stdscr.clear()
        safe_addstr(stdscr, h//2, (w-len(str(e))-10)//2, f"Error: {e}", curses.A_BOLD)
        safe_addstr(stdscr, h//2+1, (w-25)//2, "Press any key to continue...", curses.A_DIM)
        stdscr.refresh()
        stdscr.getch()
        return 'c'  # Return cancel on error

def execute_action(tui, stdscr, container, action_key):
    """Execute the selected container action"""
    # Import here to avoid circular imports
    from ..views import log_view
    from ..views import inspect_view
    
    if action_key == 'l':
        log_view.show_logs(tui, stdscr, container)
    elif action_key == 'i':  # Use the new inspect_view module
        inspect_view.show_inspect(tui, stdscr, container)
    elif action_key == 's':
        if container.status == "running": 
            container.stop()
        else: 
            container.start()
    elif action_key == 'p':
        if container.status == "paused":
            container.unpause() 
        elif container.status == "running":
            container.pause()
    elif action_key == 'r' and container.status == "running":
        container.restart()
    elif action_key == 'f':
        img = container.image.tags[0] if container.image.tags else container.image.short_id
        container.remove(force=True)
        tui.client.containers.run(img, detach=True)
    elif action_key == 'e' and container.status == "running":
        curses.endwin()
        subprocess.call(["docker","exec","-it",container.id,"/bin/bash"])
        stdscr.clear()
        curses.doupdate()
    # 'c' (cancel) does nothing
