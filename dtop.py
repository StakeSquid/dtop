#!/usr/bin/env python3
"""
Docker TUI - Final Version
-----------
A high-performance terminal UI for managing Docker containers:
- Fast parallel stats collection
- Properly separated columns with resizable widths
- Mouse support for navigation and column resizing
- Reliable log display with normalization and line wrapping
- Configuration saving

Controls:
  - ↑/↓/Mouse    : Navigate containers
  - Enter/Click   : Show action menu
  - L            : View logs for selected container
  - F            : Toggle log follow mode
  - N            : Toggle log normalization
  - W            : Toggle log line wrapping
  - Mouse Drag   : Resize columns
  - Q            : Quit

Dependencies:
  pip install docker
"""
import curses
import docker
import datetime
import time
import threading
import locale
import subprocess
import os
import json
import concurrent.futures
import sys
from collections import defaultdict

# Configuration file path in user's home directory
CONFIG_FILE = os.path.expanduser("~/.docker_tui.json")

# Default column configuration
DEFAULT_COLUMNS = [
    {"name": "NAME", "width": 25, "min_width": 15, "weight": 3, "align": "left"},
    {"name": "IMAGE", "width": 30, "min_width": 15, "weight": 2, "align": "left"},
    {"name": "STATUS", "width": 12, "min_width": 8, "weight": 1, "align": "left"},
    {"name": "CPU%", "width": 8, "min_width": 7, "weight": 0, "align": "right"},
    {"name": "MEM%", "width": 8, "min_width": 7, "weight": 0, "align": "right"},
    {"name": "NET I/O", "width": 20, "min_width": 16, "weight": 0, "align": "right"},
    {"name": "CREATED AT", "width": 21, "min_width": 19, "weight": 0, "align": "left"},
    {"name": "UPTIME", "width": 12, "min_width": 8, "weight": 0, "align": "right"}
]

# Helper to format uptime
def format_timedelta(td):
    seconds = int(td.total_seconds())
    hours, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hours:02}:{mins:02}:{secs:02}"

# Helper to format bytes
def format_bytes(num_bytes, suffix='B'):
    for unit in ['', 'K', 'M', 'G', 'T', 'P']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f}{unit}{suffix}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}Y{suffix}"

# Helper to format datetime
def format_datetime(dt_str):
    """Format ISO datetime string to human-readable format"""
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return dt_str

# Helper to truncate text and add padding
def format_column(text, width, align='left'):
    """Format text to fit in column with padding"""
    text_str = str(text)
    if len(text_str) > width - 2:
        text_str = text_str[:width - 3] + "…"
    
    if align == 'left':
        return text_str.ljust(width - 1) + " "
    elif align == 'right':
        return " " + text_str.rjust(width - 1)
    else:  # center
        return text_str.center(width)

