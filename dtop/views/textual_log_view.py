#!/usr/bin/env python3
"""
Docker TUI - Textual Log View
-----------
Advanced log viewer using Textual with search, filter, and normalization.
"""
import re
import subprocess
import os
from typing import List, Optional, Tuple
from datetime import datetime

from textual import on, work
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, RichLog, Input, Label, Static, Button
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.syntax import Syntax


class LogViewScreen(Screen):
    """Advanced log viewer with search, filter, and normalization."""
    
    CSS = """
    #log-header {
        height: 3;
        padding: 0 1;
        background: $panel;
        border-bottom: solid $primary;
    }
    
    #container-name {
        width: 30;
        text-style: bold;
    }
    
    .compact-input {
        width: 20;
        height: 1;
        margin: 0 1;
    }
    
    #status-compact {
        width: 10;
        color: $text-muted;
    }
    
    #log-stats {
        width: 20;
        text-align: right;
        color: $text-muted;
    }
    
    #log-content {
        height: 100%;
        border: none;
    }
    
    Footer {
        height: 1;
    }
    """
    
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("n", "toggle_normalize", "Toggle Normalize"),
        Binding("w", "toggle_wrap", "Toggle Wrap"),
        Binding("/", "focus_search", "Search"),
        Binding("f", "focus_filter", "Filter"),
        Binding("ctrl+c", "copy_selection", "Copy"),
        Binding("g", "go_top", "Top"),
        Binding("shift+g", "go_bottom", "Bottom"),
        Binding("t", "toggle_timestamps", "Timestamps"),
        Binding("c", "clear_logs", "Clear"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "save_logs", "Save"),
    ]
    
    # Reactive properties
    normalize_enabled = reactive(True)
    wrap_enabled = reactive(True)
    show_timestamps = reactive(True)
    search_term = reactive("")
    filter_term = reactive("")
    current_match_index = reactive(0)
    total_matches = reactive(0)
    
    def __init__(self, container, app_instance=None):
        super().__init__()
        self.container = container
        self.app_instance = app_instance
        self.raw_logs = []
        self.processed_logs = []
        self.matches = []
        self.is_following = True
        self.log_offset = 0
        self.max_lines = 10000  # Maximum lines to keep in memory
        
        # Path to normalize script
        self.normalize_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "..", "utils", "normalize_logs.py"
        )
    
    def compose(self) -> ComposeResult:
        """Create the log view UI."""
        # Compact header with container name and search
        with Horizontal(id="log-header", classes="compact-header"):
            yield Label(f"📦 {self.container.name[:30]}", id="container-name")
            yield Input(placeholder="Search...", id="search-input", classes="compact-input")
            yield Input(placeholder="Filter...", id="filter-input", classes="compact-input")
            yield Label(f"N:{'Y' if self.normalize_enabled else 'N'} W:{'Y' if self.wrap_enabled else 'N'}", id="status-compact")
            yield Label("", id="log-stats")
        
        # Log content taking up most space
        yield RichLog(highlight=True, markup=True, wrap=self.wrap_enabled, id="log-content")
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize log viewer when mounted."""
        self.set_interval(2.0, self.refresh_logs)
        self.load_initial_logs()
    
    @work(thread=True)
    def load_initial_logs(self) -> None:
        """Load initial container logs."""
        try:
            # Get logs with timestamps
            logs = self.container.logs(
                tail=1000,
                timestamps=True,
                follow=False
            ).decode('utf-8', errors='replace')
            
            # Call the handler directly from the worker thread
            self.app.call_from_thread(self.handle_logs_loaded, logs, True, False)
        except Exception as e:
            self.app.call_from_thread(self.handle_logs_loaded, f"Error loading logs: {e}", False, True)
    
    @work(thread=True)
    def refresh_logs(self) -> None:
        """Refresh logs periodically if following."""
        if not self.is_following:
            return
        
        try:
            # Get new logs since last refresh
            logs = self.container.logs(
                tail=100,
                timestamps=True,
                follow=False
            ).decode('utf-8', errors='replace')
            
            self.app.call_from_thread(self.handle_logs_loaded, logs, False, False)
        except:
            pass  # Silently fail on refresh errors
    
    class LogsLoaded(Message):
        """Message when logs are loaded."""
        def __init__(self, logs: str, initial: bool = False, error: bool = False):
            super().__init__()
            self.logs = logs
            self.initial = initial
            self.error = error
    
    def handle_logs_loaded(self, logs: str, initial: bool = False, error: bool = False) -> None:
        """Handle loaded logs."""
        if error:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.write(Text(logs, style="red"))
            return
        
        # Parse and store logs
        new_lines = logs.strip().split('\n') if logs else []
        
        if initial:
            self.raw_logs = new_lines
        else:
            # Append new logs and trim old ones
            self.raw_logs.extend(new_lines)
            if len(self.raw_logs) > self.max_lines:
                self.raw_logs = self.raw_logs[-self.max_lines:]
        
        # Process and display logs
        self.process_and_display_logs()
    
    def process_and_display_logs(self) -> None:
        """Process logs with normalization and filters."""
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.clear()
        
        # Apply normalization if enabled
        if self.normalize_enabled:
            self.processed_logs = self.normalize_logs(self.raw_logs)
        else:
            self.processed_logs = self.raw_logs
        
        # Apply filter
        if self.filter_term:
            self.processed_logs = self.filter_logs(self.processed_logs, self.filter_term)
        
        # Apply search highlighting
        self.matches = []
        for i, line in enumerate(self.processed_logs):
            display_line = self.format_log_line(line, i)
            log_widget.write(display_line)
        
        # Update stats
        self.update_stats()
        
        # Scroll to bottom if following
        if self.is_following:
            log_widget.scroll_end()
    
    def normalize_logs(self, logs: List[str]) -> List[str]:
        """Normalize log lines using the normalize script."""
        if not os.path.exists(self.normalize_script):
            return logs
        
        try:
            # Run normalization script
            process = subprocess.Popen(
                [self.normalize_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            output, _ = process.communicate(input='\n'.join(logs), timeout=5)
            return output.strip().split('\n') if output else logs
        except:
            return logs  # Return original on error
    
    def filter_logs(self, logs: List[str], filter_expr: str) -> List[str]:
        """Filter logs based on expression."""
        if not filter_expr:
            return logs
        
        filtered = []
        try:
            # Support AND/OR/NOT operations
            tokens = self.parse_filter_expression(filter_expr)
            
            for line in logs:
                if self.evaluate_filter(tokens, line):
                    filtered.append(line)
        except:
            # On parse error, do simple substring match
            filter_lower = filter_expr.lower()
            for line in logs:
                if filter_lower in line.lower():
                    filtered.append(line)
        
        return filtered
    
    def parse_filter_expression(self, expr: str) -> List[Tuple[str, str]]:
        """Parse filter expression into tokens."""
        tokens = []
        parts = expr.split()
        
        for part in parts:
            if part.upper() in ('AND', 'OR', 'NOT'):
                tokens.append(('OP', part.upper()))
            else:
                tokens.append(('TERM', part))
        
        return tokens
    
    def evaluate_filter(self, tokens: List[Tuple[str, str]], line: str) -> bool:
        """Evaluate filter tokens against a line."""
        if not tokens:
            return True
        
        line_lower = line.lower()
        result = True
        current_op = 'AND'
        
        for token_type, token_value in tokens:
            if token_type == 'OP':
                current_op = token_value
            elif token_type == 'TERM':
                term_result = token_value.lower() in line_lower
                
                if current_op == 'NOT':
                    term_result = not term_result
                    current_op = 'AND'  # Reset after NOT
                elif current_op == 'OR':
                    result = result or term_result
                else:  # AND
                    result = result and term_result
        
        return result
    
    def format_log_line(self, line: str, index: int) -> Text:
        """Format a log line with colors and highlighting."""
        text = Text()
        
        # Parse timestamp if present
        if self.show_timestamps and line.startswith('20'):  # Basic timestamp detection
            try:
                # Extract timestamp (assuming ISO format)
                parts = line.split(' ', 1)
                if len(parts) == 2:
                    timestamp, content = parts
                    text.append(timestamp, style="dim cyan")
                    text.append(" ")
                    line = content
            except:
                pass
        
        # Detect log level and apply colors
        line_lower = line.lower()
        if 'error' in line_lower or 'fatal' in line_lower:
            style = "red"
        elif 'warn' in line_lower:
            style = "yellow"
        elif 'info' in line_lower:
            style = "blue"
        elif 'debug' in line_lower:
            style = "dim"
        else:
            style = ""
        
        # Apply search highlighting
        if self.search_term:
            pattern = re.compile(re.escape(self.search_term), re.IGNORECASE)
            matches = list(pattern.finditer(line))
            
            if matches:
                self.matches.append(index)
                last_end = 0
                
                for match in matches:
                    # Add text before match
                    text.append(line[last_end:match.start()], style=style)
                    # Add highlighted match
                    text.append(line[match.start():match.end()], style="reverse yellow")
                    last_end = match.end()
                
                # Add remaining text
                text.append(line[last_end:], style=style)
            else:
                text.append(line, style=style)
        else:
            text.append(line, style=style)
        
        return text
    
    def update_stats(self) -> None:
        """Update statistics display."""
        try:
            stats_label = self.query_one("#log-stats", Label)
            stats = f"L:{len(self.raw_logs)}"
            
            if self.filter_term:
                stats += f" F:{len(self.processed_logs)}"
            
            if self.search_term and self.matches:
                stats += f" M:{len(self.matches)}"
            
            stats_label.update(stats)
        except:
            pass  # Silently fail if stats label doesn't exist
    
    def action_dismiss(self) -> None:
        """Go back to main screen."""
        self.app.pop_screen()
    
    def action_toggle_normalize(self) -> None:
        """Toggle log normalization."""
        self.normalize_enabled = not self.normalize_enabled
        try:
            self.query_one("#status-compact", Label).update(
                f"N:{'Y' if self.normalize_enabled else 'N'} W:{'Y' if self.wrap_enabled else 'N'}"
            )
        except:
            pass
        self.process_and_display_logs()
    
    def action_toggle_wrap(self) -> None:
        """Toggle line wrapping."""
        self.wrap_enabled = not self.wrap_enabled
        try:
            self.query_one("#status-compact", Label).update(
                f"N:{'Y' if self.normalize_enabled else 'N'} W:{'Y' if self.wrap_enabled else 'N'}"
            )
        except:
            pass
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.wrap = self.wrap_enabled
        self.process_and_display_logs()
    
    def action_toggle_timestamps(self) -> None:
        """Toggle timestamp display."""
        self.show_timestamps = not self.show_timestamps
        self.process_and_display_logs()
    
    def action_focus_search(self) -> None:
        """Focus search input."""
        self.query_one("#search-input", Input).focus()
    
    def action_focus_filter(self) -> None:
        """Focus filter input."""
        self.query_one("#filter-input", Input).focus()
    
    def action_go_top(self) -> None:
        """Scroll to top."""
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.scroll_home()
        self.is_following = False
    
    def action_go_bottom(self) -> None:
        """Scroll to bottom."""
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.scroll_end()
        self.is_following = True
    
    def action_clear_logs(self) -> None:
        """Clear displayed logs."""
        self.raw_logs = []
        self.processed_logs = []
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.clear()
        self.update_stats()
    
    def action_refresh(self) -> None:
        """Refresh logs manually."""
        self.refresh_logs()
    
    def action_save_logs(self) -> None:
        """Save logs to file."""
        try:
            filename = f"{self.container.name}_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            with open(filename, 'w') as f:
                f.write('\n'.join(self.raw_logs))
            self.app.notify(f"Logs saved to {filename}")
        except Exception as e:
            self.app.notify(f"Failed to save logs: {e}", severity="error")
    
    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change."""
        self.search_term = event.value
        self.current_match_index = 0
        self.process_and_display_logs()
        
        # Jump to first match
        if self.matches:
            self.jump_to_match(0)
    
    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        self.filter_term = event.value
        self.process_and_display_logs()
    
    def clear_filters(self) -> None:
        """Clear search and filter."""
        try:
            self.query_one("#search-input", Input).value = ""
            self.query_one("#filter-input", Input).value = ""
        except:
            pass
        self.search_term = ""
        self.filter_term = ""
        self.process_and_display_logs()
    
    def jump_to_match(self, index: int) -> None:
        """Jump to a specific match."""
        if not self.matches or index >= len(self.matches):
            return
        
        self.current_match_index = index
        # Would need to implement scrolling to specific line
        # This is a simplified version
        self.update_stats()