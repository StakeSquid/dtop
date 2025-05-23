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
from utils import safe_addstr, format_column, format_datetime, format_timedelta, format_bytes
from config import load_config, save_config
from stats import schedule_stats_collection
from container_actions import show_menu, execute_action

# Batch stats collection via docker stats CLI
import subprocess

def schedule_stats_collection(tui, containers):
    """Batch-collect stats for all running containers via docker stats CLI, mapping short IDs to full IDs."""
    if not containers:
        return
    id_map = {c.id[:12]: c.id for c in containers}
    fmt = (
        "{{.Container}}|{{.Name}}|{{.CPUPerc}}|"
        "{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}"
    )
    cmd = ["docker", "stats", "--no-stream", "--format", fmt]
    try:
        output = subprocess.check_output(cmd, text=True)
        new_cache = {}
        now = time.time()
        for line in output.splitlines():
            parts = line.split("|")
            if len(parts) != 6:
                continue
            short_id, name, cpu, mem, netio, blockio = parts
            full_id = id_map.get(short_id)
            if not full_id:
                continue
            try:
                cpu_pct = float(cpu.strip("%"))
            except ValueError:
                cpu_pct = 0.0
            try:
                mem_pct = float(mem.strip("%"))
            except ValueError:
                mem_pct = 0.0
            new_cache[full_id] = {
                "cpu": cpu_pct,
                "mem": mem_pct,
                "net_in_rate": 0,
                "net_out_rate": 0,
                "net_in": 0,
                "net_out": 0,
                "time": now
            }
        with tui.stats_lock:
            tui.stats_cache.clear()
            tui.stats_cache.update(new_cache)
    except Exception:
        pass