class DockerTUI:
    def __init__(self):
        self.client = docker.from_env()
        self.containers = []
        self.selected = 0
        self.running = True
        self.fetch_lock = threading.Lock()
        self.last_container_fetch = 0
        self.container_fetch_interval = 2  # seconds
        
        # Stats cache
        self.stats_lock = threading.Lock()
        self.stats_cache = defaultdict(dict)
        
        # Thread pool for parallel stats collection
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        
        # Load column configuration
        self.load_config()
        
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

    def load_config(self):
        """Load column configuration from file or use defaults"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.columns = config.get('columns', DEFAULT_COLUMNS)
            else:
                self.columns = DEFAULT_COLUMNS.copy()
        except Exception:
            # If any error occurs, use defaults
            self.columns = DEFAULT_COLUMNS.copy()
        
        # Ensure at least minimum widths
        for col in self.columns:
            col['width'] = max(col['width'], col['min_width'])

    def save_config(self):
        """Save column configuration to file"""
        try:
            config = {
                'columns': self.columns
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception:
            # Ignore errors in saving config
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
                    self.schedule_stats_collection(running_containers)
                    
                except docker.errors.DockerException:
                    # Keep existing containers if fetch fails
                    pass
        return self.containers
    
    def schedule_stats_collection(self, containers):
        """Schedule stats collection for multiple containers in parallel"""
        if not containers:
            return
            
        # Submit jobs to thread pool
        futures = []
        for container in containers:
            future = self.executor.submit(self.fetch_container_stats, container)
            futures.append(future)
    
    def fetch_container_stats(self, container):
        """Fetch stats for a single container"""
        try:
            # Get stats without streaming
            stats = container.stats(stream=False)
            
            # Process CPU stats
            try:
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              stats['precpu_stats']['system_cpu_usage']
                
                cpu_percent = 0.0
                if system_delta > 0 and cpu_delta > 0:
                    # Calculate CPU percent using the same formula Docker uses
                    cpu_count = len(stats['cpu_stats']['cpu_usage'].get('percpu_usage', [1]))
                    cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
            except (KeyError, TypeError):
                cpu_percent = 0.0
            
            # Process memory stats
            try:
                mem_percent = 0.0
                if 'memory_stats' in stats and 'usage' in stats['memory_stats'] and 'limit' in stats['memory_stats']:
                    mem_usage = stats['memory_stats']['usage']
                    mem_limit = stats['memory_stats']['limit']
                    mem_percent = (mem_usage / mem_limit) * 100.0
            except (KeyError, TypeError, ZeroDivisionError):
                mem_percent = 0.0
            
            # Process network stats
            net_in = 0
            net_out = 0
            if 'networks' in stats:
                for interface in stats['networks'].values():
                    net_in += interface['rx_bytes']
                    net_out += interface['tx_bytes']
            
            # Cache stats with timestamp
            with self.stats_lock:
                # Store previous network values for rate calculation
                prev_stats = self.stats_cache[container.id]
                prev_time = prev_stats.get('time', time.time())
                prev_net_in = prev_stats.get('net_in', net_in)
                prev_net_out = prev_stats.get('net_out', net_out)
                
                # Calculate network rate
                time_diff = time.time() - prev_time
                if time_diff > 0:
                    net_in_rate = (net_in - prev_net_in) / time_diff
                    net_out_rate = (net_out - prev_net_out) / time_diff
                else:
                    net_in_rate = 0
                    net_out_rate = 0
                
                # Store current values
                self.stats_cache[container.id] = {
                    'cpu': cpu_percent,
                    'mem': mem_percent,
                    'net_in': net_in,
                    'net_out': net_out,
                    'net_in_rate': net_in_rate,
                    'net_out_rate': net_out_rate,
                    'time': time.time()
                }
        except Exception:
            # Ignore errors for individual containers
            pass

    def normalize_container_logs(self, log_lines):
        """Pipe logs through normalize_logs.py script"""
        if not self.normalize_logs or not os.path.isfile(self.normalize_logs_script):
            return log_lines
        
        try:
            # Join log lines with newlines to create input
            log_text = "\n".join(log_lines)
            
            # Make sure normalize_logs.py is executable
            if not os.access(self.normalize_logs_script, os.X_OK):
                os.chmod(self.normalize_logs_script, 0o755)
            
            # Run normalize_logs.py as a subprocess
            process = subprocess.Popen(
                [self.normalize_logs_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Send logs to stdin and get normalized output
            stdout, stderr = process.communicate(input=log_text, timeout=3)
            
            # Check if there was an error
            if process.returncode != 0 or stderr:
                error_logs = log_lines.copy()
                error_logs.insert(0, f"Log normalization error: {stderr.strip()}")
                error_logs.insert(1, "Showing raw logs instead.")
                self.normalize_logs = False  # Disable normalization on error
                return error_logs
            
            # Split output into lines and return
            normalized_logs = stdout.splitlines()
            return normalized_logs
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
            # Handle subprocess errors
            error_logs = log_lines.copy()
            error_logs.insert(0, f"Log normalization error: {str(e)}")
            error_logs.insert(1, "Showing raw logs instead.")
            self.normalize_logs = False  # Disable normalization on error
            return error_logs

    def rebuild_log_pad(self, current_pad, logs, width, height, follow_mode):
        """Rebuild the log pad with current wrapping and normalization settings"""
        # Estimate pad size needed
        pad_height = max(len(logs)+100, 500)
        
        # If wrapping is enabled, we might need more space
        if self.wrap_log_lines:
            # Roughly estimate how many extra lines we might need for wrapping
            extra_lines = sum(max(1, len(line) // (width-3)) for line in logs)
            pad_height += extra_lines
        
        # Create new pad with appropriate dimensions
        pad_width = max(width-2, 10)
        if not self.wrap_log_lines:
            # For non-wrapped mode, make pad wider to accommodate long lines
            pad_width = max(pad_width, max((len(line) for line in logs), default=width) + 10)
            
        new_pad = curses.newpad(pad_height, pad_width)
        
        # Fill pad with logs - handle wrapping
        line_positions = []  # Track the starting position of each logical line
        current_line = 0
        
        for i, line in enumerate(logs):
            line_positions.append(current_line)
            if self.wrap_log_lines:
                # Split the line into wrapped segments
                remaining = line
                while remaining:
                    segment = remaining[:width-3]
                    try:
                        new_pad.addstr(current_line, 0, segment)
                    except curses.error:
                        pass
                    current_line += 1
                    remaining = remaining[width-3:]
            else:
                # No wrapping - just add the whole line
                try:
                    new_pad.addstr(current_line, 0, line)
                except curses.error:
                    pass
                current_line += 1
        
        # Store these values for later reference
        self.log_pad = new_pad
        self.log_line_positions = line_positions
        self.log_actual_lines = current_line
        
        return new_pad

    def safe_addstr(self, win, y, x, text, attr=0):
        """Add string only if within bounds; ignore errors"""
        h, w = win.getmaxyx()
        if 0 <= y < h and x < w:
            try:
                # Convert to string and truncate
                text_str = str(text)[:max(0, w-x)]
                win.addstr(y, x, text_str, attr)
            except curses.error:
                pass
    
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
            self.safe_addstr(stdscr, 0, 0, "Loading containers...", curses.A_BOLD)
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
                                    self.show_menu(stdscr, self.containers[self.selected])
                        except curses.error:
                            # Error getting mouse event
                            pass
                    elif key in (ord('l'), ord('L')) and self.containers:
                        self.show_logs(stdscr, self.containers[self.selected])
                    elif key in (ord('n'), ord('N')):
                        # Toggle normalization setting globally
                        self.normalize_logs = not self.normalize_logs
                        last_draw_time = 0  # Force redraw to update status
                    elif key in (ord('w'), ord('W')):
                        # Toggle line wrapping setting globally
                        self.wrap_log_lines = not self.wrap_log_lines
                        last_draw_time = 0  # Force redraw to update status
                    elif key in (10, curses.KEY_ENTER, curses.KEY_RIGHT) and self.containers:
                        self.show_menu(stdscr, self.containers[self.selected])
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
                    self.safe_addstr(stdscr, 0, 0, " " * w)  # Fill entire line
                    
                    # Show normalization status in the header
                    normalize_status = "NORM:" + ("ON" if self.normalize_logs else "OFF")
                    wrap_status = "WRAP:" + ("ON" if self.wrap_log_lines else "OFF") 
                    status_text = f"{normalize_status} | {wrap_status}"
                    self.safe_addstr(stdscr, 0, w - len(status_text) - 2, status_text, 
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
                            self.safe_addstr(stdscr, 0, col_positions[i], 
                                            format_column(header, col_width, col['align']), 
                                            curses.color_pair(5) | curses.A_BOLD)
                            
                            # Draw separator after column (except last)
                            if self.show_column_separators and i < len(self.columns) - 1:
                                sep_pos = col_positions[i] + col_width
                                self.safe_addstr(stdscr, 0, sep_pos, self.column_separator, 
                                               curses.color_pair(5) | curses.A_BOLD)
                    
                    stdscr.attroff(curses.color_pair(5))

                    # Draw content
                    if not self.containers:
                        self.safe_addstr(stdscr, 2, 1, "No containers found.", curses.A_DIM)
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
                                    self.safe_addstr(stdscr, i + 1, w-1, "█")
                                else:
                                    self.safe_addstr(stdscr, i + 1, w-1, "│")
                        
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
                                self.safe_addstr(stdscr, y, 0, "➤", curses.color_pair(1) | curses.A_BOLD)
                            else:
                                # Space for alignment
                                self.safe_addstr(stdscr, y, 0, " ")
                            
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
                                        self.safe_addstr(stdscr, y, col_positions[i], 
                                                       format_column(col_text, col_width, col['align']), attr)
                                        
                                        # Draw separator after column (except last)
                                        if self.show_column_separators and i < len(self.columns) - 1:
                                            sep_pos = col_positions[i] + col_width
                                            sep_attr = curses.color_pair(1) if idx == self.selected else curses.A_NORMAL
                                            self.safe_addstr(stdscr, y, sep_pos, self.column_separator, sep_attr)
                            
                            if idx == self.selected:
                                stdscr.attroff(curses.color_pair(1))

                    # Draw footer with help text
                    stdscr.attron(curses.color_pair(6))
                    footer_text = " ↑/↓/Click:Navigate | Enter/Click:Menu | L:Logs | N:Toggle Normalize | W:Toggle Wrap | Q:Quit "
                    footer_fill = " " * (w - len(footer_text))
                    self.safe_addstr(stdscr, h-1, 0, footer_text + footer_fill, curses.color_pair(6))
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

    def show_logs(self, stdscr, container):
        """Display container logs with follow mode"""
        try:
            # Get terminal size
            h, w = stdscr.getmaxyx()
            
            # Temporarily stop refresh
            stdscr.nodelay(False)
            curses.curs_set(0)
            
            # Clear and show loading message
            stdscr.clear()
            self.safe_addstr(stdscr, h//2, (w-25)//2, "Loading logs, please wait...", curses.A_BOLD)
            stdscr.refresh()
            
            # Fetch initial logs
            raw_logs = container.logs(tail=500).decode(errors='ignore').splitlines()
            
            # Process logs through normalize_logs.py
            logs = self.normalize_container_logs(raw_logs) if self.normalize_logs else raw_logs
            
            # Set up follow mode
            follow_mode = True
            last_log_time = time.time()
            log_update_interval = 0.5  # seconds (faster updates)
            
            # Create a pad for scrolling (with at least one line)
            # Make sure there's at least one line to display
            pad_height = max(len(logs)+100, 500)  # Extra room for new logs
            
            # If wrapping is enabled, we might need more space in the pad for wrapped lines
            if self.wrap_log_lines:
                # Roughly estimate how many extra lines we might need for wrapping
                extra_lines = sum(max(1, len(line) // (w-3)) for line in logs)
                pad_height += extra_lines
                
            if len(logs) == 0:
                logs = ["No logs available for this container"]
                
            pad = curses.newpad(pad_height, max(w-2, 10) * (not self.wrap_log_lines) + w*100*self.wrap_log_lines)  # Extra width for unwrapped
            
            # Fill pad with initial logs - handle wrapping
            line_positions = []  # Track the starting position of each logical line
            current_line = 0
            
            for i, line in enumerate(logs):
                line_positions.append(current_line)
                if self.wrap_log_lines:
                    # Split the line into wrapped segments
                    remaining = line
                    while remaining:
                        segment = remaining[:w-3]
                        try:
                            pad.addstr(current_line, 0, segment)
                        except curses.error:
                            pass
                        current_line += 1
                        remaining = remaining[w-3:]
                else:
                    # No wrapping - just add the whole line
                    try:
                        pad.addstr(current_line, 0, line)
                    except curses.error:
                        pass
                    current_line += 1
            
            # Total number of lines in the pad
            total_pad_lines = current_line
            
            # Start at the end of logs if in follow mode
            pos = max(0, total_pad_lines - (h-4)) if follow_mode else 0
            
            # Horizontal scroll
            h_scroll = 0
            max_line_length = max([len(line) for line in logs], default=0)
            
            # Initial draw of screen
            stdscr.refresh()
            pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
            
            # Reduce refresh rate to avoid flashing
            draw_interval = 0.3  # seconds between screen refreshes
            
            # Main log viewing loop
            running = True
            last_display_time = 0
            all_raw_logs = raw_logs.copy()  # Keep track of ALL raw logs for toggling
            
            # Track logical lines for accurate navigation
            last_logical_lines_count = len(logs)
            actual_lines_count = total_pad_lines
            
            # Track UI states to avoid unnecessary redraws
            last_follow_mode = follow_mode
            last_normalize_logs = self.normalize_logs
            last_wrap_lines = self.wrap_log_lines
            
            # Draw the static parts of the UI once at the beginning
            stdscr.clear()
            
            # Draw header
            stdscr.attron(curses.color_pair(5))
            self.safe_addstr(stdscr, 0, 0, " " * w)
            normalized_indicator = " [NORMALIZED]" if self.normalize_logs else " [RAW]"
            wrap_indicator = " [WRAP]" if self.wrap_log_lines else " [NOWRAP]"
            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator
            self.safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
            stdscr.attroff(curses.color_pair(5))
            
            # Draw footer with help
            if self.wrap_log_lines:
                footer_text = " ↑/↓:Scroll | PgUp/Dn:Page | F:Toggle Follow | N:Toggle Normalize | W:Toggle Wrap | ESC/Q:Back "
            else:
                footer_text = " ↑/↓:Scroll | ←/→:Scroll H | PgUp/Dn:Page | F:Follow | N:Normalize | W:Wrap | ESC/Q:Back "
            
            stdscr.attron(curses.color_pair(6))
            self.safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
            stdscr.attroff(curses.color_pair(6))
            
            while running:
                current_time = time.time()
                
                # Update logs in follow mode
                if follow_mode and current_time - last_log_time >= log_update_interval:
                    try:
                        # Simpler timestamp handling to fix follow mode
                        # Docker expects Unix timestamp in seconds
                        unix_timestamp = int(time.time()) - 2  # Go back 2 seconds to avoid missing logs
                        raw_new_logs = container.logs(
                            tail=100,
                            stream=False,  # Don't stream, just fetch once
                            since=unix_timestamp
                        ).decode(errors='ignore').splitlines()
                        
                        if raw_new_logs:
                            # Update raw_logs with new content for toggling
                            all_raw_logs.extend(raw_new_logs)
                            
                            # Process new logs through normalize_logs.py if normalization is on
                            new_logs = self.normalize_container_logs(raw_new_logs) if self.normalize_logs else raw_new_logs
                            
                            # Check if we need to resize the pad
                            new_lines_estimate = len(new_logs)
                            if self.wrap_log_lines:
                                # Estimate additional space needed for wrapping
                                new_lines_estimate += sum(max(1, len(line) // (w-3)) for line in new_logs)
                                
                            if actual_lines_count + new_lines_estimate >= pad_height:
                                # Create a new larger pad
                                new_pad_height = pad_height + 500 + new_lines_estimate
                                new_pad = curses.newpad(new_pad_height, pad.getmaxyx()[1])
                                
                                # Copy content from old pad
                                for i in range(min(pad_height, actual_lines_count)):
                                    try:
                                        line = pad.instr(i, 0, w-3)
                                        new_pad.addstr(i, 0, line.decode())
                                    except curses.error:
                                        pass
                                
                                # Replace old pad
                                pad = new_pad
                                pad_height = new_pad_height
                            
                            # Append new logs to pad with wrapping support
                            current_line = actual_lines_count
                            for i, line in enumerate(new_logs):
                                line_positions.append(current_line)
                                if self.wrap_log_lines:
                                    # Split the line into wrapped segments
                                    remaining = line
                                    while remaining:
                                        segment = remaining[:w-3]
                                        try:
                                            pad.addstr(current_line, 0, segment)
                                        except curses.error:
                                            pass
                                        current_line += 1
                                        remaining = remaining[w-3:]
                                else:
                                    # No wrapping - just add the whole line
                                    try:
                                        pad.addstr(current_line, 0, line)
                                    except curses.error:
                                        pass
                                    current_line += 1
                            
                            # Update line counts
                            last_logical_lines_count += len(new_logs)
                            actual_lines_count = current_line
                            logs.extend(new_logs)
                            
                            # Auto-scroll to bottom in follow mode
                            if follow_mode:
                                pos = max(0, actual_lines_count - (h-4))
                    except Exception:
                        pass  # Ignore errors in log fetching
                    
                    last_log_time = current_time
                
                # Always ensure pos is valid
                pos = max(0, min(pos, max(0, actual_lines_count - 1)))
                
                # Update display regularly regardless of new logs or position changes
                if current_time - last_display_time >= draw_interval:  # Use the specified draw interval
                    # Update header only when needed (status change)
                    if follow_mode != last_follow_mode or self.normalize_logs != last_normalize_logs or self.wrap_log_lines != last_wrap_lines:
                        stdscr.attron(curses.color_pair(5))
                        self.safe_addstr(stdscr, 0, 0, " " * w)
                        normalized_indicator = " [NORMALIZED]" if self.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if self.wrap_log_lines else " [NOWRAP]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator
                        self.safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        
                        # Track current state
                        last_follow_mode = follow_mode
                        last_normalize_logs = self.normalize_logs
                        last_wrap_lines = self.wrap_log_lines
                    
                    # Update line counter
                    logical_pos = 0
                    for i, line_pos in enumerate(line_positions):
                        if line_pos > pos:
                            break
                        logical_pos = i
                    
                    line_info = f" Line: {logical_pos+1}/{last_logical_lines_count} "
                    self.safe_addstr(stdscr, 1, w-len(line_info)-1, line_info)
                    
                    # Update scrollbar
                    scrollbar_height = h - 4
                    if actual_lines_count > scrollbar_height and scrollbar_height > 0:
                        scrollbar_pos = 2
                        if actual_lines_count > scrollbar_height:
                            scrollbar_pos = 2 + int((pos / (actual_lines_count - scrollbar_height)) * (scrollbar_height - 1))
                        for i in range(2, h-2):
                            if i == scrollbar_pos:
                                self.safe_addstr(stdscr, i, w-1, "█")
                            else:
                                self.safe_addstr(stdscr, i, w-1, "│")
                    
                    # Determine horizontal scroll position
                    if not self.wrap_log_lines:
                        # Update max line length
                        max_line_length = max([len(line) for line in logs], default=0)
                        
                        # Show horizontal scrollbar if needed
                        if max_line_length > w-3:
                            # Calculate horizontal scrollbar position indicators
                            scrollbar_width = w - 4
                            total_width = max_line_length
                            visible_width = w - 3
                            
                            # Create base scrollbar
                            h_scrollbar = "◄" + "─" * (scrollbar_width - 2) + "►"
                            
                            # Calculate thumb position and size
                            if total_width > 0:
                                thumb_pos = int((h_scroll / total_width) * scrollbar_width)
                                thumb_size = max(1, int((visible_width / total_width) * scrollbar_width))
                                thumb_end = min(scrollbar_width - 1, thumb_pos + thumb_size)
                                
                                # Replace characters with the thumb
                                h_scrollbar_list = list(h_scrollbar)
                                for i in range(thumb_pos + 1, thumb_end + 1):
                                    if 1 <= i < len(h_scrollbar_list) - 1:  # Avoid overwriting the arrows
                                        h_scrollbar_list[i] = "═"
                                h_scrollbar = "".join(h_scrollbar_list)
                            
                            # Show horizontal position
                            pos_text = f" {h_scroll+1}-{min(h_scroll+visible_width, total_width)}/{total_width} "
                            self.safe_addstr(stdscr, h-2, 0, h_scrollbar, curses.A_DIM)
                            self.safe_addstr(stdscr, h-2, w-len(pos_text), pos_text, curses.A_DIM)
                    
                    # Always refresh the pad
                    try:
                        pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
                        stdscr.refresh()
                    except curses.error:
                        # Handle potential pad errors
                        pass
                    
                    last_display_time = current_time
                
                # Check for user input with short timeout to maintain display
                stdscr.timeout(100)  # 100ms timeout for getch
                ch = stdscr.getch()
                
                if ch != -1:
                    if ch == curses.KEY_DOWN:
                        # Scroll down one line
                        if pos < actual_lines_count - 1:
                            pos += 1
                            follow_mode = False
                    elif ch == curses.KEY_UP:
                        # Scroll up one line
                        if pos > 0:
                            pos -= 1
                            follow_mode = False
                    elif ch == curses.KEY_NPAGE:  # Page Down
                        # Scroll down one page
                        pos = min(actual_lines_count - 1, pos + (h-5))
                        follow_mode = False
                    elif ch == curses.KEY_PPAGE:  # Page Up
                        # Scroll up one page
                        pos = max(0, pos - (h-5))
                        follow_mode = False
                    elif ch == ord(' '):  # Space - page down
                        pos = min(actual_lines_count - 1, pos + (h-5))
                        follow_mode = False
                    elif ch == curses.KEY_HOME:  # Home - go to start
                        pos = 0
                        follow_mode = False
                    elif ch == ord('g'):  # g - go to start
                        pos = 0
                        follow_mode = False
                    elif ch == curses.KEY_END:  # End - go to end
                        pos = max(0, actual_lines_count - (h-4))
                        follow_mode = True
                    elif ch == ord('G'):  # G - go to end
                        pos = max(0, actual_lines_count - (h-4))
                        follow_mode = True
                    elif ch in (ord('f'), ord('F')):  # Toggle follow mode
                        follow_mode = not follow_mode
                        if follow_mode:
                            pos = max(0, actual_lines_count - (h-4))
                        
                        # Update header
                        stdscr.attron(curses.color_pair(5))
                        self.safe_addstr(stdscr, 0, 0, " " * w)
                        normalized_indicator = " [NORMALIZED]" if self.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if self.wrap_log_lines else " [NOWRAP]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator
                        self.safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        
                        stdscr.refresh()
                    elif ch in (ord('n'), ord('N')):  # Toggle normalization
                        self.normalize_logs = not self.normalize_logs
                        
                        # Renormalize or revert to raw logs
                        new_logs = []
                        if self.normalize_logs:
                            new_logs = self.normalize_container_logs(all_raw_logs)
                        else:
                            new_logs = all_raw_logs.copy()
                        
                        # Rebuild pad with updated content
                        pad = self.rebuild_log_pad(pad, new_logs, w, h, follow_mode)
                        
                        # Update header immediately
                        stdscr.attron(curses.color_pair(5))
                        normalized_indicator = " [NORMALIZED]" if self.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if self.wrap_log_lines else " [NOWRAP]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator
                        self.safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        stdscr.refresh()
                        
                        # Get updated values from rebuild
                        pad = self.log_pad
                        logs = new_logs
                        line_positions = self.log_line_positions
                        actual_lines_count = self.log_actual_lines
                        last_logical_lines_count = len(logs)
                        
                        # Maintain position proportionally
                        if last_logical_lines_count > 0:
                            pos = min(pos, actual_lines_count - 1)
                        else:
                            pos = 0
                    elif ch in (ord('w'), ord('W')):  # Toggle line wrapping
                        self.wrap_log_lines = not self.wrap_log_lines
                        
                        # Reset horizontal scroll if switching to wrapped mode
                        if self.wrap_log_lines:
                            h_scroll = 0
                        
                        # Rebuild pad with new wrapping setting
                        pad = self.rebuild_log_pad(pad, logs, w, h, follow_mode)
                        
                        # Update footer immediately to show horizontal scroll keys if unwrapped
                        if self.wrap_log_lines:
                            footer_text = " ↑/↓:Scroll | PgUp/Dn:Page | F:Toggle Follow | N:Toggle Normalize | W:Toggle Wrap | ESC/Q:Back "
                        else:
                            footer_text = " ↑/↓:Scroll | ←/→:Scroll H | PgUp/Dn:Page | F:Follow | N:Normalize | W:Wrap | ESC/Q:Back "
                        
                        stdscr.attron(curses.color_pair(6))
                        self.safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                        stdscr.attroff(curses.color_pair(6))
                        
                        # Update header immediately to reflect changed wrapping mode
                        stdscr.attron(curses.color_pair(5))
                        normalized_indicator = " [NORMALIZED]" if self.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if self.wrap_log_lines else " [NOWRAP]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator
                        self.safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        stdscr.refresh()
                        
                        # Get updated values from rebuild
                        pad = self.log_pad
                        line_positions = self.log_line_positions
                        actual_lines_count = self.log_actual_lines
                        
                        # Maintain position proportionally
                        if actual_lines_count > 0:
                            # Try to keep the same logical line visible
                            logical_pos = 0
                            for i, line_pos in enumerate(line_positions):
                                if line_pos > pos:
                                    break
                                logical_pos = i
                            
                            # Go to that logical line in new pad
                            if logical_pos < len(line_positions):
                                pos = line_positions[logical_pos]
                            else:
                                pos = 0
                        else:
                            pos = 0
                    elif ch == curses.KEY_MOUSE:
                        try:
                            _, mx, my, _, button_state = curses.getmouse()
                            # Scroll with mouse wheel
                            if button_state & curses.BUTTON4_PRESSED:  # Wheel up
                                pos = max(0, pos - 3)
                                follow_mode = False
                            elif button_state & curses.BUTTON5_PRESSED:  # Wheel down
                                pos = min(actual_lines_count - 1, pos + 3)
                                follow_mode = False
                            # Horizontal scrolling with Shift+wheel or horizontal wheel
                            elif not self.wrap_log_lines and button_state & (1 << 8):  # Horizontal wheel left
                                h_scroll = max(0, h_scroll - 10)
                            elif not self.wrap_log_lines and button_state & (1 << 9):  # Horizontal wheel right
                                h_scroll = min(h_scroll + 10, max_line_length - (w - 5))
                                h_scroll = max(0, h_scroll)
                            # Click on scrollbar to jump
                            elif button_state & curses.BUTTON1_CLICKED and mx == w-1 and 2 <= my < h-2:
                                # Calculate position from click on scrollbar
                                click_percent = (my - 2) / (h - 4)
                                pos = int(click_percent * actual_lines_count)
                                follow_mode = False
                        except curses.error:
                            pass
                    elif ch in (27, ord('q'), ord('Q')):  # ESC or Q to exit
                        running = False
                    elif ch == curses.KEY_RIGHT and not self.wrap_log_lines:  # Right arrow for horizontal scroll
                        # Only allow horizontal scrolling in unwrapped mode
                        h_scroll = min(h_scroll + 10, max_line_length - (w - 5))
                        h_scroll = max(0, h_scroll)  # Ensure positive
                    elif ch == curses.KEY_LEFT and not self.wrap_log_lines:  # Left arrow for horizontal scroll
                        h_scroll = max(0, h_scroll - 10)  # Scroll left by 10 characters
        
        except Exception as e:
            # Show error and wait for key
            stdscr.clear()
            self.safe_addstr(stdscr, h//2, (w-len(str(e))-10)//2, f"Error: {e}", curses.A_BOLD)
            self.safe_addstr(stdscr, h//2+1, (w-25)//2, "Press any key to continue...", curses.A_DIM)
            stdscr.refresh()
            stdscr.getch()
        
        finally:
            # Restore screen state
            stdscr.clear()
            stdscr.nodelay(True)  # Restore non-blocking mode
            stdscr.refresh()

    def show_menu(self, stdscr, container):
        """Show action menu for container with arrow key navigation"""
        try:
            # Determine available actions based on container state
            is_running = container.status == "running"
            is_paused = container.status == "paused"
            
            # Build menu options with keys, labels, and availability
            opts = []
            opts.append(("L", "Logs", True))
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
            self.safe_addstr(menu, 0, (menu_width - len(title))//2, title)
            
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
                    self.safe_addstr(menu, i + 2, 2, " " * (menu_width - 4), curses.A_NORMAL)
                    self.safe_addstr(menu, i + 2, 2, text, attr)
                
                # Draw help
                help_text = "↑/↓:Navigate | Enter/Click:Select | ESC:Cancel"
                self.safe_addstr(menu, menu_height - 1, (menu_width - len(help_text))//2, help_text, curses.A_DIM)
                
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
            
            # Execute selected action
            if action_key == 'l':
                self.show_logs(stdscr, container)
            elif action_key == 's':
                if is_running: 
                    container.stop()
                else: 
                    container.start()
            elif action_key == 'p':
                if is_paused:
                    container.unpause() 
                elif is_running:
                    container.pause()
            elif action_key == 'r' and is_running:
                container.restart()
            elif action_key == 'f':
                img = container.image.tags[0] if container.image.tags else container.image.short_id
                container.remove(force=True)
                self.client.containers.run(img, detach=True)
            elif action_key == 'e' and is_running:
                curses.endwin()
                subprocess.call(["docker","exec","-it",container.id,"/bin/bash"])
                stdscr.clear()
                curses.doupdate()
            # 'c' (cancel) does nothing
                
        except Exception as e:
            # Show error and wait for key
            h, w = stdscr.getmaxyx()
            stdscr.clear()
            self.safe_addstr(stdscr, h//2, (w-len(str(e))-10)//2, f"Error: {e}", curses.A_BOLD)
            self.safe_addstr(stdscr, h//2+1, (w-25)//2, "Press any key to continue...", curses.A_DIM)
            stdscr.refresh()
            stdscr.getch()

def main():
    try:
        curses.wrapper(DockerTUI().draw)
    except docker.errors.DockerException as e:
        print("Error connecting to Docker daemon:", e)
        print("Make sure Docker is running and you have access to /var/run/docker.sock")
    except Exception as e:
        print(f"Unexpected error: {e}")
        print("If the screen isn't restoring properly, try: reset")

if __name__ == '__main__':
    main()
