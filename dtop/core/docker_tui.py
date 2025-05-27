#!/usr/bin/env python3
"""
Docker TUI - Core Module
-----------
Main DockerTUI class implementation with container list view.
"""
import curses
import docker
import datetime
import time
import threading
import locale
import os
import json
import concurrent.futures
from collections import defaultdict

# Import from other modules
from ..utils.utils import safe_addstr, format_column, format_datetime, format_timedelta, format_bytes, get_speed_color
from ..utils.config import load_config, save_config
from .stats import schedule_stats_collection
from .stats import schedule_stats_collection_sync
from ..actions.container_actions import show_menu, execute_action


class DockerTUI:
    def __init__(self):
        self.client = docker.from_env()
        self.containers = []
        self.selected = 0
        self.running = True
        self.fetch_lock = threading.Lock()
        self.last_container_fetch = 0
        self.container_fetch_interval = 2  # seconds - reduced frequency for high container count
        
        # Stats cache
        self.stats_lock = threading.Lock()
        self.stats_cache = defaultdict(dict)
        
        # Thread pool for parallel stats collection
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=30)
        
        # Load column configuration
        self.columns = load_config()
        
        # Column separator
        self.column_separator = "│"
        
        # Display flags
        self.show_column_separators = True
        
        # Log normalization toggle (default: on)
        self.normalize_logs = True
        
        # Log line wrapping toggle (default: on)
        self.wrap_log_lines = True
        
        # Scrolling position for main container list
        self.scroll_offset = 0
        
        # Horizontal scroll for unwrapped logs
        self.h_scroll_offset = 0
        
        # Path to normalize_logs.py script
        self.normalize_logs_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils", "normalize_logs.py")
        
        # Check if normalize_logs.py exists and is executable
        if os.path.isfile(self.normalize_logs_script):
            if not os.access(self.normalize_logs_script, os.X_OK):
                try:
                    os.chmod(self.normalize_logs_script, 0o755)
                except:
                    pass
        
        # Sorting
        self.sort_column = 0  # Default sort by name
        self.sort_reverse = False
        
        # Filtering
        self.filter_string = ""
        self.filter_mode = False
        self.filtered_containers = []
        
        # ADDED: Limit container history
        self.container_history_limit = 100
        self.container_fetch_count = 0
        
        # Color pairs for speed indicators
        self.init_speed_colors()
    
    def init_speed_colors(self):
        """Initialize color pairs for speed indicators"""
        try:
            # Speed color pairs (starting from 11)
            curses.init_pair(11, curses.COLOR_GREEN, curses.COLOR_BLACK)    # KB/s
            curses.init_pair(12, curses.COLOR_YELLOW, curses.COLOR_BLACK)   # MB/s
            curses.init_pair(13, 208, curses.COLOR_BLACK)  # Dark orange for 300MB/s+ (color 208 is orange)
            curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)      # GB/s
        except:
            # Fallback if terminal doesn't support 256 colors
            try:
                curses.init_pair(11, curses.COLOR_GREEN, curses.COLOR_BLACK)
                curses.init_pair(12, curses.COLOR_YELLOW, curses.COLOR_BLACK)
                curses.init_pair(13, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Use yellow instead
                curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)
            except:
                pass

    def cleanup_stats_cache(self):
        """Remove stats entries for containers that no longer exist"""
        with self.stats_lock:
            # Get current container IDs
            current_ids = {c.id for c in self.containers}
            
            # Find stale entries
            stale_ids = [cid for cid in self.stats_cache.keys() if cid not in current_ids]
            
            # Remove stale entries
            for cid in stale_ids:
                del self.stats_cache[cid]
                
            # Also limit cache size to prevent unbounded growth
            # Keep only last 1000 entries (adjust based on your needs)
            if len(self.stats_cache) > 1000:
                # Remove oldest entries
                sorted_entries = sorted(
                    self.stats_cache.items(), 
                    key=lambda x: x[1].get('time', 0)
                )
                for cid, _ in sorted_entries[:len(sorted_entries) - 1000]:
                    del self.stats_cache[cid]

    def fetch_containers(self):
        """Fetch container list with throttling"""
        current_time = time.time()
        with self.fetch_lock:
            if current_time - self.last_container_fetch >= self.container_fetch_interval:
                try:
                    containers = self.client.containers.list(all=True)
                    # Sort containers by current sort settings
                    self.containers = self.sort_containers(containers)
                    self.last_container_fetch = current_time
                    
                    # ADDED: Periodic full cleanup
                    self.container_fetch_count += 1
                    if self.container_fetch_count % 100 == 0:
                        # Force garbage collection every 100 fetches
                        import gc
                        gc.collect()
                        self.container_fetch_count = 0
                    
                    # ADDED: Clean up stats cache periodically
                    self.cleanup_stats_cache()
                    
                    # Clear stats for stopped containers
                    with self.stats_lock:
                        running_ids = {c.id for c in containers if c.status == 'running'}
                        stopped_ids = [cid for cid in self.stats_cache.keys() if cid not in running_ids]
                        for cid in stopped_ids:
                            # Reset rates to 0 for stopped containers
                            if cid in self.stats_cache:
                                self.stats_cache[cid]['net_in_rate'] = 0
                                self.stats_cache[cid]['net_out_rate'] = 0
                                self.stats_cache[cid]['block_read_rate'] = 0
                                self.stats_cache[cid]['block_write_rate'] = 0
                                self.stats_cache[cid]['cpu'] = 0
                                self.stats_cache[cid]['mem'] = 0
                    
                    # Apply filter
                    self.apply_filter()
                    
                    # Schedule stats collection for all running containers
                    running_containers = [c for c in self.containers if c.status == 'running']
                    if running_containers:
                        self.executor.submit(schedule_stats_collection_sync, self, running_containers)
                    
                except docker.errors.DockerException:
                    # Keep existing containers if fetch fails
                    pass
        return self.containers
    
    def sort_containers(self, containers):
        """Sort containers based on current sort column and direction"""
        if not containers:
            return containers
        
        # Define sort key functions for each column
        def get_sort_key(container):
            with self.stats_lock:
                stats = self.stats_cache.get(container.id, {})
            
            # Find the actual column name to handle dynamic column order
            if self.sort_column < len(self.columns):
                col_name = self.columns[self.sort_column]['name']
                
                if col_name == 'NAME':
                    return container.name.lower()
                elif col_name == 'IMAGE':
                    return container.image.tags[0].lower() if container.image.tags else ''
                elif col_name == 'STATUS':
                    return container.status.lower()
                elif col_name == 'CPU%':
                    return stats.get('cpu', 0)
                elif col_name == 'MEM%':
                    return stats.get('mem', 0)
                elif col_name == 'NET I/O':
                    return stats.get('net_in_rate', 0) + stats.get('net_out_rate', 0)
                elif col_name == 'DISK I/O':
                    return stats.get('block_read_rate', 0) + stats.get('block_write_rate', 0)
                elif col_name == 'CREATED AT':
                    return container.attrs.get('Created', '')
                elif col_name == 'UPTIME':
                    if container.attrs.get('State', {}).get('Running'):
                        try:
                            start = datetime.datetime.fromisoformat(container.attrs['State']['StartedAt'][:-1])
                            return (datetime.datetime.utcnow() - start).total_seconds()
                        except:
                            return 0
                    return 0
            return ''
        
        return sorted(containers, key=get_sort_key, reverse=self.sort_reverse)
    
    def apply_filter(self):
        """Apply filter to containers list"""
        if not self.filter_string:
            self.filtered_containers = self.containers
        else:
            filter_lower = self.filter_string.lower()
            self.filtered_containers = [
                c for c in self.containers 
                if filter_lower in c.name.lower() or
                   (c.image.tags and filter_lower in c.image.tags[0].lower())
            ]
    
    def get_column_positions(self, screen_width):
        """Calculate column positions based on widths and screen size"""
        positions = [1]  # Start after cursor column
        
        # Calculate total weight and minimum required width
        total_weight = sum(col['weight'] for col in self.columns)
        min_required_width = 1  # Start position
        for i, col in enumerate(self.columns):
            min_required_width += col['min_width']
            # Add separator width if not the last column
            if i < len(self.columns) - 1 and self.show_column_separators:
                min_required_width += len(self.column_separator)
        
        # Calculate available space for weighted columns
        available_space = max(0, screen_width - min_required_width)
        
        # Calculate positions with dynamic widths
        current_pos = 1
        for i, col in enumerate(self.columns):
            # Calculate width based on weight if there's weight and space available
            if total_weight > 0 and col['weight'] > 0 and available_space > 0:
                extra_width = int((col['weight'] / total_weight) * available_space)
                width = col['min_width'] + extra_width
            else:
                width = col['width']  # Use fixed width if no weight
            
            # Ensure width is at least minimum
            width = max(width, col['min_width'])
            
            # Store the actual width used for drawing and resizing
            col['current_width'] = width
            
            current_pos += width
            
            # Add separator width if not the last column
            if i < len(self.columns) - 1 and self.show_column_separators:
                current_pos += len(self.column_separator)
                
            positions.append(current_pos)
        
        return positions
    
    def get_column_at_position(self, x, screen_width):
        """Find which column contains the given x position - IMPROVED VERSION"""
        positions = self.get_column_positions(screen_width)
        
        # Check each column's boundaries more precisely
        for i in range(len(self.columns)):
            if i < len(positions) - 1:
                # Column starts at positions[i] and ends before positions[i+1]
                start = positions[i]
                if i < len(self.columns) - 1 and self.show_column_separators:
                    # End before the separator
                    end = positions[i+1] - len(self.column_separator)
                else:
                    # Last column or no separators
                    end = positions[i+1]
                
                # More generous click detection - include separator area
                if start <= x <= end + (len(self.column_separator) if self.show_column_separators else 0):
                    return i
        
        # If no exact match, find closest column
        if len(positions) > 1:
            for i in range(len(self.columns)):
                if i < len(positions) - 1:
                    mid_point = (positions[i] + positions[i+1]) // 2
                    if x < mid_point:
                        return i
            # If past all midpoints, return last column
            return len(self.columns) - 1
            
        return -1
    
    def is_separator_position(self, x, screen_width):
        """Check if position is a column separator"""
        if not self.show_column_separators:
            return False
            
        positions = self.get_column_positions(screen_width)
        
        # Check if position is within 1 of any separator position
        for i in range(len(self.columns) - 1):
            if i + 1 < len(positions):
                sep_pos = positions[i+1] - len(self.column_separator)
                if abs(x - sep_pos) <= 1:
                    return i
        
        return -1

    def draw(self, stdscr):
        curses.curs_set(0)  # Hide cursor
        locale.setlocale(locale.LC_ALL, '')
        stdscr.nodelay(True)
        
        # Initialize colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected row
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # running
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # paused
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)  # stopped
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)  # header
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # footer
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_GREEN)  # menu selected
        curses.init_pair(8, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # resize handle
        curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # search highlight
        curses.init_pair(10, curses.COLOR_BLACK, curses.COLOR_GREEN)  # current search highlight
        
        # Initialize speed colors
        self.init_speed_colors()
        
        # Enable mouse support with enhanced motion events
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        
        # Enable extended mouse tracking (1003 mode) for reliable mouse motion events
        # This is essential for column dragging/resizing to work
        print("\033[?1003h")
        
        # Set terminal to report move events while button is pressed (1002 mode)
        print("\033[?1002h")
        
        try:
            # Initial message
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            safe_addstr(stdscr, 0, 0, "Loading containers...", curses.A_BOLD)
            stdscr.refresh()
            
            # Initial fetch
            self.fetch_containers()

            # Last time the screen was redrawn
            last_draw_time = 0
            draw_interval = 0.2  # Screen refresh rate in seconds (faster)
            
            # Last time stats were collected
            last_stats_time = 0
            stats_interval = 1.0  # Collect stats every second

            while self.running:
                # Handle key presses immediately for responsiveness
                key = stdscr.getch()
                current_time = time.time()
                
                if self.filter_mode:
                    # Handle filter input
                    if key == 27:  # ESC - exit filter mode
                        self.filter_mode = False
                        curses.curs_set(0)
                    elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
                        if self.filter_string:
                            self.filter_string = self.filter_string[:-1]
                            self.apply_filter()
                            # Reset selection if needed
                            if self.selected >= len(self.filtered_containers):
                                self.selected = max(0, len(self.filtered_containers) - 1)
                    elif key == 10:  # Enter - confirm filter
                        self.filter_mode = False
                        curses.curs_set(0)
                    elif 32 <= key < 127:  # Printable characters
                        self.filter_string += chr(key)
                        self.apply_filter()
                        # Reset selection if needed
                        if self.selected >= len(self.filtered_containers):
                            self.selected = max(0, len(self.filtered_containers) - 1)
                    last_draw_time = 0  # Force redraw
                    
                elif key != -1:
                    # Process key in normal mode
                    if key == curses.KEY_DOWN and self.selected < len(self.filtered_containers) - 1:
                        self.selected += 1
                        # Adjust scroll if selected container is outside view
                        visible_rows = h - 3  # Header and footer rows
                        if self.selected >= self.scroll_offset + visible_rows:
                            self.scroll_offset = self.selected - visible_rows + 1
                        last_draw_time = 0  # Redraw immediately
                    elif key == curses.KEY_UP and self.selected > 0:
                        self.selected -= 1
                        # Adjust scroll if selected container is outside view
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected
                        last_draw_time = 0  # Redraw immediately
                    elif key == curses.KEY_NPAGE:  # Page Down - FIXED: smaller increment
                        page_size = 5  # Only move 5 lines instead of full screen
                        self.selected = min(len(self.filtered_containers) - 1, self.selected + page_size)
                        # Adjust scroll to keep selection visible
                        visible_rows = h - 3
                        if self.selected >= self.scroll_offset + visible_rows:
                            self.scroll_offset = self.selected - visible_rows + 1
                        last_draw_time = 0
                    elif key == curses.KEY_PPAGE:  # Page Up - FIXED: smaller increment
                        page_size = 5  # Only move 5 lines instead of full screen
                        self.selected = max(0, self.selected - page_size)
                        # Adjust scroll to keep selection visible
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected
                        last_draw_time = 0
                    elif key == curses.KEY_HOME or key == ord('g'):  # NEW: Home key or 'g' - go to top
                        self.selected = 0
                        self.scroll_offset = 0
                        last_draw_time = 0
                    elif key == curses.KEY_END or key == ord('G'):  # NEW: End key or 'G' - go to bottom
                        self.selected = max(0, len(self.filtered_containers) - 1)
                        visible_rows = h - 3
                        if len(self.filtered_containers) > visible_rows:
                            self.scroll_offset = len(self.filtered_containers) - visible_rows
                        else:
                            self.scroll_offset = 0
                        last_draw_time = 0
                    elif key == ord('\\'):  # Start filter mode (backslash)
                        self.filter_mode = True
                        curses.curs_set(1)
                        last_draw_time = 0
                    elif key == 27 and self.filter_string:  # ESC - clear filter
                        self.filter_string = ""
                        self.apply_filter()
                        last_draw_time = 0
                    elif key == curses.KEY_MOUSE:
                        try:
                            _, mx, my, _, button_state = curses.getmouse()
                            
                            # Check if click was on header row - IMPROVED SORTING
                            if my == 0 and button_state & curses.BUTTON1_CLICKED:
                                # Find which column was clicked with improved detection
                                col_idx = self.get_column_at_position(mx, w)
                                if col_idx >= 0:
                                    # Toggle sort
                                    if self.sort_column == col_idx:
                                        self.sort_reverse = not self.sort_reverse
                                    else:
                                        self.sort_column = col_idx
                                        self.sort_reverse = False
                                    
                                    # Re-sort containers
                                    self.containers = self.sort_containers(self.containers)
                                    self.apply_filter()
                                    last_draw_time = 0
                            
                            # Check if click was on a container row
                            elif my > 0 and my < h - 1:
                                # Calculate content area start
                                content_start = 2 if self.filter_mode or self.filter_string else 1
                                
                                # Only process if click is in content area
                                if my >= content_start:
                                    row_idx = my - content_start + self.scroll_offset  # Adjust for scroll offset and header(s)
                                    if row_idx < len(self.filtered_containers):
                                        # Select the clicked container
                                        old_selection = self.selected
                                        self.selected = row_idx
                                        if old_selection != self.selected:
                                            last_draw_time = 0  # Redraw immediately
                                        elif self.filtered_containers:
                                            # Double click or click on selection -> show menu
                                            container = self.filtered_containers[self.selected]
                                            action_key = show_menu(self, stdscr, container)
                                            execute_action(self, stdscr, container, action_key)
                        except curses.error:
                            # Error getting mouse event
                            pass
                    elif key in (ord('l'), ord('L')) and self.filtered_containers:
                        # Import here to avoid circular imports
                        from ..views import log_view
                        log_view.show_logs(self, stdscr, self.filtered_containers[self.selected])
                    elif key in (ord('i'), ord('I')) and self.filtered_containers:
                        # Direct inspect shortcut using new module
                        from ..views import inspect_view
                        inspect_view.show_inspect(self, stdscr, self.filtered_containers[self.selected])
                    elif key in (ord('n'), ord('N')):
                        # Toggle normalization setting globally
                        self.normalize_logs = not self.normalize_logs
                        last_draw_time = 0  # Force redraw to update status
                    elif key in (ord('w'), ord('W')):
                        # Toggle line wrapping setting globally
                        self.wrap_log_lines = not self.wrap_log_lines
                        last_draw_time = 0  # Force redraw to update status
                    elif key in (10, curses.KEY_ENTER, curses.KEY_RIGHT) and self.filtered_containers:
                        container = self.filtered_containers[self.selected]
                        action_key = show_menu(self, stdscr, container)
                        execute_action(self, stdscr, container, action_key)
                    elif key in (ord('q'), ord('Q')):
                        self.running = False
                
                # Fetch containers in the background (throttled)
                self.fetch_containers()
                
                # Collect stats periodically
                if current_time - last_stats_time >= stats_interval:
                    running_containers = [c for c in self.containers if c.status == 'running']
                    if running_containers:
                        self.executor.submit(schedule_stats_collection_sync, self, running_containers)
                    last_stats_time = current_time
                
                # Only redraw the screen periodically to reduce CPU usage
                if current_time - last_draw_time >= draw_interval:
                    stdscr.erase()
                    h, w = stdscr.getmaxyx()
                    
                    # Get column positions based on current screen width
                    col_positions = self.get_column_positions(w)
                    
                    # Draw header with background color
                    stdscr.attron(curses.color_pair(5))
                    safe_addstr(stdscr, 0, 0, " " * w)  # Fill entire line
                    
                    # Show normalization status in the header
                    normalize_status = "NORM:" + ("ON" if self.normalize_logs else "OFF")
                    wrap_status = "WRAP:" + ("ON" if self.wrap_log_lines else "OFF") 
                    status_text = f"{normalize_status} | {wrap_status}"
                    safe_addstr(stdscr, 0, w - len(status_text) - 2, status_text, 
                                   curses.color_pair(5) | curses.A_BOLD)
                    
                    # Draw headers with sort indicators
                    for i, col in enumerate(self.columns):
                        header = col['name']
                        # Add sort indicator
                        if i == self.sort_column:
                            header += " ▼" if self.sort_reverse else " ▲"
                        
                        if i < len(col_positions) - 1:
                            # Calculate column width including separator
                            if i < len(self.columns) - 1 and self.show_column_separators:
                                col_width = col_positions[i+1] - col_positions[i] - len(self.column_separator)
                            else:
                                col_width = col_positions[i+1] - col_positions[i]
                            
                            # Draw column header
                            safe_addstr(stdscr, 0, col_positions[i], 
                                            format_column(header, col_width, col['align']), 
                                            curses.color_pair(5) | curses.A_BOLD)
                            
                            # Draw separator after column (except last)
                            if self.show_column_separators and i < len(self.columns) - 1:
                                sep_pos = col_positions[i] + col_width
                                safe_addstr(stdscr, 0, sep_pos, self.column_separator, 
                                               curses.color_pair(5) | curses.A_BOLD)
                    
                    stdscr.attroff(curses.color_pair(5))

                    # Draw filter input if in filter mode
                    if self.filter_mode:
                        filter_prompt = " Filter: "
                        safe_addstr(stdscr, 1, 0, filter_prompt, curses.A_BOLD)
                        safe_addstr(stdscr, 1, len(filter_prompt), self.filter_string)
                        safe_addstr(stdscr, 1, len(filter_prompt) + len(self.filter_string), "_", curses.A_BLINK)
                        stdscr.move(1, len(filter_prompt) + len(self.filter_string))
                    elif self.filter_string:
                        # Show active filter
                        filter_info = f" Filtered: {len(self.filtered_containers)}/{len(self.containers)} (Press \\ to change, ESC to clear) "
                        safe_addstr(stdscr, 1, 0, filter_info, curses.A_BOLD | curses.color_pair(3))

                    # Calculate content area
                    content_start = 2 if self.filter_mode or self.filter_string else 1
                    
                    # Draw content
                    if not self.filtered_containers:
                        if self.filter_string:
                            safe_addstr(stdscr, content_start + 1, 1, "No containers match the filter.", curses.A_DIM)
                        else:
                            safe_addstr(stdscr, content_start + 1, 1, "No containers found.", curses.A_DIM)
                    else:
                        # Calculate visible area
                        max_visible_containers = h - content_start - 1  # Minus header(s) and footer
                        
                        # Ensure scroll offset is valid
                        if self.scroll_offset > len(self.filtered_containers) - max_visible_containers:
                            self.scroll_offset = max(0, len(self.filtered_containers) - max_visible_containers)
                        
                        # Ensure selected container is visible
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected
                        elif self.selected >= self.scroll_offset + max_visible_containers:
                            self.scroll_offset = self.selected - max_visible_containers + 1
                        
                        # Draw scrollbar if needed
                        if len(self.filtered_containers) > max_visible_containers:
                            scrollbar_height = max_visible_containers
                            scrollbar_pos = int((self.scroll_offset / max(1, len(self.filtered_containers) - max_visible_containers)) 
                                                * (scrollbar_height - 1))
                            for i in range(scrollbar_height):
                                if i == scrollbar_pos:
                                    safe_addstr(stdscr, i + content_start, w-1, "█")
                                else:
                                    safe_addstr(stdscr, i + content_start, w-1, "│")
                        
                        # Draw visible containers
                        for i in range(min(max_visible_containers, len(self.filtered_containers) - self.scroll_offset)):
                            idx = i + self.scroll_offset
                            y = i + content_start  # Start after header(s)
                            
                            c = self.filtered_containers[idx]
                            
                            # Get container data
                            attr = c.attrs
                            name = c.name
                            image = c.image.tags[0] if c.image.tags else '<none>'
                            status = c.status
                            
                            # Status color
                            status_color = curses.A_NORMAL
                            if "running" in status.lower():
                                status_color = curses.color_pair(2)  # Green
                            elif "exited" in status.lower() or "stopped" in status.lower():
                                status_color = curses.color_pair(4)  # Red
                            elif "paused" in status.lower():
                                status_color = curses.color_pair(3)  # Yellow
                            
                            # Get stats for this container
                            with self.stats_lock:
                                stats = self.stats_cache.get(c.id, {})
                            
                            # Format CPU and memory percentages
                            cpu_pct = stats.get('cpu', 0)
                            mem_pct = stats.get('mem', 0)
                            
                            # Format network I/O with colors
                            net_in_rate = stats.get('net_in_rate', 0)
                            net_out_rate = stats.get('net_out_rate', 0)
                            
                            # Format disk I/O with colors
                            disk_read_rate = stats.get('block_read_rate', 0)
                            disk_write_rate = stats.get('block_write_rate', 0)
                            
                            # Format full creation date and time
                            created = format_datetime(attr.get('Created', ''))
                            
                            # Calculate uptime for running containers
                            uptime = '-'
                            if attr.get('State', {}).get('Running'):
                                try:
                                    start = datetime.datetime.fromisoformat(attr['State']['StartedAt'][:-1])
                                    uptime = format_timedelta(datetime.datetime.utcnow() - start)
                                except (ValueError, KeyError):
                                    pass
                            
                            # Prepare row data for all columns
                            row_data = {
                                'NAME': name,
                                'IMAGE': image,
                                'STATUS': status,
                                'CPU%': f"{cpu_pct:.1f}",
                                'MEM%': f"{mem_pct:.1f}",
                                'NET I/O': None,  # Handled specially
                                'DISK I/O': None,  # Handled specially  
                                'CREATED AT': created,
                                'UPTIME': uptime
                            }
                            
                            # Highlight selected row with visual indicator
                            if idx == self.selected:
                                stdscr.attron(curses.color_pair(1))
                                # Draw cursor indicator
                                safe_addstr(stdscr, y, 0, "➤", curses.color_pair(1) | curses.A_BOLD)
                            else:
                                # Space for alignment
                                safe_addstr(stdscr, y, 0, " ")
                            
                            # Draw each column with proper spacing
                            for i, col in enumerate(self.columns):
                                col_name = col['name']
                                if i < len(col_positions) - 1:
                                    # Calculate column width
                                    if i < len(self.columns) - 1 and self.show_column_separators:
                                        col_width = col_positions[i+1] - col_positions[i] - len(self.column_separator)
                                    else:
                                        col_width = col_positions[i+1] - col_positions[i]
                                    
                                    # Handle special columns
                                    if col_name == 'NET I/O':
                                        # Draw NET I/O with colors
                                        if idx == self.selected:
                                            # For selected row, use selection color
                                            net_io = f"{format_bytes(net_in_rate, '/s')}↓ {format_bytes(net_out_rate, '/s')}↑"
                                            safe_addstr(stdscr, y, col_positions[i], 
                                                       format_column(net_io, col_width, col['align']), 
                                                       curses.color_pair(1))
                                        else:
                                            # Draw with colors
                                            x_pos = col_positions[i]
                                            if col['align'] == 'right':
                                                # For right-aligned, we need to calculate positions
                                                down_text = f"{format_bytes(net_in_rate, '/s')}↓"
                                                up_text = f"{format_bytes(net_out_rate, '/s')}↑"
                                                
                                                # Get color for each part
                                                down_color = get_speed_color(net_in_rate)
                                                up_color = get_speed_color(net_out_rate)
                                                
                                                # Calculate total width needed
                                                total_len = len(down_text) + 1 + len(up_text)  # +1 for space
                                                
                                                # Start position for right alignment
                                                start_x = x_pos + col_width - total_len - 1
                                                
                                                # Draw download rate
                                                safe_addstr(stdscr, y, start_x, down_text, curses.color_pair(down_color))
                                                safe_addstr(stdscr, y, start_x + len(down_text), " ")
                                                # Draw upload rate
                                                safe_addstr(stdscr, y, start_x + len(down_text) + 1, up_text, curses.color_pair(up_color))
                                            else:
                                                # Left aligned
                                                down_text = f"{format_bytes(net_in_rate, '/s')}↓"
                                                up_text = f"{format_bytes(net_out_rate, '/s')}↑"
                                                
                                                # Get color for each part
                                                down_color = get_speed_color(net_in_rate)
                                                up_color = get_speed_color(net_out_rate)
                                                
                                                safe_addstr(stdscr, y, x_pos, down_text, curses.color_pair(down_color))
                                                safe_addstr(stdscr, y, x_pos + len(down_text), " ")
                                                safe_addstr(stdscr, y, x_pos + len(down_text) + 1, up_text, curses.color_pair(up_color))
                                    
                                    elif col_name == 'DISK I/O':
                                        # Draw DISK I/O with colors
                                        if idx == self.selected:
                                            # For selected row, use selection color
                                            disk_io = f"{format_bytes(disk_read_rate, '/s')}R {format_bytes(disk_write_rate, '/s')}W"
                                            safe_addstr(stdscr, y, col_positions[i], 
                                                       format_column(disk_io, col_width, col['align']), 
                                                       curses.color_pair(1))
                                        else:
                                            # Draw with colors
                                            x_pos = col_positions[i]
                                            if col['align'] == 'right':
                                                # For right-aligned, calculate positions
                                                read_text = f"{format_bytes(disk_read_rate, '/s')}R"
                                                write_text = f"{format_bytes(disk_write_rate, '/s')}W"
                                                
                                                # Get color for each part
                                                read_color = get_speed_color(disk_read_rate)
                                                write_color = get_speed_color(disk_write_rate)
                                                
                                                # Calculate total width needed
                                                total_len = len(read_text) + 1 + len(write_text)  # +1 for space
                                                
                                                # Start position for right alignment
                                                start_x = x_pos + col_width - total_len - 1
                                                
                                                # Draw read rate
                                                safe_addstr(stdscr, y, start_x, read_text, curses.color_pair(read_color))
                                                safe_addstr(stdscr, y, start_x + len(read_text), " ")
                                                # Draw write rate
                                                safe_addstr(stdscr, y, start_x + len(read_text) + 1, write_text, curses.color_pair(write_color))
                                            else:
                                                # Left aligned
                                                read_text = f"{format_bytes(disk_read_rate, '/s')}R"
                                                write_text = f"{format_bytes(disk_write_rate, '/s')}W"
                                                
                                                # Get color for each part
                                                read_color = get_speed_color(disk_read_rate)
                                                write_color = get_speed_color(disk_write_rate)
                                                
                                                safe_addstr(stdscr, y, x_pos, read_text, curses.color_pair(read_color))
                                                safe_addstr(stdscr, y, x_pos + len(read_text), " ")
                                                safe_addstr(stdscr, y, x_pos + len(read_text) + 1, write_text, curses.color_pair(write_color))
                                    
                                    elif col_name in row_data and row_data[col_name] is not None:
                                        col_text = row_data[col_name]
                                        
                                        # Apply status color only to the status column when not selected
                                        attr = status_color if col_name == 'STATUS' and idx != self.selected else curses.A_NORMAL
                                        
                                        if idx == self.selected:
                                            attr = curses.color_pair(1)  # Use selection color for all columns
                                        
                                        # Draw column content
                                        safe_addstr(stdscr, y, col_positions[i], 
                                                       format_column(col_text, col_width, col['align']), attr)
                                    
                                    # Draw separator after column (except last)
                                    if self.show_column_separators and i < len(self.columns) - 1:
                                        sep_pos = col_positions[i] + col_width
                                        sep_attr = curses.color_pair(1) if idx == self.selected else curses.A_NORMAL
                                        safe_addstr(stdscr, y, sep_pos, self.column_separator, sep_attr)
                            
                            if idx == self.selected:
                                stdscr.attroff(curses.color_pair(1))

                    # Draw footer with help text - UPDATED with new shortcuts
                    stdscr.attron(curses.color_pair(6))
                    footer_text = " ↑/↓:Navigate | PgUp/Dn:5 Lines | Home/End:Top/Bottom | Enter:Menu | L:Logs | I:Inspect | \\:Filter | Q:Quit "
                    footer_fill = " " * (w - len(footer_text))
                    safe_addstr(stdscr, h-1, 0, footer_text + footer_fill, curses.color_pair(6))
                    stdscr.attroff(curses.color_pair(6))
                    
                    stdscr.refresh()
                    last_draw_time = current_time
                
                # Sleep to reduce CPU usage, but keep it short for responsive UI
                time.sleep(0.01)
                
        finally:
            # Disable mouse movement tracking before exiting
            print("\033[?1003l")
            print("\033[?1002l")
            
            # IMPROVED: Shutdown executor with timeout
            self.executor.shutdown(wait=True, timeout=5.0)
            
            # ADDED: Clear stats cache
            with self.stats_lock:
                self.stats_cache.clear()
            
            # ADDED: Force garbage collection
            import gc
            gc.collect()
            
            # Clean up stats collector
            from .stats import cleanup_stats_sync
            cleanup_stats_sync()
