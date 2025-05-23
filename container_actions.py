#!/usr/bin/env python3
"""
Docker TUI - Container Actions Module
-----------
Handles container actions menu and operations.
"""
import curses
import subprocess
import json
import time
from utils import safe_addstr

def show_menu(tui, stdscr, container):
    """Show action menu for container with arrow key navigation"""
    try:
        # Determine available actions based on container state
        is_running = container.status == "running"
        is_paused = container.status == "paused"
        
        # Build menu options with keys, labels, and availability
        opts = []
        opts.append(("L", "Logs", True))
        opts.append(("I", "Inspect", True))  # NEW: Docker inspect option
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

def show_inspect(tui, stdscr, container):
    """Display container inspect information in a scrollable view"""
    try:
        # Get terminal size
        h, w = stdscr.getmaxyx()
        
        # Clear and show loading message
        stdscr.clear()
        safe_addstr(stdscr, h//2, (w-30)//2, "Loading inspect data, please wait...", curses.A_BOLD)
        stdscr.refresh()
        
        # Get inspect data
        inspect_data = container.attrs
        
        # Format JSON with nice indentation
        json_text = json.dumps(inspect_data, indent=2, default=str)
        lines = json_text.splitlines()
        
        # Create a pad for scrolling
        pad_height = max(len(lines) + 10, h)
        pad_width = max(w - 2, max(len(line) for line in lines) + 10)
        pad = curses.newpad(pad_height, pad_width)
        
        # Fill pad with inspect data
        for i, line in enumerate(lines):
            try:
                pad.addstr(i, 0, line)
            except curses.error:
                pass
        
        # Scrolling variables
        pos = 0
        h_scroll = 0
        max_line_length = max(len(line) for line in lines) if lines else 0
        
        # Set up non-blocking input
        stdscr.nodelay(True)
        
        # Draw the static UI elements once
        stdscr.clear()
        
        # Draw header with background color
        stdscr.attron(curses.color_pair(5))
        safe_addstr(stdscr, 0, 0, " " * w)
        header_text = f" Inspect: {container.name} "
        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
        stdscr.attroff(curses.color_pair(5))
        
        # Draw footer with help
        footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | PgUp/Dn:Page | Home/End:Top/Bottom | ESC/Q:Back "
        stdscr.attron(curses.color_pair(6))
        safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
        stdscr.attroff(curses.color_pair(6))
        
        # Initial display of dynamic elements
        line_info = f" Line: {pos+1}/{len(lines)} "
        safe_addstr(stdscr, 1, w-len(line_info)-1, line_info)
        
        # Clear the content area to ensure clean display
        for i in range(2, h-1):  # Clear content area (between header and footer)
            safe_addstr(stdscr, i, 0, " " * (w-1))
        
        # Important: Refresh the screen FIRST (including the cleared area), then the pad
        stdscr.refresh()
        
        # Then display the pad content
        try:
            pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
        except curses.error:
            pass
        
        # Main viewing loop
        running = True
        
        while running:
            # Handle input with timeout
            stdscr.timeout(100)  # 100ms timeout
            key = stdscr.getch()
            
            if key != -1:  # Key was pressed
                if key == curses.KEY_DOWN:
                    if pos < len(lines) - 1:
                        pos += 1
                elif key == curses.KEY_UP:
                    if pos > 0:
                        pos -= 1
                elif key == curses.KEY_NPAGE:  # Page Down
                    pos = min(len(lines) - 1, pos + (h-5))
                elif key == curses.KEY_PPAGE:  # Page Up
                    pos = max(0, pos - (h-5))
                elif key == curses.KEY_RIGHT:  # Right arrow for horizontal scroll
                    h_scroll = min(h_scroll + 10, max_line_length - (w - 5))
                    h_scroll = max(0, h_scroll)
                elif key == curses.KEY_LEFT:  # Left arrow for horizontal scroll
                    h_scroll = max(0, h_scroll - 10)
                elif key == curses.KEY_HOME:  # Home - go to start
                    pos = 0
                    h_scroll = 0
                elif key == curses.KEY_END:  # End - go to end
                    pos = max(0, len(lines) - (h-4))
                elif key == curses.KEY_MOUSE:
                    try:
                        _, mx, my, _, button_state = curses.getmouse()
                        # Scroll with mouse wheel
                        if button_state & curses.BUTTON4_PRESSED:  # Wheel up
                            pos = max(0, pos - 3)
                        elif button_state & curses.BUTTON5_PRESSED:  # Wheel down
                            pos = min(len(lines) - 1, pos + 3)
                    except curses.error:
                        pass
                elif key in (27, ord('q'), ord('Q')):  # ESC or Q to exit
                    running = False
                    continue
                
                # Update only the dynamic elements - line counter and position info
                line_info = f" Line: {pos+1}/{len(lines)} "
                safe_addstr(stdscr, 1, w-len(line_info)-1, line_info)
                
                # Clear and update horizontal position info
                safe_addstr(stdscr, 1, 0, " " * 15)  # Clear previous position info
                if h_scroll > 0:
                    h_pos_info = f" Col: {h_scroll+1} "
                    safe_addstr(stdscr, 1, 0, h_pos_info)
                
                # Clear the content area first to prevent old text showing through
                for i in range(2, h-1):  # Clear content area (between header and footer)
                    safe_addstr(stdscr, i, 0, " " * (w-1))
                
                # Refresh screen elements first (including cleared content area)
                stdscr.refresh()
                
                # Then refresh the pad content
                try:
                    pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
                except curses.error:
                    pass
    
    except Exception as e:
        # Show error and wait for key
        stdscr.clear()
        safe_addstr(stdscr, h//2, (w-len(str(e))-10)//2, f"Error: {e}", curses.A_BOLD)
        safe_addstr(stdscr, h//2+1, (w-25)//2, "Press any key to continue...", curses.A_DIM)
        stdscr.refresh()
        stdscr.getch()
    
    finally:
        # Restore screen state
        stdscr.clear()
        stdscr.nodelay(True)  # Restore non-blocking mode for main TUI
        stdscr.refresh()

def execute_action(tui, stdscr, container, action_key):
    """Execute the selected container action"""
    # Import here to avoid circular imports
    import log_view
    
    if action_key == 'l':
        log_view.show_logs(tui, stdscr, container)
    elif action_key == 'i':  # NEW: Handle inspect action
        show_inspect(tui, stdscr, container)
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