class DockerTUI:
    def __init__(self):
        self.client = docker.from_env()
        self.containers = []
        self.selected = 0
        self.running = True
        self.fetch_lock = threading.Lock()
        self.last_container_fetch = 0
        self.container_fetch_interval = 0.5  # seconds
        
        # Stats cache
        self.stats_lock = threading.Lock()
        self.stats_cache = defaultdict(dict)
        
        # Thread pool for parallel stats collection
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        
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
        self.normalize_logs_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalize_logs.py")
        
        # Check if normalize_logs.py exists and is executable
        if os.path.isfile(self.normalize_logs_script):
            if not os.access(self.normalize_logs_script, os.X_OK):
                try:
                    os.chmod(self.normalize_logs_script, 0o755)
                except:
                    pass

    def fetch_containers(self):
        """Fetch container list with throttling"""
        current_time = time.time()
        with self.fetch_lock:
            if current_time - self.last_container_fetch >= self.container_fetch_interval:
                try:
                    containers = self.client.containers.list(all=True)
                    # Sort containers by name
                    self.containers = sorted(containers, key=lambda c: c.name.lower())
                    self.last_container_fetch = current_time
                    
                    # Schedule stats collection for all running containers
                    running_containers = [c for c in self.containers if c.status == 'running']
                    self.executor.submit(schedule_stats_collection, self, running_containers)
                    
                except docker.errors.DockerException:
                    # Keep existing containers if fetch fails
                    pass
        return self.containers
    
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
    
    def get_column_at_position(self, x):
        """Find which column contains the given x position"""
        positions = self.get_column_positions(9999)  # Large width to get all positions
        
        for i in range(len(positions) - 1):
            if positions[i] <= x < positions[i+1]:
                return i
        
        return -1
    
    def is_separator_position(self, x):
        """Check if position is a column separator"""
        if not self.show_column_separators:
            return False
            
        positions = self.get_column_positions(9999)
        
        # Check if position is within 1 of any separator position
        for i in range(len(positions) - 1):
            sep_pos = positions[i] + self.columns[i].get('current_width', self.columns[i]['width']) - 1
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

            while self.running:
                # Handle key presses immediately for responsiveness
                key = stdscr.getch()
                current_time = time.time()
                
                if key != -1:
                    # Process key
                    if key == curses.KEY_DOWN and self.selected < len(self.containers) - 1:
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
                    elif key == curses.KEY_MOUSE:
                        try:
                            _, mx, my, _, button_state = curses.getmouse()
                            
                            # Check if click was on a container row
                            row_idx = my - 1 + self.scroll_offset  # Adjust for scroll offset
                            if my > 0 and my < h - 1 and row_idx < len(self.containers):
                                # Select the clicked container
                                old_selection = self.selected
                                self.selected = row_idx
                                if old_selection != self.selected:
                                    last_draw_time = 0  # Redraw immediately
                                elif self.containers:
                                    # Double click or click on selection -> show menu
                                    action_key = show_menu(self, stdscr, self.containers[self.selected])
                                    execute_action(self, stdscr, self.containers[self.selected], action_key)
                        except curses.error:
                            # Error getting mouse event
                            pass
                    elif key in (ord('l'), ord('L')) and self.containers:
                        # Import here to avoid circular imports
                        import log_view
                        log_view.show_logs(self, stdscr, self.containers[self.selected])
                    elif key in (ord('n'), ord('N')):
                        # Toggle normalization setting globally
                        self.normalize_logs = not self.normalize_logs
                        last_draw_time = 0  # Force redraw to update status
                    elif key in (ord('w'), ord('W')):
                        # Toggle line wrapping setting globally
                        self.wrap_log_lines = not self.wrap_log_lines
                        last_draw_time = 0  # Force redraw to update status
                    elif key in (10, curses.KEY_ENTER, curses.KEY_RIGHT) and self.containers:
                        action_key = show_menu(self, stdscr, self.containers[self.selected])
                        execute_action(self, stdscr, self.containers[self.selected], action_key)
                    elif key in (ord('q'), ord('Q')):
                        self.running = False
                
                # Fetch containers in the background (throttled)
                self.fetch_containers()
                
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
                    
                    # Draw headers
                    for i, col in enumerate(self.columns):
                        header = col['name']
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

                    # Draw content
                    if not self.containers:
                        safe_addstr(stdscr, 2, 1, "No containers found.", curses.A_DIM)
                    else:
                        # Calculate visible area
                        max_visible_containers = h - 3  # Minus header and footer rows
                        
                        # Ensure scroll offset is valid
                        if self.scroll_offset > len(self.containers) - max_visible_containers:
                            self.scroll_offset = max(0, len(self.containers) - max_visible_containers)
                        
                        # Ensure selected container is visible
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected
                        elif self.selected >= self.scroll_offset + max_visible_containers:
                            self.scroll_offset = self.selected - max_visible_containers + 1
                        
                        # Draw scrollbar if needed
                        if len(self.containers) > max_visible_containers:
                            scrollbar_height = max_visible_containers
                            scrollbar_pos = int((self.scroll_offset / max(1, len(self.containers) - max_visible_containers)) 
                                                * (scrollbar_height - 1))
                            for i in range(scrollbar_height):
                                if i == scrollbar_pos:
                                    safe_addstr(stdscr, i + 1, w-1, "█")
                                else:
                                    safe_addstr(stdscr, i + 1, w-1, "│")
                        
                        # Draw visible containers
                        for i in range(min(max_visible_containers, len(self.containers) - self.scroll_offset)):
                            idx = i + self.scroll_offset
                            y = i + 1  # Start at line 1 (after header)
                            
                            c = self.containers[idx]
                            
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
                            
                            # Format network I/O
                            net_in_rate = stats.get('net_in_rate', 0)
                            net_out_rate = stats.get('net_out_rate', 0)
                            net_io = f"{format_bytes(net_in_rate, '/s')}↓ {format_bytes(net_out_rate, '/s')}↑"
                            
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
                            
                            # Prepare row data
                            row_data = [
                                name, image, status, 
                                f"{cpu_pct:.1f}", f"{mem_pct:.1f}", 
                                net_io, created, uptime
                            ]
                            
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
                                if i < len(row_data):
                                    col_text = row_data[i]
                                    
                                    # Calculate column width
                                    if i < len(col_positions) - 1:
                                        # Get width from positions, accounting for separator
                                        if i < len(self.columns) - 1 and self.show_column_separators:
                                            col_width = col_positions[i+1] - col_positions[i] - len(self.column_separator)
                                        else:
                                            col_width = col_positions[i+1] - col_positions[i]
                                        
                                        # Apply status color only to the status column when not selected
                                        attr = status_color if i == 2 and idx != self.selected else curses.A_NORMAL
                                        
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

                    # Draw footer with help text
                    stdscr.attron(curses.color_pair(6))
                    footer_text = " ↑/↓/Click:Navigate | Enter/Click:Menu | L:Logs | N:Toggle Normalize | W:Toggle Wrap | Q:Quit "
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
            
            # Close executor
            self.executor.shutdown(wait=False)
