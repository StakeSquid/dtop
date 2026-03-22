#!/usr/bin/env python3
"""
Docker TUI - Textual Log View
-----------
Advanced log viewer using Textual with search, filter, and normalization.
"""
import asyncio
import re
import subprocess
import os
import sys
from typing import List, Optional, Tuple, Dict
from datetime import datetime
from pathlib import Path

from textual import on, work, events
from textual.app import ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import Header, Footer, RichLog, Input, Label, Static, Button, RadioSet, RadioButton
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Grid
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.syntax import Syntax
import time
import json


class NormalizeLogsRequest(Message):
    """Ask to normalize raw log lines off-thread; request_id drops stale completions."""

    def __init__(self, lines: List[str], request_id: int) -> None:
        self.lines = lines
        self.request_id = request_id
        super().__init__()


def _split_docker_log_timestamp(line: str) -> Tuple[str, str]:
    """Split a Docker log line into (timestamp_token, message). token may be empty."""
    if not line:
        return "", ""
    if "Z " in line:
        z = line.index("Z ")
        return line[: z + 1], line[z + 3 :]
    if " " in line and line[0].isdigit():
        prefix, rest = line.split(" ", 1)
        if "T" in prefix and len(prefix) >= 10:
            return prefix, rest
    return "", line


def _normalize_logs_subprocess(logs: List[str], normalize_script: str) -> List[str]:
    """Run normalize script; intended for worker threads (blocking subprocess I/O)."""
    if not logs:
        return logs
    if not os.path.exists(normalize_script):
        return logs
    if not os.access(normalize_script, os.X_OK):
        try:
            os.chmod(normalize_script, 0o755)
        except OSError:
            return logs
    try:
        log_text = "\n".join(logs)
        process = subprocess.Popen(
            [sys.executable, normalize_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, _stderr = process.communicate(input=log_text, timeout=3)
        if process.returncode != 0:
            return logs
        if stdout:
            normalized = stdout.splitlines()
            if normalized:
                return normalized
        return logs
    except (subprocess.TimeoutExpired, Exception):
        return logs


class TimeFilterDialog(ModalScreen):
    """Dialog for setting time range filter."""
    
    CSS = """
    TimeFilterDialog {
        align: center middle;
    }
    
    #dialog {
        width: 70;
        height: 20;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    
    #dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    
    .field-label {
        width: 12;
        margin-top: 1;
    }
    
    Input {
        width: 50;
        margin-top: 1;
    }
    
    #button-container {
        align: center middle;
        margin-top: 2;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    def __init__(self, from_time: str = "", to_time: str = ""):
        super().__init__()
        self.from_time = from_time
        self.to_time = to_time
    
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("Time Range Filter", id="dialog-title")
            yield Label(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            yield Label("Format: YYYY-MM-DD HH:MM:SS (or partial like '2024-01-01')")
            yield Label("")
            
            with Horizontal():
                yield Label("From time:", classes="field-label")
                yield Input(value=self.from_time, id="from-input", placeholder="Leave empty for no filter")
            
            with Horizontal():
                yield Label("To time:", classes="field-label")
                yield Input(value=self.to_time, id="to-input", placeholder="Leave empty for current time")
            
            with Horizontal(id="button-container"):
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Clear", variant="warning", id="clear")
                yield Button("Cancel", variant="default", id="cancel")
    
    def on_mount(self) -> None:
        """Focus the first input field when mounted."""
        self.query_one("#from-input", Input).focus()
    
    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        # Move to next field or apply
        if event.input.id == "from-input":
            self.query_one("#to-input", Input).focus()
        else:
            self.apply_filter()
    
    @on(Button.Pressed, "#apply")
    def apply_filter(self) -> None:
        from_input = self.query_one("#from-input", Input)
        to_input = self.query_one("#to-input", Input)
        self.dismiss({'from': from_input.value, 'to': to_input.value})
    
    @on(Button.Pressed, "#clear")
    def clear_filter(self) -> None:
        self.dismiss({'from': '', 'to': ''})
    
    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
    
    def on_key(self, event) -> None:
        """Handle ESC key to cancel."""
        if event.key == "escape":
            self.dismiss(None)


class TailLinesDialog(ModalScreen):
    """Dialog for setting tail lines."""
    
    CSS = """
    TailLinesDialog {
        align: center middle;
    }
    
    #dialog {
        width: 50;
        height: 12;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    
    #dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    
    Input {
        width: 100%;
        margin: 1 0;
    }
    
    #button-container {
        align: center middle;
        margin-top: 1;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    def __init__(self, current_tail: int = 1000):
        super().__init__()
        self.current_tail = current_tail
    
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("Change Number of Log Lines", id="dialog-title")
            yield Label("Enter number of lines to show:")
            yield Label("(0 = all lines, default = 1000)")
            yield Input(value=str(self.current_tail) if self.current_tail > 0 else "", 
                       id="tail-input", 
                       placeholder="Number of lines")
            
            with Horizontal(id="button-container"):
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Cancel", variant="default", id="cancel")
    
    def on_mount(self) -> None:
        """Focus the input field when mounted."""
        self.query_one("#tail-input", Input).focus()
    
    @on(Input.Submitted, "#tail-input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input field."""
        self.apply_tail()
    
    @on(Button.Pressed, "#apply")
    def apply_tail(self) -> None:
        tail_input = self.query_one("#tail-input", Input)
        try:
            new_tail = int(tail_input.value) if tail_input.value else 1000
            if new_tail < 0:
                new_tail = 0
            self.dismiss(new_tail)
        except ValueError:
            self.app.notify("Invalid number! Please enter a valid integer.", severity="error")
    
    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
    
    def on_key(self, event) -> None:
        """Handle ESC key to cancel."""
        if event.key == "escape":
            self.dismiss(None)


class ExportDialog(ModalScreen):
    """Dialog for exporting logs."""
    
    CSS = """
    ExportDialog {
        align: center middle;
    }
    
    #dialog {
        width: 60;
        height: 15;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    
    #dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    
    RadioSet {
        width: 100%;
        height: 4;
        margin: 1 0;
    }
    
    Input {
        width: 100%;
        margin: 1 0;
    }
    
    #button-container {
        align: center middle;
        margin-top: 1;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("Export Logs", id="dialog-title")
            yield Label("Select export location:")
            
            with RadioSet(id="location-choice"):
                yield RadioButton("Current directory", value=True)
                yield RadioButton("Custom path")
            
            yield Input(placeholder="Enter custom path (if selected)", 
                       id="custom-path", 
                       disabled=True)
            
            with Horizontal(id="button-container"):
                yield Button("Export", variant="primary", id="export")
                yield Button("Cancel", variant="default", id="cancel")
    
    def on_mount(self) -> None:
        """Set initial focus."""
        self.query_one("#location-choice", RadioSet).focus()
    
    @on(RadioSet.Changed)
    def radio_changed(self, event: RadioSet.Changed) -> None:
        custom_input = self.query_one("#custom-path", Input)
        custom_input.disabled = event.index == 0
        if event.index == 1:
            custom_input.focus()
    
    @on(Input.Submitted, "#custom-path")
    def on_path_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in custom path input."""
        self.export_logs()
    
    @on(Button.Pressed, "#export")
    def export_logs(self) -> None:
        radio_set = self.query_one("#location-choice", RadioSet)
        custom_path = self.query_one("#custom-path", Input)
        
        if radio_set.pressed_index == 0:
            self.dismiss({'type': 'current_dir'})
        else:
            if custom_path.value:
                self.dismiss({'type': 'custom_path', 'path': custom_path.value})
            else:
                self.app.notify("Please enter a custom path", severity="error")
    
    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
    
    def on_key(self, event) -> None:
        """Handle ESC key to cancel."""
        if event.key == "escape":
            self.dismiss(None)


class LogViewScreen(Screen):
    """Advanced log viewer with search, filter, and normalization."""
    
    CSS = """
    LogViewScreen {
        overflow: hidden;
    }
    
    #log-container {
        height: 100%;
        overflow: hidden;
    }
    
    #log-header {
        height: 3;
        background: $panel;
        border-bottom: solid $primary;
        dock: top;
        padding: 0 1;
    }

    #container-name {
        width: 100%;
        text-style: bold;
        text-align: center;
        height: 1;
    }

    #header-controls {
        height: 1;
        layout: horizontal;
    }

    .search-input {
        width: 20;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
    }

    .filter-input {
        width: 20;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
    }

    #status-compact {
        width: 12;
        color: $text-muted;
        margin: 0 1;
    }

    #log-stats {
        width: 1fr;
        text-align: right;
        color: $text-muted;
        margin-right: 1;
    }
    
    #log-content {
        height: 100%;
        border: none;
    }
    
    Footer {
        height: 1;
        dock: bottom;
    }
    """
    
    BINDINGS = [
        Binding("escape", "dismiss", "Back/Clear"),
        Binding("n", "next_search", "Next Match"),
        Binding("shift+n", "toggle_normalize", "Toggle Normalize"),
        Binding("p", "prev_search", "Prev Match"),
        Binding("w", "toggle_wrap", "Toggle Wrap"),
        Binding("/", "focus_search", "Search"),
        Binding("\\", "focus_filter", "Filter"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("ctrl+c", "copy_selection", "Copy"),
        Binding("g", "go_top", "Top"),
        Binding("shift+g", "go_bottom", "Bottom"),
        Binding("t", "show_tail_dialog", "Tail Lines"),
        Binding("shift+t", "toggle_timestamps", "Docker Time"),
        Binding("c", "clear_logs", "Clear"),
        Binding("r", "show_time_filter", "Time Filter"),
        Binding("e", "export_logs", "Export"),
        Binding("s", "toggle_case_sensitive", "Case Toggle"),
        Binding("d", "cycle_theme", "Theme"),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("home", "go_top", "Home", show=False),
        Binding("end", "go_bottom", "End", show=False),
        # Common scroll keys also disable follow
        Binding("up", "page_up", "Up", show=False),
        Binding("down", "page_down", "Down", show=False),
        Binding("k", "page_up", "Up", show=False),
        Binding("j", "page_down", "Down", show=False),
    ]
    
    # Reactive properties
    normalize_enabled = reactive(True)
    wrap_enabled = reactive(True)
    show_timestamps = reactive(False)
    search_term = reactive("")
    filter_term = reactive("")
    current_match_index = reactive(0)
    total_matches = reactive(0)
    case_sensitive = reactive(False)
    tail_lines = reactive(1000)
    time_filter_from = reactive("")
    time_filter_to = reactive("")
    
    def __init__(self, container, app_instance=None):
        super().__init__()
        self.container = container
        self.app_instance = app_instance
        self.raw_logs = []
        self.raw_logs_with_timestamps = []  # Store version with Docker timestamps
        self.processed_logs = []
        self.matches = []
        self.is_following = True
        self.log_offset = 0
        self.max_lines = 25000  # Maximum lines to keep in memory
        self.last_log_time = time.time()
        self.log_update_interval = 2.0
        self._last_raw_len = 0
        self._normalize_latest_id = 0

        # Path to normalize script
        self.normalize_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "..", "utils", "normalize_logs.py"
        )

    def _semantic_color(self, key: str, fallback: str) -> str:
        """Get app-configured semantic color if available."""
        if self.app and hasattr(self.app, "_semantic_color"):
            return self.app._semantic_color(key, fallback)
        return fallback
    
    def compose(self) -> ComposeResult:
        """Create the log view UI."""
        # Footer at bottom
        yield Footer()
        
        # Header docked at top
        with Vertical(id="log-header"):
            yield Label(f"Logs: {self.container.name}", id="container-name")
            with Horizontal(id="header-controls"):
                yield Input(placeholder="Search", id="search-input", classes="search-input")
                yield Input(placeholder="Filter", id="filter-input", classes="filter-input")
                yield Label(f"N:{'Y' if self.normalize_enabled else 'N'} W:{'Y' if self.wrap_enabled else 'N'} F:{'ON' if self.is_following else 'OFF'}", id="status-compact")
                yield Label("", id="log-stats")
        
        # Log content fills remaining space
        yield RichLog(highlight=True, markup=True, wrap=self.wrap_enabled, id="log-content")
    
    async def on_mount(self) -> None:
        """Initialize log viewer when mounted."""
        # Use a UI-thread tick that checks scroll position before spawning worker
        self.set_interval(self.log_update_interval, self._tick_refresh)
        self.load_initial_logs()
        # Ensure initial focus is on the logs, not the search bar
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.focus()
            # Keep RichLog auto-scroll in sync with follow state
            try:
                log_widget.auto_scroll = self.is_following
            except Exception:
                pass
        except Exception:
            pass

    def _is_view_at_bottom(self) -> bool:
        """Best-effort check if the log view is at the bottom (UI thread)."""
        try:
            log_widget = self.query_one("#log-content", RichLog)
        except Exception:
            return True
        # Try RichLog-specific flags if present
        at_end = getattr(log_widget, "is_at_end", None)
        if isinstance(at_end, bool):
            return at_end
        # Fallback to geometry-based check
        try:
            vs = getattr(log_widget, "virtual_size", None)
            so = getattr(log_widget, "scroll_offset", None)
            sz = getattr(log_widget, "size", None)
            if vs and so and sz:
                bottom_threshold = max(0, vs.height - sz.height - 1)
                return so.y >= bottom_threshold
        except Exception:
            pass
        # Default to True to avoid surprising disables
        return True

    def _tick_refresh(self) -> None:
        """UI-thread refresh tick: disable follow if user is not at bottom, else fetch logs."""
        # If user scrolled away, disable follow and keep position
        if not self._is_view_at_bottom():
            if self.is_following:
                self.is_following = False
                # Sync auto_scroll and status
                try:
                    self.query_one("#log-content", RichLog).auto_scroll = False
                except Exception:
                    pass
                self.update_stats()
            return
        # Only refresh when following
        if self.is_following:
            self.refresh_logs()
    
    @work(thread=True)
    def load_initial_logs(self) -> None:
        """Load initial container logs (single Docker API call with timestamps)."""
        try:
            log_params: Dict[str, object] = {"follow": False, "timestamps": True}
            if self.tail_lines > 0:
                log_params["tail"] = self.tail_lines
            raw = self.container.logs(**log_params).decode("utf-8", errors="replace")
            lines_ts = raw.strip().split("\n") if raw else []
            plain = [_split_docker_log_timestamp(line)[1] for line in lines_ts]
            if len(plain) > self.max_lines:
                plain = plain[-self.max_lines :]
                lines_ts = lines_ts[-self.max_lines :]
            self.app.call_from_thread(self.handle_logs_loaded, (plain, lines_ts), True, False)
        except Exception as e:
            self.app.call_from_thread(
                self.handle_logs_loaded, f"Error loading logs: {e}", False, True
            )

    @work(thread=True)
    def refresh_logs(self) -> None:
        """Refresh logs periodically if following (single API call)."""
        try:
            log_params: Dict[str, object] = {
                "tail": min(100, self.tail_lines) if self.tail_lines > 0 else 100,
                "follow": False,
                "timestamps": True,
            }
            raw = self.container.logs(**log_params).decode("utf-8", errors="replace")
            lines_ts = raw.strip().split("\n") if raw else []
            plain = [_split_docker_log_timestamp(line)[1] for line in lines_ts]
            self.app.call_from_thread(self.handle_logs_loaded, (plain, lines_ts), False, False)
        except Exception:
            pass
    
    class LogsLoaded(Message):
        """Message when logs are loaded."""
        def __init__(self, logs: str, initial: bool = False, error: bool = False):
            super().__init__()
            self.logs = logs
            self.initial = initial
            self.error = error
    
    def handle_logs_loaded(self, logs, initial: bool = False, error: bool = False) -> None:
        """Handle loaded logs."""
        if error:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.write(Text(logs, style=self._semantic_color("error_text", "red")))
            return

        if isinstance(logs, tuple):
            logs_plain, logs_with_ts = logs
            if isinstance(logs_plain, str):
                new_lines = logs_plain.strip().split("\n") if logs_plain else []
                new_lines_with_ts = logs_with_ts.strip().split("\n") if logs_with_ts else []
            else:
                new_lines = list(logs_plain) if logs_plain else []
                new_lines_with_ts = list(logs_with_ts) if logs_with_ts else []
        else:
            new_lines = str(logs).strip().split("\n") if logs else []
            new_lines_with_ts = []

        trimmed = False
        if initial:
            self.raw_logs = new_lines
            self.raw_logs_with_timestamps = new_lines_with_ts
            self._last_raw_len = len(self.raw_logs)
            self.process_and_display_logs()
            return

        prev_len = len(self.raw_logs)
        if self.raw_logs and new_lines:
            last_existing = self.raw_logs[-1] if self.raw_logs else ""
            new_start = 0
            for i, line in enumerate(new_lines):
                if line == last_existing:
                    new_start = i + 1
                    break
            if new_start < len(new_lines):
                truly_new = new_lines[new_start:]
                truly_new_with_ts = new_lines_with_ts[new_start:]
                self.raw_logs.extend(truly_new)
                self.raw_logs_with_timestamps.extend(truly_new_with_ts)
        else:
            self.raw_logs.extend(new_lines)
            self.raw_logs_with_timestamps.extend(new_lines_with_ts)

        if len(self.raw_logs) > self.max_lines:
            self.raw_logs = self.raw_logs[-self.max_lines :]
            self.raw_logs_with_timestamps = self.raw_logs_with_timestamps[-self.max_lines :]
            trimmed = True

        if (
            not trimmed
            and not initial
            and self._can_incremental_append()
            and prev_len < len(self.raw_logs)
            and not self.normalize_enabled
        ):
            self._append_new_log_lines(prev_len)
            self._last_raw_len = len(self.raw_logs)
            self.update_stats()
            if self.is_following:
                try:
                    self.query_one("#log-content", RichLog).scroll_end()
                except Exception:
                    pass
            return

        self._last_raw_len = len(self.raw_logs)
        self.process_and_display_logs()

    def _can_incremental_append(self) -> bool:
        return (
            not self.filter_term
            and not self.time_filter_from
            and not self.time_filter_to
            and not self.search_term
        )

    def _append_new_log_lines(self, start_index: int) -> None:
        log_widget = self.query_one("#log-content", RichLog)
        base_idx = len(self.processed_logs)
        for i in range(start_index, len(self.raw_logs)):
            pl = self.raw_logs[i]
            if self.show_timestamps and i < len(self.raw_logs_with_timestamps):
                ts_line = self.raw_logs_with_timestamps[i]
                if ts_line and " " in ts_line:
                    timestamp = ts_line.split(" ", 1)[0]
                    disp = f"{timestamp} {pl}"
                else:
                    disp = pl
            else:
                disp = pl
            self.processed_logs.append(disp)
            log_widget.write(self.format_log_line(disp, base_idx))
            base_idx += 1

    def process_and_display_logs(self) -> None:
        """Process logs with normalization and filters."""
        log_widget = self.query_one("#log-content", RichLog)
        if self.is_following and not self._is_view_at_bottom():
            self.is_following = False
            try:
                log_widget.auto_scroll = False
            except Exception:
                pass
        if not self.raw_logs:
            log_widget.clear()
            self.processed_logs = []
            self.matches = []
            log_widget.write(
                Text("No logs available yet...", style=self._semantic_color("muted_text", "dim"))
            )
            self.update_stats()
            return
        if self.normalize_enabled:
            self._normalize_latest_id += 1
            self.post_message(
                NormalizeLogsRequest(list(self.raw_logs), self._normalize_latest_id)
            )
            return
        self._process_and_display_logs_inline()

    @on(NormalizeLogsRequest)
    async def handle_normalize_logs_request(self, message: NormalizeLogsRequest) -> None:
        if message.request_id != self._normalize_latest_id:
            return
        try:
            if hasattr(asyncio, "to_thread"):
                normalized = await asyncio.to_thread(
                    _normalize_logs_subprocess,
                    message.lines,
                    self.normalize_script,
                )
            else:
                loop = asyncio.get_running_loop()
                normalized = await loop.run_in_executor(
                    None,
                    lambda: _normalize_logs_subprocess(
                        message.lines, self.normalize_script
                    ),
                )
        except Exception as e:
            self.app.notify(f"Normalize failed: {e}", severity="error")
            return
        if message.request_id != self._normalize_latest_id:
            return
        self._apply_normalized_and_render(normalized)

    def _merge_docker_timestamps_into_processed(self) -> None:
        if not self.show_timestamps or not self.raw_logs_with_timestamps:
            return
        processed_with_ts = []
        for i, processed_line in enumerate(self.processed_logs):
            if i < len(self.raw_logs_with_timestamps):
                ts_line = self.raw_logs_with_timestamps[i]
                if ts_line and " " in ts_line:
                    timestamp = ts_line.split(" ", 1)[0]
                    processed_with_ts.append(f"{timestamp} {processed_line}")
                else:
                    processed_with_ts.append(processed_line)
            else:
                processed_with_ts.append(processed_line)
        self.processed_logs = processed_with_ts

    def _process_and_display_logs_inline(self) -> None:
        self.processed_logs = list(self.raw_logs)
        self._merge_docker_timestamps_into_processed()
        if self.time_filter_from or self.time_filter_to:
            self.processed_logs = self.filter_logs_by_time(self.processed_logs)
        if self.filter_term:
            self.processed_logs = self.filter_logs(self.processed_logs, self.filter_term)
        self._write_all_log_lines()

    def _apply_normalized_and_render(self, normalized_plain: List[str]) -> None:
        self.processed_logs = list(normalized_plain)
        self._merge_docker_timestamps_into_processed()
        if self.time_filter_from or self.time_filter_to:
            self.processed_logs = self.filter_logs_by_time(self.processed_logs)
        if self.filter_term:
            self.processed_logs = self.filter_logs(self.processed_logs, self.filter_term)
        self._write_all_log_lines()

    def _write_all_log_lines(self) -> None:
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.clear()
        if not self.processed_logs:
            log_widget.write(
                Text("No logs available yet...", style=self._semantic_color("muted_text", "dim"))
            )
            self.matches = []
            self.update_stats()
            return
        self.matches = []
        for i, line in enumerate(self.processed_logs):
            log_widget.write(self.format_log_line(line, i))
        self.update_stats()
        if self.is_following:
            try:
                log_widget.scroll_end()
            except Exception:
                pass

    def normalize_logs(self, logs: List[str]) -> List[str]:
        """Normalize log lines using the normalize script (blocking; prefer worker path)."""
        return _normalize_logs_subprocess(logs, self.normalize_script)
    
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
    
    def parse_filter_expression(self, filter_string: str) -> List[Tuple[str, str]]:
        """Parse filter expression with AND/OR operators and parentheses.
        
        Supports:
        - Basic terms: word, +word (include), -word/!word (exclude)
        - AND operator: word AND word
        - OR operator: word OR word  
        - Parentheses: (word OR word) AND word
        - Quoted strings: "multi word phrase"
        """
        if not filter_string:
            return []
        
        tokens = []
        current_token = ""
        in_quotes = False
        i = 0
        
        while i < len(filter_string):
            char = filter_string[i]
            
            if char == '"':
                if in_quotes:
                    # End of quoted string
                    if current_token:
                        tokens.append(('TERM', current_token))
                        current_token = ""
                    in_quotes = False
                else:
                    # Start of quoted string
                    if current_token:
                        tokens.append(('TERM', current_token))
                        current_token = ""
                    in_quotes = True
            elif char == ' ' and not in_quotes:
                if current_token:
                    # Check if it's an operator
                    if current_token.upper() == 'AND':
                        tokens.append(('AND', 'AND'))
                    elif current_token.upper() == 'OR':
                        tokens.append(('OR', 'OR'))
                    else:
                        tokens.append(('TERM', current_token))
                    current_token = ""
            elif char == '(' and not in_quotes:
                if current_token:
                    tokens.append(('TERM', current_token))
                    current_token = ""
                tokens.append(('LPAREN', '('))
            elif char == ')' and not in_quotes:
                if current_token:
                    tokens.append(('TERM', current_token))
                    current_token = ""
                tokens.append(('RPAREN', ')'))
            else:
                current_token += char
            i += 1
        
        # Add the last token
        if current_token:
            if current_token.upper() == 'AND':
                tokens.append(('AND', 'AND'))
            elif current_token.upper() == 'OR':
                tokens.append(('OR', 'OR'))
            else:
                tokens.append(('TERM', current_token))
        
        # If no operators, treat as implicit AND between terms
        if not any(t[0] in ('AND', 'OR') for t in tokens):
            # Insert AND between consecutive terms
            new_tokens = []
            for i, token in enumerate(tokens):
                new_tokens.append(token)
                if (i < len(tokens) - 1 and 
                    token[0] in ('TERM', 'RPAREN') and 
                    tokens[i+1][0] in ('TERM', 'LPAREN')):
                    new_tokens.append(('AND', 'AND'))
            tokens = new_tokens
        
        return tokens
    
    def evaluate_filter(self, tokens: List[Tuple[str, str]], line: str) -> bool:
        """Evaluate parsed filter tokens against a log line.
        
        Uses a recursive descent parser to evaluate the expression.
        """
        if not tokens:
            return True
        
        flags = 0 if self.case_sensitive else re.IGNORECASE
        
        def evaluate_term(term: str, line: str) -> bool:
            """Evaluate a single term against the line."""
            # Handle exclusion operators
            if term.startswith('!') or term.startswith('-'):
                search_term = term[1:]
                if search_term:
                    pattern = re.compile(re.escape(search_term), flags)
                    return not pattern.search(line)
                return True
            # Handle explicit inclusion
            elif term.startswith('+'):
                search_term = term[1:]
            else:
                search_term = term
            
            if search_term:
                pattern = re.compile(re.escape(search_term), flags)
                return bool(pattern.search(line))
            return True
        
        def parse_expression(pos: int = 0) -> Tuple[bool, int]:
            """Parse and evaluate expression starting at position pos."""
            if pos >= len(tokens):
                return True, pos
            
            # Parse primary expression (term or parenthesized expression)
            token_type, token_value = tokens[pos]
            
            if token_type == 'TERM':
                result = evaluate_term(token_value, line)
                pos += 1
            elif token_type == 'LPAREN':
                # Parse expression inside parentheses
                result, pos = parse_expression(pos + 1)
                if pos < len(tokens) and tokens[pos][0] == 'RPAREN':
                    pos += 1  # Skip closing paren
            else:
                return True, pos
            
            # Handle operators
            while pos < len(tokens):
                token_type, token_value = tokens[pos]
                
                if token_type == 'AND':
                    pos += 1
                    if pos < len(tokens):
                        right_result, pos = parse_expression(pos)
                        result = result and right_result
                    else:
                        break
                elif token_type == 'OR':
                    pos += 1
                    if pos < len(tokens):
                        right_result, pos = parse_expression(pos)
                        result = result or right_result
                    else:
                        break
                elif token_type == 'RPAREN':
                    # End of parenthesized expression
                    break
                else:
                    break
            
            return result, pos
        
        result, _ = parse_expression()
        return result
    
    def extract_log_timestamp(self, log_line: str) -> Optional[datetime]:
        """Extract timestamp from a log line."""
        # Common timestamp patterns in logs
        patterns = [
            # Docker format: 2024-01-01T12:00:00.000000000Z
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6,9}Z?)',
            # ISO 8601 format: 2024-01-01T12:00:00.000Z
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,3}Z?)',
            # ISO 8601 without microseconds: 2024-01-01T12:00:00Z
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)',
            # Standard format: 2024-01-01 12:00:00
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
            # Time only: 12:00:00
            r'(\d{2}:\d{2}:\d{2})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, log_line)
            if match:
                timestamp_str = match.group(1)
                
                # Try to parse the timestamp
                formats = [
                    '%Y-%m-%dT%H:%M:%S.%fZ',
                    '%Y-%m-%dT%H:%M:%S.%f',
                    '%Y-%m-%dT%H:%M:%SZ',
                    '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M:%S',
                    '%H:%M:%S'
                ]
                
                for fmt in formats:
                    try:
                        parsed = datetime.strptime(timestamp_str, fmt)
                        
                        # For formats without year, use current year
                        if '%Y' not in fmt:
                            parsed = parsed.replace(year=datetime.now().year)
                        if '%m' not in fmt and '%d' not in fmt:
                            # Time only - use today's date
                            today = datetime.now().date()
                            parsed = datetime.combine(today, parsed.time())
                        
                        return parsed
                    except ValueError:
                        continue
        
        return None
    
    def filter_logs_by_time(self, logs: List[str]) -> List[str]:
        """Filter logs by time range."""
        if not self.time_filter_from and not self.time_filter_to:
            return logs
        
        filtered = []
        from_dt = None
        to_dt = None
        
        # Parse time bounds
        if self.time_filter_from:
            try:
                from_dt = datetime.strptime(self.time_filter_from, '%Y-%m-%d %H:%M:%S')
            except:
                try:
                    from_dt = datetime.strptime(self.time_filter_from, '%Y-%m-%d')
                except:
                    pass
        
        if self.time_filter_to:
            try:
                to_dt = datetime.strptime(self.time_filter_to, '%Y-%m-%d %H:%M:%S')
            except:
                try:
                    to_dt = datetime.strptime(self.time_filter_to, '%Y-%m-%d')
                except:
                    pass
        
        for line in logs:
            log_time = self.extract_log_timestamp(line)
            
            if log_time:
                # Check if log time is within range
                if from_dt and log_time < from_dt:
                    continue
                if to_dt and log_time > to_dt:
                    continue
                
                filtered.append(line)
            # Note: logs without timestamps are excluded when time filtering is active
        
        return filtered
    
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
                    text.append(timestamp, style=self._semantic_color("timestamp_text", "dim cyan"))
                    text.append(" ")
                    line = content
            except:
                pass
        
        # Detect log level and apply colors
        line_lower = line.lower()
        if 'error' in line_lower or 'fatal' in line_lower:
            style = self._semantic_color("error_text", "red")
        elif 'warn' in line_lower:
            style = self._semantic_color("warning_text", "yellow")
        elif 'info' in line_lower:
            style = self._semantic_color("info_text", "blue")
        elif 'debug' in line_lower:
            style = self._semantic_color("muted_text", "dim")
        else:
            style = ""
        
        # Apply search highlighting
        if self.search_term:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(self.search_term), flags)
            matches = list(pattern.finditer(line))
            
            if matches:
                self.matches.append(index)
                last_end = 0
                
                for match in matches:
                    # Add text before match
                    text.append(line[last_end:match.start()], style=style)
                    # Add highlighted match
                    if index == self.matches[self.current_match_index] if self.matches else False:
                        # Current match - different highlight
                        text.append(
                            line[match.start():match.end()],
                            style=self._semantic_color("search_highlight_case", "reverse bold yellow"),
                        )
                    else:
                        text.append(
                            line[match.start():match.end()],
                            style=self._semantic_color("search_highlight", "reverse yellow"),
                        )
                    last_end = match.end()
                
                # Add remaining text
                text.append(line[last_end:], style=style)
            else:
                text.append(line, style=style)
        else:
            text.append(line, style=style)
        
        return text
    
    def update_stats(self) -> None:
        """Update statistics display and sync follow state."""
        try:
            stats_label = self.query_one("#log-stats", Label)
            # Keep RichLog auto-scroll in sync with follow mode
            try:
                self.query_one("#log-content", RichLog).auto_scroll = self.is_following
            except Exception:
                pass
            stats = f"L:{len(self.raw_logs)}"
            
            if self.tail_lines > 0:
                stats += f" T:{self.tail_lines}"
            
            if self.time_filter_from or self.time_filter_to:
                stats += " [TIME]"
            
            if self.filter_term:
                stats += f" F:{len(self.processed_logs)}"
            
            if self.search_term and self.matches:
                stats += f" M:{self.current_match_index+1}/{len(self.matches)}"
            
            if self.case_sensitive:
                stats += " [CS]"
            
            stats_label.update(stats)
            
            # Update status compact
            status_label = self.query_one("#status-compact", Label)
            status_label.update(
                f"N:{'Y' if self.normalize_enabled else 'N'} W:{'Y' if self.wrap_enabled else 'N'} F:{'ON' if self.is_following else 'OFF'}"
            )
        except:
            pass  # Silently fail if stats label doesn't exist
    
    def action_dismiss(self) -> None:
        """Go back to main screen or clear filters."""
        # If filters are active, clear them first
        if self.filter_term or self.search_term or self.time_filter_from or self.time_filter_to:
            self.clear_filters()
        else:
            self.app.pop_screen()
    
    def action_next_search(self) -> None:
        """Next search match."""
        if self.search_term and self.matches:
            self.next_match()
    
    def action_toggle_normalize(self) -> None:
        """Toggle log normalization."""
        self.normalize_enabled = not self.normalize_enabled
        self.app.notify(f"Normalization: {'ON' if self.normalize_enabled else 'OFF'}")
        
        # Update status label
        try:
            status_label = self.query_one("#status-compact", Label)
            status_label.update(
                f"N:{'Y' if self.normalize_enabled else 'N'} W:{'Y' if self.wrap_enabled else 'N'} F:{'ON' if self.is_following else 'OFF'}"
            )
        except:
            pass
        
        self.process_and_display_logs()
    
    def action_prev_search(self) -> None:
        """Previous search match."""
        if self.search_term and self.matches:
            self.prev_match()
    
    def action_toggle_follow(self) -> None:
        """Toggle follow mode."""
        self.is_following = not self.is_following
        # Sync RichLog auto-scroll immediately
        try:
            self.query_one("#log-content", RichLog).auto_scroll = self.is_following
        except Exception:
            pass
        self.update_stats()
        if self.is_following:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.scroll_end()
    
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
        """Toggle Docker timestamp display."""
        self.show_timestamps = not self.show_timestamps
        self.app.notify(f"Docker timestamps: {'ON' if self.show_timestamps else 'OFF'}")
        self.process_and_display_logs()
    
    def action_focus_search(self) -> None:
        """Focus search input."""
        self.query_one("#search-input", Input).focus()
    
    def action_focus_filter(self) -> None:
        """Focus filter input."""
        self.query_one("#filter-input", Input).focus()
    
    def action_refresh(self) -> None:
        """Refresh logs manually."""
        self.refresh_logs()
    
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
        self.raw_logs_with_timestamps = []
        self.processed_logs = []
        self._last_raw_len = 0
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.clear()
        self.update_stats()
    
    def action_show_time_filter(self) -> None:
        """Show time filter dialog."""
        def handle_result(result):
            if result is not None:
                self.time_filter_from = result['from']
                self.time_filter_to = result['to']
                self.process_and_display_logs()
        
        self.app.push_screen(
            TimeFilterDialog(self.time_filter_from, self.time_filter_to),
            handle_result
        )
    
    def action_show_tail_dialog(self) -> None:
        """Show tail lines dialog."""
        def handle_result(result):
            if result is not None:
                self.tail_lines = result
                # Reload logs with new tail value
                self.load_initial_logs()
        
        self.app.push_screen(TailLinesDialog(self.tail_lines), handle_result)
    
    def action_toggle_case_sensitive(self) -> None:
        """Toggle case sensitive search/filter."""
        self.case_sensitive = not self.case_sensitive
        self.process_and_display_logs()
    
    def action_page_up(self) -> None:
        """Scroll up one page."""
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.scroll_page_up()
        self.is_following = False
        self.update_stats()
    
    def action_page_down(self) -> None:
        """Scroll down one page."""
        log_widget = self.query_one("#log-content", RichLog)
        log_widget.scroll_page_down()
        self.is_following = False
        self.update_stats()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        """Disable follow when user scrolls up with mouse."""
        self.is_following = False
        self.update_stats()
    
    def action_export_logs(self) -> None:
        """Export logs with dialog."""
        def handle_result(result):
            if result:
                self.export_logs_to_file(result)
        
        self.app.push_screen(ExportDialog(), handle_result)

    def action_cycle_theme(self) -> None:
        """Cycle app theme using the same behavior as the main table view."""
        if hasattr(self.app, "action_cycle_theme"):
            self.app.action_cycle_theme()
        elif hasattr(self.app, "action_toggle_dark"):
            self.app.action_toggle_dark()
    
    def export_logs_to_file(self, export_config: dict) -> None:
        """Export logs to file with metadata."""
        try:
            # Determine export path
            if export_config['type'] == 'current_dir':
                export_dir = Path.cwd()
            else:
                export_dir = Path(export_config['path'])
                if not export_dir.exists():
                    export_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{self.container.name}_logs_{timestamp}.txt"
            filepath = export_dir / filename
            
            # Prepare filter info
            filter_info = {}
            if self.filter_term:
                filter_info['text_filter'] = self.filter_term
            if self.time_filter_from or self.time_filter_to:
                filter_info['time_filter'] = f"From: {self.time_filter_from or 'start'} To: {self.time_filter_to or 'now'}"
            if self.search_term:
                filter_info['search_term'] = self.search_term
            
            # Write logs with metadata
            with open(filepath, 'w', encoding='utf-8') as f:
                # Write header with export info
                f.write(f"# Docker Container Logs Export\n")
                f.write(f"# Container: {self.container.name}\n")
                f.write(f"# Export Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total Lines: {len(self.processed_logs)}\n")
                
                if filter_info:
                    f.write(f"# Filters Applied:\n")
                    for key, value in filter_info.items():
                        f.write(f"#   {key}: {value}\n")
                
                f.write(f"# {'=' * 50}\n\n")
                
                # Write the actual logs
                for line in self.processed_logs:
                    f.write(line + '\n')
            
            self.app.notify(f"Logs exported to {filepath}")
        except Exception as e:
            self.app.notify(f"Failed to export logs: {e}", severity="error")
    
    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        self.search_term = event.value
        self.current_match_index = 0
        self.process_and_display_logs()
        
        # Jump to first match
        if self.matches:
            self.jump_to_match(0)
            self.is_following = False
    
    @on(Input.Submitted, "#filter-input")
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        """Handle filter input submission."""
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
        self.time_filter_from = ""
        self.time_filter_to = ""
        self.process_and_display_logs()
    
    def jump_to_match(self, index: int) -> None:
        """Jump to a specific match."""
        if not self.matches or index >= len(self.matches):
            return
        
        self.current_match_index = index
        match_line = self.matches[index]
        
        # Scroll to the match line
        log_widget = self.query_one("#log-content", RichLog)
        # Calculate approximate position (RichLog doesn't have direct line scrolling)
        # This is a workaround - scroll to approximate position
        if len(self.processed_logs) > 0:
            scroll_percentage = match_line / len(self.processed_logs)
            log_widget.scroll_to(y=int(log_widget.virtual_size.height * scroll_percentage))
        
        self.update_stats()
    
    def next_match(self) -> None:
        """Move to next search match."""
        if self.matches:
            self.current_match_index = (self.current_match_index + 1) % len(self.matches)
            self.jump_to_match(self.current_match_index)
            self.is_following = False
    
    def prev_match(self) -> None:
        """Move to previous search match."""
        if self.matches:
            self.current_match_index = (self.current_match_index - 1) % len(self.matches)
            self.jump_to_match(self.current_match_index)
            self.is_following = False
