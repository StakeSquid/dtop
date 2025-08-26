#!/usr/bin/env python3
"""
Docker TUI - Complete Textual Implementation
-----------
Full-featured Docker TUI using Textual framework with all original features.
"""
import asyncio
import datetime
import docker
import json
import os
import subprocess
import sys
import termios
import time
import tty
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from textual import on, work
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, Button, Switch, RichLog, Select
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual.binding import Binding
from textual.message import Message
from textual.timer import Timer
from textual.coordinate import Coordinate
from rich.text import Text

from ..utils.utils import format_bytes, format_datetime, format_timedelta
from ..utils.config import load_config, save_config
from ..views.textual_log_view import LogViewScreen
from ..views.textual_inspect_view import InspectViewScreen
from .textual_stats import StatsManager


@dataclass
class ContainerInfo:
    """Container information wrapper."""
    container: Any
    stats: Dict[str, Any]


class ContainerViewHeader(Container):
    """Custom header widget for container view."""
    
    DEFAULT_CSS = """
    ContainerViewHeader {
        height: auto;
        min-height: 3;
        background: $panel;
        border-bottom: solid $primary;
        dock: top;
        padding: 0 1;
    }
    
    #header-content {
        height: auto;
        width: 100%;
    }
    
    #header-top {
        height: 1;
        layout: horizontal;
        width: 100%;
        margin: 0 0 1 0;
    }
    
    #header-bottom {
        height: 1;
        layout: horizontal;
        width: 100%;
    }
    
    #app-title {
        text-style: bold;
        width: auto;
    }
    
    #container-count {
        width: auto;
        margin: 0 0 0 2;
    }
    
    #connection-indicator {
        width: auto;
        margin: 0 0 0 1;
    }
    
    #search-input {
        width: 20;
        margin: 0 1 0 0;
    }
    
    #filter-input {
        width: 20;
        margin: 0 1 0 0;
    }
    
    #status-filter {
        width: 15;
        margin: 0 1 0 0;
    }
    
    #search-status {
        width: auto;
        margin: 0 1 0 0;
    }
    
    #filter-indicator {
        width: auto;
        margin: 0 1 0 0;
    }
    
    .spacer {
        width: 1fr;
    }
    """
    
    def __init__(self, app_instance=None):
        super().__init__()
        self.app_instance = app_instance
    
    def compose(self) -> ComposeResult:
        """Compose the header UI."""
        with Vertical(id="header-content"):
            # Top row: Title and status
            with Horizontal(id="header-top"):
                yield Label("Docker TUI", id="app-title")
                yield Label("Containers: 0/0", id="container-count")
                yield Static("", classes="spacer")  # Spacer to push connection to right
                yield Label("Connected", id="connection-indicator")
            
            # Bottom row: Search and filter controls
            with Horizontal(id="header-bottom"):
                yield Input(
                    placeholder="Search (/)",
                    id="search-input"
                )
                yield Input(
                    placeholder="Filter (\\)",
                    id="filter-input"
                )
                yield Select(
                    [("All", "all"),
                     ("Running", "running"),
                     ("Exited", "exited"),
                     ("Stopped", "stopped"),
                     ("Paused", "paused"),
                     ("Created", "created"),
                     ("Restarting", "restarting"),
                     ("Removing", "removing"),
                     ("Dead", "dead")],
                    prompt="Status",
                    value="all",
                    id="status-filter"
                )
                yield Label("", id="search-status")
                yield Label("", id="filter-indicator")
    
    def update_counts(self, total: int, filtered: int, running: int) -> None:
        """Update container counts."""
        try:
            count_label = self.query_one("#container-count", Label)
            if filtered < total:
                count_label.update(f"Containers: {filtered}/{total} (Running: {running})")
            else:
                count_label.update(f"Containers: {total} (Running: {running})")
        except Exception:
            pass
    
    def update_connection_status(self, connected: bool, message: str = "") -> None:
        """Update connection status indicator."""
        try:
            status_label = self.query_one("#connection-indicator", Label)
            if connected:
                status_label.update("✓ Connected")
                status_label.styles.color = "green"
            else:
                status_label.update(f"✗ {message or 'Disconnected'}")
                status_label.styles.color = "red"
        except Exception:
            pass
    
    def update_search_status(self, current: int, total: int) -> None:
        """Update search match status."""
        try:
            search_label = self.query_one("#search-status", Label)
            if total > 0:
                search_label.update(f"Match {current+1}/{total}")
            else:
                search_label.update("")
        except Exception:
            pass
    
    def update_filter_indicator(self, active: bool, text: str = "") -> None:
        """Update filter indicator."""
        try:
            filter_label = self.query_one("#filter-indicator", Label)
            if active and text:
                filter_label.update(f"[Filter: {text[:10]}...]" if len(text) > 10 else f"[{text}]")
            else:
                filter_label.update("")
        except Exception:
            pass


class ContainerViewFooter(Container):
    """Custom footer widget for container view."""
    
    DEFAULT_CSS = """
    ContainerViewFooter {
        height: 2;
        background: $primary;
        border-top: solid $primary;
        dock: bottom;
    }
    
    #footer-top {
        height: 1;
        layout: horizontal;
        padding: 0 1;
    }
    
    #footer-bottom {
        height: 1;
        layout: horizontal;
        padding: 0 1;
    }
    
    .footer-key {
        margin: 0 1 0 0;
        text-style: bold;
    }
    
    .footer-desc {
        margin: 0 2 0 0;
    }
    
    #selection-info {
        width: auto;
        margin: 0 0 0 1;
    }
    
    #refresh-indicator {
        width: auto;
        margin: 0 0 0 1;
    }
    
    .spacer {
        width: 1fr;
    }
    """
    
    def __init__(self, app_instance=None):
        super().__init__()
        self.app_instance = app_instance
        self.last_refresh = time.time()
    
    def compose(self) -> ComposeResult:
        """Compose the footer UI."""
        with Container(id="footer-container"):
            # Top row: Primary key bindings
            with Horizontal(id="footer-top"):
                yield Label("Enter", classes="footer-key")
                yield Label("Actions", classes="footer-desc")
                yield Label("L", classes="footer-key")
                yield Label("Logs", classes="footer-desc")
                yield Label("I", classes="footer-key")
                yield Label("Inspect", classes="footer-desc")
                yield Label("R", classes="footer-key")
                yield Label("Refresh", classes="footer-desc")
                yield Label("?", classes="footer-key")
                yield Label("Help", classes="footer-desc")
                yield Label("Q", classes="footer-key")
                yield Label("Quit", classes="footer-desc")
                yield Static("", classes="spacer")  # Spacer
                yield Label("", id="selection-info")
            
            # Bottom row: Status and secondary bindings
            with Horizontal(id="footer-bottom"):
                yield Label("/", classes="footer-key")
                yield Label("Search", classes="footer-desc")
                yield Label("\\", classes="footer-key")
                yield Label("Filter", classes="footer-desc")
                yield Label("ESC", classes="footer-key")
                yield Label("Clear", classes="footer-desc")
                yield Label("C", classes="footer-key")
                yield Label("Columns", classes="footer-desc")
                yield Label("D", classes="footer-key")
                yield Label("Theme", classes="footer-desc")
                yield Static("", classes="spacer")  # Spacer
                yield Label("⟳ Auto: 2s", id="refresh-indicator")
    
    def update_selection(self, container_name: str = "", container_status: str = "") -> None:
        """Update selected container info."""
        try:
            selection_label = self.query_one("#selection-info", Label)
            if container_name:
                # Truncate long names
                display_name = container_name[:20] + "..." if len(container_name) > 20 else container_name
                selection_label.update(f"[{container_status}] {display_name}")
            else:
                selection_label.update("")
        except Exception:
            pass
    
    def update_refresh_status(self, interval: float, last_refresh: float) -> None:
        """Update refresh indicator."""
        try:
            refresh_label = self.query_one("#refresh-indicator", Label)
            time_since = time.time() - last_refresh
            if time_since < 1:
                refresh_label.update(f"↻ Just refreshed")
            else:
                refresh_label.update(f"↻ Auto: {interval}s")
        except Exception:
            pass
    
    def set_context_keys(self, context: str = "default") -> None:
        """Update key bindings based on context."""
        # This could show different keys based on what's selected
        # For now, keeping the default set
        pass


class ContainerActionModal(ModalScreen):
    """Modal dialog for container actions."""
    
    CSS = """
    ContainerActionModal { align: center middle; }
    
    #action-dialog {
        width: 60;
        height: 80%;
        max-height: 80%;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
        layout: vertical;
    }
    
    #action-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 0 0 1 0;
        height: auto;
        dock: top;
    }
    
    #action-list { 
        height: 1fr;
        width: 100%;
    }
    
    #cancel {
        dock: bottom;
        height: auto;
    }
    
    .action-button { width: 100%; margin: 0 0 1 0; }
    
    .section-separator {
        width: 100%;
        height: 1;
        margin: 1 0;
        border-top: dashed $primary-background;
    }
    
    .info-text {
        margin: 0 0 0 0;
        padding: 0 0 1 0;
    }
    """
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]
    
    def __init__(self, container):
        super().__init__()
        self.container = container
    
    def compose(self) -> ComposeResult:
        """Create the action menu UI."""
        is_running = self.container.status == "running"
        is_paused = self.container.status == "paused"
        
        with Vertical(id="action-dialog"):
            yield Label(f"📦 {self.container.name[:30]}", id="action-title")
            
            # Scrollable middle content - FLATTENED structure
            with ScrollableContainer(id="action-list"):
                # Information section
                yield Static(f"Image: {self.container.image.tags[0] if self.container.image.tags else '<none>'}", classes="info-text")
                yield Static(f"Status: {self.container.status}", classes="info-text")
                yield Static(f"ID: {self.container.short_id}", classes="info-text")
                
                # Section separator
                yield Static("", classes="section-separator")
                
                # Actions section - directly yield buttons, no nested container
                yield Button("📜 View Logs", id="logs", classes="action-button", variant="primary")
                yield Button("🔍 Inspect", id="inspect", classes="action-button", variant="primary")
                
                # Section separator
                yield Static("", classes="section-separator")
                
                # Control section - directly yield buttons, no nested container
                if is_running:
                    yield Button("⏹️ Stop", id="stop", classes="action-button", variant="warning")
                    if not is_paused:
                        yield Button("⏸️ Pause", id="pause", classes="action-button", variant="warning")
                    yield Button("🔄 Restart", id="restart", classes="action-button", variant="warning")
                    yield Button("💻 Exec Shell", id="exec", classes="action-button", variant="primary")
                else:
                    yield Button("▶️ Start", id="start", classes="action-button", variant="success")
                
                if is_paused:
                    yield Button("▶️ Unpause", id="unpause", classes="action-button", variant="success")
                
                yield Button("♻️ Recreate", id="recreate", classes="action-button", variant="error")
                yield Button("🗑️ Remove", id="remove", classes="action-button", variant="error")
            
            # Fixed bottom action
            yield Button("Cancel", id="cancel", classes="action-button", variant="default")
    
    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """Handle button press."""
        action = event.button.id
        if action == "cancel":
            self.action_cancel()
        else:
            self.dismiss(action)
    
    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)


class DockerTUIApp(App):
    """Complete Docker TUI Application using Textual."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #main-container {
        height: 100%;
    }
    
    #filter-bar {
        /* Overlay header */
        dock: top;
        layer: above;
        height: 4;
        width: 100%;
        background: $panel;
        padding: 0;
        border-bottom: solid $primary;
    }

    #search-input {
        width: 20;
        height: 3;
        padding: 0;
        margin: 0 0;
    }

    #filter-input {
        width: 20;
        height: 3;
        padding: 0;
        margin: 0 0;
    }
    
    #status-filter {
        width: 15;
        height: 3;
        margin: 0 0;
    }

    #match-status {
        width: auto;
        margin: 0 1;
    }
    
    #connection-status {
        width: auto;
        margin: 0 1;
    }
    
    #container-table {
        height: 1fr;
        scrollbar-background: $panel;
        scrollbar-corner-color: $panel;
    }
    
    DataTable > .datatable--cursor {
        background: $secondary 30%;
        color: $text;
    }
    
    DataTable > .datatable--header {
        background: $primary;
        color: $text;
        text-style: bold;
    }
    
    DataTable > .datatable--odd-row {
        background: $surface;
    }
    
    DataTable > .datatable--even-row {
        background: $panel;
    }
    
    Notification {
        margin: 1;
        padding: 1;
    }
    """
    
    TITLE = "Docker TUI - Textual Edition"
    SUB_TITLE = "Container Management Interface"
    
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "view_logs", "Logs", show=True),
        Binding("i", "inspect", "Inspect", show=True),
        Binding("enter", "show_actions", "Actions", show=True),
        Binding("/", "focus_search", "Search"),
        Binding("n", "search_next", "Next", show=False),
        Binding("p", "search_prev", "Prev", show=False),
        Binding("\\", "focus_filter", "Filter"),
        Binding("escape", "clear_filter", "Clear"),
        Binding("shift+n", "toggle_normalize", "Normalize"),
        Binding("shift+w", "toggle_wrap", "Wrap"),
        Binding("s", "sort_dialog", "Sort"),
        Binding("?", "help", "Help"),
        Binding("d", "toggle_dark", "Theme"),
        Binding("c", "column_settings", "Columns"),
    ]
    
    # Reactive properties
    filter_text = reactive("")
    search_text = reactive("")
    status_filter = reactive("all")
    current_match_index = reactive(-1)
    total_matches = reactive(0)
    normalize_logs = reactive(True)
    wrap_lines = reactive(True)
    refresh_interval = reactive(2.0)
    show_header = reactive(False)  # Header overlay visibility
    
    def __init__(self):
        super().__init__()
        self.docker_client = None
        self.containers = []
        self.filtered_containers = []
        self.container_map = {}
        self._search_matches: List[str] = []  # container IDs matching search
        self.stats_manager = StatsManager()
        self.stats_cache = {}
        self.columns = load_config()
        self.refresh_timer = None
        # Default sort by NAME column if present
        try:
            name_index = next((i for i, c in enumerate(self.columns) if c.get('name') == 'NAME'), 0)
        except Exception:
            name_index = 0
        self.sort_column = name_index
        self.sort_reverse = False
        self.selected_container_id = None
        self.last_refresh = 0

    # -----------------------------
    # Column width management
    # -----------------------------

    def _usable_table_width(self) -> int:
        """Compute usable character width for the table based on app size.

        Adds a small safety margin for borders/scrollbars.
        """
        total = max(0, int(self.size.width))
        return max(0, total - 2)

    def _compute_column_widths(self) -> List[int]:
        """Compute target widths for all columns to fit the available width.

        - Start with min_width
        - Distribute extra width by column weight
        - Respect max_width when present
        """
        cols = self.columns
        if not cols:
            return []

        usable = self._usable_table_width()
        min_widths = [int(c.get('min_width', c.get('width', 10)) or 0) for c in cols]
        max_widths: List[Optional[int]] = [
            (int(c['max_width']) if c.get('max_width') is not None else None) for c in cols
        ]
        weights = [int(c.get('weight', 0) or 0) for c in cols]

        widths = min_widths[:]
        current = sum(widths)
        if usable <= current:
            return widths

        extra = usable - current

        # Iteratively distribute extra respecting caps
        for _ in range(3):
            expandable = []
            total_weight = 0
            for i, w in enumerate(weights):
                if w <= 0:
                    continue
                mx = max_widths[i]
                remaining_cap = (mx - widths[i]) if (mx is not None) else extra
                if remaining_cap > 0:
                    expandable.append(i)
                    total_weight += max(1, w)

            if not expandable or total_weight == 0 or extra <= 0:
                break

            allocated_total = 0
            for i in expandable:
                share = max(1, weights[i]) / total_weight
                alloc = int(extra * share)
                if alloc == 0 and (extra - allocated_total) > 0:
                    alloc = 1
                if max_widths[i] is not None:
                    alloc = min(alloc, max(0, max_widths[i] - widths[i]))
                widths[i] += max(0, alloc)
                allocated_total += max(0, alloc)

            if allocated_total == 0:
                break
            extra -= allocated_total

        # If extra remains and some columns have no max, distribute round-robin by weight
        if extra > 0:
            no_max = [i for i, mx in enumerate(max_widths) if mx is None and weights[i] > 0]
            no_max.sort(key=lambda i: (-weights[i], i))
            idx = 0
            while extra > 0 and no_max:
                widths[no_max[idx % len(no_max)]] += 1
                extra -= 1
                idx += 1

        return widths

    def _apply_column_widths(self) -> None:
        """Apply computed widths to the DataTable columns."""
        table = self.query_one("#container-table", DataTable)
        widths = self._compute_column_widths()
        for i, w in enumerate(widths):
            try:
                table.set_column_width(i, int(w))  # type: ignore[attr-defined]
            except Exception:
                try:
                    table.set_column_width(f"col_{i}", int(w))  # type: ignore[attr-defined]
                except Exception:
                    pass
    
    def compose(self) -> ComposeResult:
        """Create the main UI."""
        # Main container with table
        with Vertical(id="main-container"):
            # Container table fills space
            yield DataTable(id="container-table", cursor_type="row", zebra_stripes=True)
            
        # Overlay header (hidden initially)
        with Horizontal(id="filter-bar"):
            yield Input(placeholder="Search", id="search-input")
            yield Input(placeholder="Filter", id="filter-input")
            yield Select(
                [("All", "all"), 
                 ("Running", "running"), 
                 ("Exited", "exited"), 
                 ("Stopped", "stopped"),
                 ("Paused", "paused"),
                 ("Created", "created"),
                 ("Restarting", "restarting"),
                 ("Removing", "removing"),
                 ("Dead", "dead")],
                prompt="Status",
                value="all",
                id="status-filter"
            )
            yield Label("", id="match-status")
            yield Label("", id="connection-status")

        # Keep custom footer
        self.footer = ContainerViewFooter(self)
        yield self.footer
    
    async def on_mount(self) -> None:
        """Initialize when app is mounted."""
        await self.connect_docker()
        await self.setup_table()
        await self.start_stats_collection()
        await self.start_refresh_timers()
        
        # Hide header initially
        self.query_one("#filter-bar").visible = False
        
        # Focus the table for keyboard navigation
        table = self.query_one("#container-table", DataTable)
        self._apply_column_widths()
        table.focus()

    def on_resize(self, event: events.Resize) -> None:  # type: ignore[override]
        """Recompute and apply column widths on terminal resize."""
        try:
            self._apply_column_widths()
        except Exception:
            pass
    
    def watch_show_header(self, show: bool) -> None:
        """Toggle header visibility."""
        header = self.query_one("#filter-bar")
        header.visible = show
    
    def on_click(self, event) -> None:
        """Handle clicks to close header when clicking outside."""
        if self.show_header:
            # Simple check: if click is below the header area (y > 4 since header height is 4)
            if event.y > 4:
                self.show_header = False
    
    async def connect_docker(self) -> None:
        """Connect to Docker daemon."""
        try:
            self.docker_client = docker.from_env()
            status = self.query_one("#connection-status", Label)
            status.update("✓ Connected")
            await self.refresh_containers()
        except docker.errors.DockerException as e:
            status = self.query_one("#connection-status", Label)
            status.update("✗ Disconnected")
            self.notify(f"Docker connection failed: {e}", severity="error", timeout=10)
    
    async def setup_table(self) -> None:
        """Setup the data table columns."""
        table = self.query_one("#container-table", DataTable)
        
        # Add columns with proper keys
        for i, col in enumerate(self.columns):
            # Make column sortable
            table.add_column(
                col['name'],
                key=f"col_{i}",
                width=col.get('width', col.get('min_width', 20))
            )
    
    async def start_refresh_timers(self) -> None:
        """Start automatic refresh timers."""
        self.refresh_timer = self.set_interval(
            self.refresh_interval,
            self.refresh_containers,
            name="refresh"
        )
    
    async def refresh_containers(self) -> None:
        """Refresh container list and stats."""
        if not self.docker_client:
            return
        
        current_time = time.time()
        if current_time - self.last_refresh < 0.5:  # Throttle refreshes
            return
        
        self.last_refresh = current_time
        
        try:
            # Always get all containers
            self.containers = self.docker_client.containers.list(all=True)
            
            # Build container map for quick lookup
            self.container_map = {c.id: c for c in self.containers}
            
            # Apply filter and sort
            await self.apply_filter_and_sort()
            # Recompute search matches when list changes
            self._compute_search_matches()
            
            # Update table display
            await self.update_table()
            
            # Update footer refresh status if exists
            if hasattr(self, 'footer'):
                self.footer.update_refresh_status(self.refresh_interval, self.last_refresh)
            
            # Update stats manager with running containers
            running_ids = [c.id for c in self.containers if c.status == 'running']
            self.stats_manager.update_containers(running_ids)
            
        except Exception as e:
            self.log.error(f"Refresh error: {e}")
    
    async def apply_filter_and_sort(self) -> None:
        """Apply filtering and sorting to containers."""
        # Start with all containers
        filtered = self.containers.copy()
        
        # Apply status filter
        if self.status_filter and self.status_filter != "all":
            filtered = [c for c in filtered if c.status.lower() == self.status_filter.lower()]
        
        # Apply text filter
        if self.filter_text:
            filter_lower = self.filter_text.lower()
            filtered = [
                c for c in filtered
                if filter_lower in c.name.lower() or
                   (c.image.tags and filter_lower in c.image.tags[0].lower()) or
                   filter_lower in c.status.lower() or
                   filter_lower in c.short_id.lower()
            ]
        
        self.filtered_containers = filtered
        
        # Sort
        if self.sort_column is not None:
            self.filtered_containers.sort(
                key=lambda c: self.get_sort_value(c, self.sort_column),
                reverse=self.sort_reverse
            )
    
    def get_sort_value(self, container, col_index: int) -> Any:
        """Get value for sorting based on column index."""
        if col_index >= len(self.columns):
            return ""
        
        col = self.columns[col_index]
        col_name = col['name']
        stats = self.stats_manager.get_stats(container.id) or {}
        
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
                    start = datetime.datetime.fromisoformat(
                        container.attrs['State']['StartedAt'][:-1]
                    )
                    return (datetime.datetime.utcnow() - start).total_seconds()
                except:
                    return 0
            return 0
        else:
            return ""
    
    async def update_table(self) -> None:
        """Update the data table with container info."""
        table = self.query_one("#container-table", DataTable)
        
        # Helpers to work across Textual versions
        def _get_row_key_value_at(idx: int):
            try:
                # Preferred API
                key = table.get_row_key(idx)  # type: ignore[attr-defined]
                return getattr(key, "value", key)
            except Exception:
                pass
            try:
                # Fallback: rows or row_keys collections
                rows = getattr(table, "rows", None)
                if rows is not None and 0 <= idx < len(rows):
                    key = rows[idx]
                    return getattr(key, "value", key)
            except Exception:
                pass
            try:
                row_keys = getattr(table, "row_keys", None)
                if row_keys is not None and 0 <= idx < len(row_keys):
                    key = row_keys[idx]
                    return getattr(key, "value", key)
            except Exception:
                pass
            return None
        
        def _set_cursor_to_key_value(key_value) -> bool:
            try:
                rows = getattr(table, "rows", None)
                if rows is not None:
                    for i, rk in enumerate(rows):
                        if getattr(rk, "value", rk) == key_value:
                            table.cursor_coordinate = Coordinate(i, 0)
                            # Attempt to scroll to ensure visibility
                            try:
                                table.scroll_to_row(i)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                            return True
            except Exception:
                pass
            try:
                row_keys = getattr(table, "row_keys", None)
                if row_keys is not None:
                    for i, rk in enumerate(row_keys):
                        if getattr(rk, "value", rk) == key_value:
                            table.cursor_coordinate = Coordinate(i, 0)
                            try:
                                table.scroll_to_row(i)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                            return True
            except Exception:
                pass
            # As a last resort iterate by index using get_row_key
            try:
                for i in range(getattr(table, "row_count", 0)):
                    kv = _get_row_key_value_at(i)
                    if kv == key_value:
                        table.cursor_coordinate = Coordinate(i, 0)
                        try:
                            table.scroll_to_row(i)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        return True
            except Exception:
                pass
            return False
        
        # Remember current selection (index and key)
        current_row_index = 0
        current_key_value = None
        if table.cursor_coordinate:
            try:
                current_row_index = table.cursor_coordinate.row
            except Exception:
                current_row_index = 0
        try:
            current_key_value = _get_row_key_value_at(current_row_index)
        except Exception:
            current_key_value = None
        
        # Clear and rebuild table
        table.clear()
        
        for container in self.filtered_containers:
            row_data = self.build_row_data(container)
            table.add_row(*row_data, key=container.id)
        
        # Restore selection if possible
        if getattr(table, "row_count", 0) > 0:
            restored = False
            if current_key_value is not None:
                restored = _set_cursor_to_key_value(current_key_value)
            if not restored:
                # Maintain relative position by index
                new_index = min(current_row_index, table.row_count - 1)
                table.cursor_coordinate = Coordinate(new_index, 0)
                try:
                    table.scroll_to_row(new_index)  # type: ignore[attr-defined]
                except Exception:
                    pass
    
    def _highlight_text(self, text: str, base_style: str = "") -> Text:
        """Highlight search text within a string."""
        if not self.search_text or not text:
            return Text(text, style=base_style) if base_style else Text(text)
        
        search_lower = self.search_text.lower()
        text_lower = text.lower()
        
        if search_lower not in text_lower:
            return Text(text, style=base_style) if base_style else Text(text)
        
        # Create a Text object with highlighting
        result = Text()
        last_end = 0
        
        while True:
            start = text_lower.find(search_lower, last_end)
            if start == -1:
                # Add remaining text
                if last_end < len(text):
                    result.append(text[last_end:], style=base_style)
                break
            
            # Add text before match
            if start > last_end:
                result.append(text[last_end:start], style=base_style)
            
            # Add highlighted match
            end = start + len(self.search_text)
            highlight_style = f"{base_style} bold reverse" if base_style else "bold reverse"
            result.append(text[start:end], style=highlight_style)
            
            last_end = end
        
        return result
    
    def build_row_data(self, container) -> List:
        """Build row data for a container."""
        row_data = []
        stats = self.stats_manager.get_stats(container.id) or {}
        
        for col in self.columns:
            col_name = col['name']
            
            if col_name == 'NAME':
                row_data.append(self._highlight_text(container.name))
            elif col_name == 'IMAGE':
                image = container.image.tags[0] if container.image.tags else '<none>'
                row_data.append(self._highlight_text(image))
            elif col_name == 'STATUS':
                status = container.status
                # Determine base color for status
                if "running" in status.lower():
                    row_data.append(self._highlight_text(status, "green"))
                elif "exited" in status.lower() or "stopped" in status.lower():
                    row_data.append(self._highlight_text(status, "red"))
                elif "paused" in status.lower():
                    row_data.append(self._highlight_text(status, "yellow"))
                else:
                    row_data.append(self._highlight_text(status))
            elif col_name == 'CPU%':
                cpu_pct = stats.get('cpu', 0)
                row_data.append(f"{cpu_pct:.1f}%")
            elif col_name == 'MEM%':
                mem_pct = stats.get('mem', 0)
                row_data.append(f"{mem_pct:.1f}%")
            elif col_name == 'NET I/O':
                net_in = stats.get('net_in_rate', 0)
                net_out = stats.get('net_out_rate', 0)
                text = f"↓{format_bytes(net_in, '/s')} ↑{format_bytes(net_out, '/s')}"
                row_data.append(text)
            elif col_name == 'DISK I/O':
                disk_read = stats.get('block_read_rate', 0)
                disk_write = stats.get('block_write_rate', 0)
                text = f"R:{format_bytes(disk_read, '/s')} W:{format_bytes(disk_write, '/s')}"
                row_data.append(text)
            elif col_name == 'CREATED AT':
                created = format_datetime(container.attrs.get('Created', ''))
                row_data.append(self._highlight_text(created))
            elif col_name == 'UPTIME':
                uptime = self.calculate_uptime(container)
                row_data.append(self._highlight_text(uptime))
            else:
                row_data.append("")
        
        return row_data
    
    def calculate_uptime(self, container) -> str:
        """Calculate container uptime."""
        if container.attrs.get('State', {}).get('Running'):
            try:
                start = datetime.datetime.fromisoformat(
                    container.attrs['State']['StartedAt'][:-1]
                )
                return format_timedelta(datetime.datetime.utcnow() - start)
            except:
                return "-"
        return "-"
    
    async def update_stats_bar(self) -> None:
        """Update statistics bar."""
        stats_bar = self.query_one("#stats-bar", Static)
        
        total = len(self.containers)
        filtered = len(self.filtered_containers)
        running = sum(1 for c in self.containers if c.status == 'running')
        
        stats_text = f"📊 Total: {total} | Shown: {filtered} | Running: {running}"
        
        if self.filter_text:
            stats_text += f" | Filter: '{self.filter_text}'"
        
        if self.sort_column is not None:
            col_name = self.columns[self.sort_column]['name']
            arrow = "↓" if self.sort_reverse else "↑"
            stats_text += f" | Sort: {col_name} {arrow}"
        
        stats_bar.update(stats_text)
    
    async def start_stats_collection(self) -> None:
        """Start the stats manager."""
        await self.stats_manager.start(self.on_stats_updated)
    
    async def on_stats_updated(self, stats: Dict[str, Any]) -> None:
        """Handle stats update from stats manager."""
        # Update cache with new stats
        self.stats_cache = self.stats_manager.get_all_stats()
        # Request UI update
        await self.update_table()
    
    def get_selected_container(self) -> Optional[Any]:
        """Get currently selected container."""
        table = self.query_one("#container-table", DataTable)
        
        # Try to get from cursor coordinate using robust key retrieval
        if table.cursor_coordinate and table.row_count > 0:
            try:
                row_index = table.cursor_coordinate.row
                if 0 <= row_index < table.row_count:
                    # Prefer API get_row_key if available
                    try:
                        key = table.get_row_key(row_index)  # type: ignore[attr-defined]
                        key_value = getattr(key, "value", key)
                        if key_value:
                            return self.container_map.get(key_value)
                    except Exception:
                        pass
                    # Fallback: rows / row_keys collections
                    try:
                        rows = getattr(table, "rows", None)
                        if rows is not None:
                            rk = rows[row_index]
                            key_value = getattr(rk, "value", rk)
                            if key_value:
                                return self.container_map.get(key_value)
                    except Exception:
                        pass
                    try:
                        row_keys = getattr(table, "row_keys", None)
                        if row_keys is not None:
                            rk = row_keys[row_index]
                            key_value = getattr(rk, "value", rk)
                            if key_value:
                                return self.container_map.get(key_value)
                    except Exception:
                        pass
            except Exception as e:
                self.log.debug(f"Error getting selected container: {e}")
        
        # Fallback to stored selected container ID
        if hasattr(self, 'selected_container_id') and self.selected_container_id:
            return self.container_map.get(self.selected_container_id)
        
        return None

    def _compute_search_matches(self) -> None:
        """Compute container IDs that match current search within the filtered list."""
        self._search_matches = []
        self.total_matches = 0
        self.current_match_index = -1
        if not self.search_text:
            self._update_match_status()
            return
        s = self.search_text.lower()
        for c in self.filtered_containers:
            try:
                image = (c.image.tags[0] if c.image.tags else "")
            except Exception:
                image = ""
            if (
                s in (c.name or "").lower()
                or s in (c.short_id or "").lower()
                or s in (c.status or "").lower()
                or s in image.lower()
            ):
                self._search_matches.append(c.id)
        self.total_matches = len(self._search_matches)
        self.current_match_index = 0 if self.total_matches > 0 else -1
        self._update_match_status()

    def _update_match_status(self) -> None:
        """Update match status label in header."""
        try:
            label = self.query_one("#match-status", Label)
            if self.total_matches > 0 and self.current_match_index >= 0:
                label.update(f"Match {self.current_match_index+1}/{self.total_matches}")
            elif self.search_text:
                label.update("No matches")
            else:
                label.update("")
        except Exception:
            pass

    def _jump_to_current_match(self) -> None:
        """Move the table cursor to the current matched container if exists."""
        if not self._search_matches or self.current_match_index < 0:
            return
        match_id = self._search_matches[self.current_match_index]
        # Find row index for this container
        table = self.query_one("#container-table", DataTable)
        try:
            # Iterate rows to match key value to container id
            for row_idx in range(table.row_count):
                key_val = None
                try:
                    key = table.get_row_key(row_idx)  # type: ignore[attr-defined]
                    key_val = getattr(key, "value", key)
                except Exception:
                    try:
                        rows = getattr(table, "rows", None)
                        if rows is not None:
                            rk = rows[row_idx]
                            key_val = getattr(rk, "value", rk)
                    except Exception:
                        pass
                if key_val == match_id:
                    table.cursor_coordinate = Coordinate(row_idx, 0)
                    self.selected_container_id = match_id
                    break
        except Exception:
            pass
    
    @on(DataTable.HeaderSelected)
    def on_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click for sorting."""
        col_index = event.column_index
        
        if self.sort_column == col_index:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col_index
            self.sort_reverse = False
        
        asyncio.create_task(self.refresh_containers())
    
    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row selection."""
        if event.row_key:
            self.selected_container_id = event.row_key.value
            # Update footer with selection info if exists
            if hasattr(self, 'footer'):
                container = self.container_map.get(event.row_key.value)
                if container:
                    self.footer.update_selection(container.name, container.status)
    
    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row double-click or Enter key."""
        # Hide header when user actively selects a row
        if self.show_header:
            self.show_header = False
        
        if event.row_key:
            container = self.container_map.get(event.row_key.value)
            if container:
                def handle_action(action: str) -> None:
                    if action:
                        asyncio.create_task(self.execute_container_action(container, action))
                
                self.push_screen(ContainerActionModal(container), handle_action)
    
    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        self.filter_text = event.value
        # Apply filter/sort locally against the current list to keep typing snappy
        async def _apply_local():
            try:
                await self.apply_filter_and_sort()
                await self.update_table()
            except Exception:
                # Fallback to full refresh if something goes wrong
                await self.refresh_containers()
        asyncio.create_task(_apply_local())

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change for containers list."""
        self.search_text = event.value
        self._compute_search_matches()
        # Update table to show highlighting
        asyncio.create_task(self.update_table())
        # Auto-jump to the first match for more responsive UX
        if self._search_matches and self.current_match_index >= 0:
            self._jump_to_current_match()

    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        """Apply search and hide header when submitting."""
        self.search_text = event.value
        self._compute_search_matches()
        if self._search_matches:
            self._jump_to_current_match()
        # Hide header after applying
        self.show_header = False
        asyncio.create_task(self.update_table())
    
    @on(Input.Submitted, "#filter-input")  
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        """Apply filter and hide header when submitting."""
        self.filter_text = event.value
        # Hide header after applying
        self.show_header = False
        asyncio.create_task(self.refresh_containers())

    def action_search_next(self) -> None:
        """Move to next container search match and select it."""
        if self.total_matches <= 0:
            return
        self.current_match_index = (self.current_match_index + 1) % self.total_matches
        self._update_match_status()
        self._jump_to_current_match()

    def action_search_prev(self) -> None:
        """Move to previous container search match and select it."""
        if self.total_matches <= 0:
            return
        self.current_match_index = (self.current_match_index - 1) % self.total_matches
        self._update_match_status()
        self._jump_to_current_match()
    
    @on(Select.Changed)
    def on_status_filter_changed(self, event: Select.Changed) -> None:
        """Handle status filter dropdown change."""
        if event.select.id == "status-filter":
            self.status_filter = event.value
            asyncio.create_task(self.refresh_containers())
    
    @on(Switch.Changed)
    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle switch toggles."""
        switch_id = event.switch.id
        
        if switch_id == "normalize-switch":
            self.normalize_logs = event.value
        elif switch_id == "wrap-switch":
            self.wrap_lines = event.value
    
    def action_show_actions(self) -> None:
        """Show container actions menu."""
        container = self.get_selected_container()
        if container:
            def handle_action(action: str) -> None:
                if action:
                    asyncio.create_task(self.execute_container_action(container, action))
            
            self.push_screen(ContainerActionModal(container), handle_action)
    
    async def execute_container_action(self, container, action: str) -> None:
        """Execute a container action."""
        try:
            if action == "logs":
                self.push_screen(LogViewScreen(container, self))
            elif action == "inspect":
                self.push_screen(InspectViewScreen(container))
            elif action == "stop":
                container.stop()
                self.notify(f"Stopped {container.name}", severity="information")
                await self.refresh_containers()
            elif action == "start":
                container.start()
                self.notify(f"Started {container.name}", severity="information")
                await self.refresh_containers()
            elif action == "restart":
                container.restart()
                self.notify(f"Restarted {container.name}", severity="information")
                await self.refresh_containers()
            elif action == "pause":
                container.pause()
                self.notify(f"Paused {container.name}", severity="information")
                await self.refresh_containers()
            elif action == "unpause":
                container.unpause()
                self.notify(f"Unpaused {container.name}", severity="information")
                await self.refresh_containers()
            elif action == "remove":
                container.remove(force=True)
                self.notify(f"Removed {container.name}", severity="warning")
                await self.refresh_containers()
            elif action == "exec":
                # Execute shell into container
                await self.execute_shell_into_container(container)
            elif action == "recreate":
                # Show recreate dialog
                def handle_recreate_result(result: Optional[Dict[str, Any]]) -> None:
                    if result:
                        if result.get('action') == 'recreate-compose':
                            asyncio.create_task(self.execute_docker_compose_recreate(
                                container,
                                result['path'],
                                result['service'],
                                result.get('compose_file')  # Pass the selected file
                            ))
                        elif result.get('action') == 'recreate-simple':
                            asyncio.create_task(self.execute_simple_recreate(container))
                
                self.push_screen(RecreateContainerModal(container), handle_recreate_result)
        except Exception as e:
            self.notify(f"Action failed: {e}", severity="error")
    
    def action_view_logs(self) -> None:
        """View logs for selected container."""
        container = self.get_selected_container()
        if container:
            self.push_screen(LogViewScreen(container, self))
    
    def action_inspect(self) -> None:
        """Inspect selected container."""
        container = self.get_selected_container()
        if container:
            self.push_screen(InspectViewScreen(container))
    
    def action_focus_filter(self) -> None:
        """Show header and focus filter input."""
        self.show_header = True
        self.query_one("#filter-input", Input).focus()

    def action_focus_search(self) -> None:
        """Show header and focus search input."""
        self.show_header = True
        self.query_one("#search-input", Input).focus()
    
    def action_clear_filter(self) -> None:
        """Clear filter and hide header."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = ""
        self.filter_text = ""
        
        # Reset status filter to all
        try:
            status_select = self.query_one("#status-filter", Select)
            status_select.value = "all"
        except Exception:
            pass
        self.status_filter = "all"
        
        # Also clear search if present
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.value = ""
        except Exception:
            pass
        self.search_text = ""
        self._compute_search_matches()
        
        # Hide header
        self.show_header = False
        
        asyncio.create_task(self.refresh_containers())
    
    def action_toggle_normalize(self) -> None:
        """Toggle log normalization."""
        switch = self.query_one("#normalize-switch", Switch)
        switch.value = not switch.value
    
    def action_toggle_wrap(self) -> None:
        """Toggle line wrapping."""
        switch = self.query_one("#wrap-switch", Switch)
        switch.value = not switch.value
    
    def action_refresh(self) -> None:
        """Manual refresh."""
        asyncio.create_task(self.refresh_containers())
        self.notify("Refreshed", timeout=1)
    
    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.dark = not self.dark
    
    def action_help(self) -> None:
        """Show help."""
        help_text = """
        Keyboard Shortcuts:
        
        Navigation:
        ↑/↓ - Select container
        Enter - Show actions menu
        
        Actions:
        L - View logs
        I - Inspect container
        R - Refresh
        
        Filtering:
        \\ - Focus filter
        ESC - Clear filter
        
        Settings:
        N - Toggle normalize logs
        W - Toggle wrap lines
        D - Toggle dark mode
        
        Q - Quit
        """
        self.notify(help_text, title="Help", timeout=10)
    
    async def execute_shell_into_container(self, container) -> None:
        """Execute an interactive shell session into the container."""
        try:
            # Check if container is running
            if container.status != "running":
                self.notify(f"Container {container.name} is not running", severity="warning")
                return
            
            # Check if container is Windows or Linux based
            # Try to detect OS by checking for typical Windows paths
            is_windows_container = False
            try:
                test_result = container.exec_run("test -d C:\\Windows")
                if hasattr(test_result, 'exit_code'):
                    is_windows_container = test_result.exit_code == 0
                elif isinstance(test_result, tuple):
                    is_windows_container = test_result[0] == 0
            except Exception:
                pass
            
            # Determine available shells in order of preference
            if is_windows_container:
                shells_to_try = ["powershell.exe", "cmd.exe"]
            else:
                shells_to_try = ["/bin/bash", "/bin/sh", "/bin/ash", "/bin/zsh"]
            available_shell = None
            
            # Test which shell is available
            for shell in shells_to_try:
                try:
                    # Test if shell exists in container
                    if is_windows_container:
                        # For Windows, try to run the shell with a simple command
                        test_cmd = f'{shell} /c "exit 0"' if shell == "cmd.exe" else f'{shell} -Command "exit 0"'
                    else:
                        # For Linux, test if shell exists
                        test_cmd = f"test -e {shell}"
                    
                    exec_result = container.exec_run(test_cmd)
                    # Handle both old and new docker-py API versions
                    if hasattr(exec_result, 'exit_code'):
                        exit_code = exec_result.exit_code
                    else:
                        # Older versions might return tuple (exit_code, output)
                        exit_code = exec_result[0] if isinstance(exec_result, tuple) else 1
                    
                    if exit_code == 0:
                        available_shell = shell
                        break
                except Exception:
                    continue
            
            if not available_shell:
                self.notify(f"No shell found in container {container.name}", severity="error")
                return
            
            # Check if the container has TTY capability
            container_info = container.attrs
            has_tty = container_info.get('Config', {}).get('Tty', False)
            
            # Build the docker exec command
            docker_cmd = ["docker", "exec"]
            
            # Add interactive and TTY flags if supported
            if has_tty or not is_windows_container:
                docker_cmd.extend(["-it"])
            else:
                # For non-TTY containers, still try interactive mode
                docker_cmd.append("-i")
            
            # Set user if specified in container config
            user = container_info.get('Config', {}).get('User', None)
            if user:
                docker_cmd.extend(["-u", user])
            
            # Set working directory to a sensible default if available
            working_dir = container_info.get('Config', {}).get('WorkingDir', None)
            if working_dir:
                docker_cmd.extend(["-w", working_dir])
            
            # Add container ID and shell
            docker_cmd.extend([container.id, available_shell])
            
            # Show notification about entering shell
            self.notify(f"Entering shell in {container.name}...", timeout=1)
            
            # Save terminal state and prepare for suspension
            def run_docker_exec():
                """Run docker exec in a clean terminal environment."""
                # Save current terminal settings
                old_tty = None
                try:
                    old_tty = termios.tcgetattr(sys.stdin)
                except Exception:
                    pass
                
                # Reset terminal to a clean state
                sys.stdout.write('\033c')  # Reset terminal
                sys.stdout.write('\033[?1000l')  # Disable mouse reporting
                sys.stdout.write('\033[?1002l')  # Disable mouse motion tracking  
                sys.stdout.write('\033[?1003l')  # Disable any mouse mode
                sys.stdout.write('\033[?1006l')  # Disable SGR mouse mode
                sys.stdout.write('\033[?1015l')  # Disable urxvt mouse mode
                sys.stdout.write('\033[?25h')   # Show cursor
                sys.stdout.write('\033[0m')  # Reset all attributes
                sys.stdout.write('\033[2J\033[H')  # Clear screen and move cursor to top
                sys.stdout.flush()
                
                # Small delay to ensure terminal is ready
                time.sleep(0.1)
                
                try:
                    # Execute the docker command in the terminal
                    result = subprocess.call(docker_cmd)
                    
                    # Handle different exit codes
                    if result == 0:
                        # Success - do nothing, just resume
                        pass
                    elif result == 125:
                        # Docker daemon error
                        print("\nError: Docker daemon error occurred")
                    elif result == 126:
                        # Container command not executable
                        print(f"\nError: Shell {available_shell} is not executable in container")
                    elif result == 127:
                        # Container command not found
                        print(f"\nError: Shell {available_shell} not found in container")
                    else:
                        # Other error
                        print(f"\nShell exited with code {result}")
                    
                    # Wait for user to acknowledge if there was an error
                    if result != 0:
                        print("\nPress Enter to return to Docker TUI...")
                        input()
                        
                except FileNotFoundError:
                    print("\nError: Docker command not found. Please ensure Docker is installed.")
                    print("Press Enter to return to Docker TUI...")
                    input()
                except KeyboardInterrupt:
                    # User pressed Ctrl+C - this is normal
                    print("\n\nReturning to Docker TUI...")
                except Exception as e:
                    print(f"\nError executing shell: {e}")
                    print("Press Enter to return to Docker TUI...")
                    input()
                finally:
                    # Restore terminal settings
                    if old_tty:
                        try:
                            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
                        except Exception:
                            pass
                    
                    # Clear screen and reset terminal state before returning
                    sys.stdout.write('\033[2J\033[H')  # Clear screen
                    sys.stdout.write('\033[0m')  # Reset attributes
                    sys.stdout.flush()
            
            # Use Textual's suspend context manager with the callback
            with self.suspend():
                run_docker_exec()
            
            # After resuming, the app will automatically restore mouse mode and redraw
            
        except Exception as e:
            self.notify(f"Failed to execute shell: {e}", severity="error")
    
    async def execute_simple_recreate(self, container) -> None:
        """Recreate a container without docker-compose (simple docker run)."""
        try:
            # Get container configuration
            container_info = container.attrs
            config = container_info.get('Config', {})
            host_config = container_info.get('HostConfig', {})
            
            # Get image
            image = container.image
            image_name = image.tags[0] if image.tags else image.id
            
            # Store container name
            container_name = container.name
            
            # Get important configurations
            env_vars = config.get('Env', [])
            volumes = []
            binds = host_config.get('Binds', [])
            ports = {}
            
            # Parse port bindings
            port_bindings = host_config.get('PortBindings', {})
            for container_port, host_ports in port_bindings.items():
                if host_ports:
                    for hp in host_ports:
                        if hp.get('HostPort'):
                            ports[container_port] = hp['HostPort']
            
            # Get network mode
            network_mode = host_config.get('NetworkMode', 'default')
            
            # Get restart policy  
            restart_policy = host_config.get('RestartPolicy', {})
            restart = None
            if restart_policy.get('Name'):
                restart = restart_policy['Name']
                if restart == 'on-failure' and restart_policy.get('MaximumRetryCount'):
                    restart = f"on-failure:{restart_policy['MaximumRetryCount']}"
            
            # Stop and remove the container
            self.notify(f"Stopping {container_name}...", timeout=1)
            try:
                container.stop(timeout=10)
            except Exception:
                pass  # Container might already be stopped
            
            self.notify(f"Removing {container_name}...", timeout=1)
            container.remove(force=True)
            
            # Create new container with same config
            self.notify(f"Creating {container_name}...", timeout=1)
            
            # Build docker run arguments
            run_kwargs = {
                'image': image_name,
                'name': container_name,
                'detach': True,
                'environment': env_vars,
            }
            
            # Add optional parameters
            if binds:
                run_kwargs['volumes'] = binds
            if ports:
                run_kwargs['ports'] = ports
            if network_mode and network_mode != 'default':
                run_kwargs['network_mode'] = network_mode
            if restart:
                run_kwargs['restart_policy'] = {'Name': restart}
            
            # Add command if present
            cmd = config.get('Cmd')
            if cmd:
                run_kwargs['command'] = cmd
            
            # Add entrypoint if present
            entrypoint = config.get('Entrypoint')
            if entrypoint:
                run_kwargs['entrypoint'] = entrypoint
            
            # Add working directory
            working_dir = config.get('WorkingDir')
            if working_dir:
                run_kwargs['working_dir'] = working_dir
            
            # Add user
            user = config.get('User')
            if user:
                run_kwargs['user'] = user
            
            # Create and start new container
            new_container = self.docker_client.containers.run(**run_kwargs)
            
            self.notify(f"Successfully recreated {container_name}", severity="information")
            
            # Refresh the container list
            await self.refresh_containers()
            
        except Exception as e:
            self.notify(f"Failed to recreate container: {e}", severity="error")
            # Try to clean up if something went wrong
            try:
                # Check if old container still exists and remove it
                old_container = self.docker_client.containers.get(container.id)
                old_container.remove(force=True)
            except Exception:
                pass
    
    async def execute_docker_compose_recreate(self, container, compose_path: str, service_name: str, selected_file: Optional[str] = None) -> None:
        """Execute docker-compose to recreate a container."""
        try:
            # Validate path exists
            if not os.path.exists(compose_path):
                self.notify(f"Path does not exist: {compose_path}", severity="error")
                return
            
            if not os.path.isdir(compose_path):
                self.notify(f"Path is not a directory: {compose_path}", severity="error")
                return
            
            # Use selected file if provided, otherwise check for standard files
            compose_file = selected_file
            if not compose_file:
                # Check for standard docker-compose files
                for filename in ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml']:
                    file_path = os.path.join(compose_path, filename)
                    if os.path.exists(file_path):
                        compose_file = filename
                        break
            
            # Verify the selected/detected file exists
            if compose_file:
                full_path = os.path.join(compose_path, compose_file)
                if not os.path.exists(full_path):
                    self.notify(f"Compose file not found: {compose_file}", severity="error")
                    return
            else:
                self.notify("No docker-compose file specified or found", severity="error")
                return
            
            # Check if docker-compose or docker compose is available
            compose_cmd = None
            try:
                # Try docker compose (newer integrated version)
                result = subprocess.run(
                    ["docker", "compose", "version"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    compose_cmd = ["docker", "compose"]
            except Exception:
                pass
            
            if not compose_cmd:
                try:
                    # Try docker-compose (standalone version)
                    result = subprocess.run(
                        ["docker-compose", "version"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        compose_cmd = ["docker-compose"]
                except Exception:
                    pass
            
            if not compose_cmd:
                self.notify(
                    "Docker Compose not found. Please install docker-compose or use Docker Desktop",
                    severity="error"
                )
                return
            
            # Build the recreate command
            recreate_cmd = compose_cmd + [
                "-f", os.path.join(compose_path, compose_file),
                "up", "-d",
                "--force-recreate",
                "--no-deps",  # Don't recreate dependencies
                service_name
            ]
            
            # Show notification
            self.notify(f"Recreating {service_name}...", timeout=2)
            
            # Execute in a worker to not block the UI
            self._run_compose_command(recreate_cmd, compose_path, service_name)
            
        except Exception as e:
            self.notify(f"Failed to recreate container: {e}", severity="error")
    
    def _run_compose_command_sync(self, cmd: List[str], cwd: str, service_name: str) -> None:
        """Run docker-compose command in a separate thread (synchronous)."""
        try:
            # Run the command
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            if result.returncode == 0:
                # Success
                self.call_from_thread(
                    self.notify,
                    f"Successfully recreated {service_name}",
                    severity="information"
                )
                # Refresh containers list
                self.call_from_thread(asyncio.create_task, self.refresh_containers())
            else:
                # Command failed
                error_msg = result.stderr or result.stdout or "Unknown error"
                # Truncate long error messages
                if len(error_msg) > 200:
                    error_msg = error_msg[:200] + "..."
                self.call_from_thread(
                    self.notify,
                    f"Failed to recreate {service_name}: {error_msg}",
                    severity="error",
                    timeout=10
                )
        except subprocess.TimeoutExpired:
            self.call_from_thread(
                self.notify,
                f"Recreate operation timed out for {service_name}",
                severity="error"
            )
        except Exception as e:
            self.call_from_thread(
                self.notify,
                f"Error running docker-compose: {e}",
                severity="error"
            )
    
    @work(thread=True)
    def _run_compose_command(self, cmd: List[str], cwd: str, service_name: str) -> None:
        """Wrapper to run compose command in a worker thread."""
        self._run_compose_command_sync(cmd, cwd, service_name)

    # -----------------------------
    # Column settings UI
    # -----------------------------

    def action_column_settings(self) -> None:
        """Open a simple modal to edit per-column min/max widths."""
        self.push_screen(ColumnSettingsModal(self.columns), self._handle_column_settings_result)

    def _handle_column_settings_result(self, result: Optional[List[Dict[str, Any]]]) -> None:
        """Handle updated columns from settings modal."""
        if not result:
            return
        cleaned = []
        for old, new in zip(self.columns, result):
            try:
                min_w = max(1, int(new.get('min_width', old.get('min_width', 1))))
                max_w_val = new.get('max_width', old.get('max_width'))
                max_w = int(max_w_val) if (max_w_val not in (None, "",)) else None
                width = max(min_w, int(old.get('width', min_w)))
                if max_w is not None:
                    width = min(width, max_w)
                cleaned.append({
                    **old,
                    'min_width': min_w,
                    'max_width': max_w,
                    'width': width,
                })
            except Exception:
                cleaned.append(old)

        self.columns = cleaned
        try:
            save_config(self.columns)
        except Exception:
            pass
        # Recreate columns to ensure keys + widths, then repopulate
        try:
            table = self.query_one("#container-table", DataTable)
            current = table.cursor_coordinate
            table.clear(columns=True)
            for i, col in enumerate(self.columns):
                table.add_column(col['name'], key=f"col_{i}", width=col.get('width', col.get('min_width', 20)))
            asyncio.create_task(self.update_table())
            self._apply_column_widths()
            if current:
                table.cursor_coordinate = current
        except Exception:
            pass
    
    async def on_unmount(self) -> None:
        """Cleanup when app closes."""
        if self.refresh_timer:
            self.refresh_timer.stop()
        await self.stats_manager.stop()


class RecreateContainerModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal dialog for recreating a container with docker-compose."""
    
    CSS = """
    RecreateContainerModal { align: center middle; }
    
    #recreate-dialog {
        width: 80;
        height: auto;
        max-height: 35;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
        layout: vertical;
    }
    
    #recreate-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 0 0 1 0;
        height: auto;
    }
    
    #info-section {
        height: auto;
        margin: 0 0 1 0;
    }
    
    .info-label {
        margin: 0 0 0 0;
        height: 1;
    }
    
    #path-section {
        height: auto;
        margin: 1 0;
    }
    
    #path-input {
        width: 100%;
        margin: 0 0 1 0;
    }
    
    #compose-file-select {
        width: 100%;
        margin: 0 0 1 0;
        display: none;
    }
    
    #compose-options {
        height: auto;
        margin: 1 0;
    }
    
    .option-row {
        layout: horizontal;
        height: auto;
        margin: 0 0 0 0;
    }
    
    #actions {
        layout: horizontal;
        margin-top: 1;
        width: 100%;
        height: auto;
    }
    
    .action-button {
        width: 1fr;
        margin: 0 1 0 0;
    }
    
    #warning-text {
        color: $warning;
        margin: 1 0;
        text-align: center;
    }
    """
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, container):
        super().__init__()
        self.container = container
        self.current_path = os.getcwd()
        self.service_name = None
        self.compose_project = None
        self.selected_compose_file = None
        self.yaml_files = []
        self._detect_compose_info()
    
    def _detect_compose_info(self):
        """Try to detect docker-compose project and service name from container labels."""
        try:
            labels = self.container.labels
            # Common docker-compose labels
            self.compose_project = labels.get('com.docker.compose.project', '')
            self.service_name = labels.get('com.docker.compose.service', '')
            
            # Try to detect compose working directory
            compose_dir = labels.get('com.docker.compose.project.working_dir', '')
            if compose_dir and os.path.exists(compose_dir):
                self.current_path = compose_dir
        except Exception:
            pass
    
    def on_mount(self) -> None:
        """Initialize the dialog when mounted."""
        # Trigger initial path validation to populate dropdown if needed
        path_input = self.query_one("#path-input", Input)
        if path_input.value:
            # Simulate path change to trigger validation
            self.on_path_changed(Input.Changed(path_input, path_input.value))
    
    def compose(self) -> ComposeResult:
        """Create the recreate dialog UI."""
        with Vertical(id="recreate-dialog"):
            yield Label(f"♻️ Recreate Container: {self.container.name}", id="recreate-title")
            
            # Info section
            with Container(id="info-section"):
                image_name = self.container.image.tags[0] if self.container.image.tags else self.container.image.short_id
                yield Label(f"Image: {image_name}", classes="info-label")
                yield Label(f"Status: {self.container.status}", classes="info-label")
                
                if self.compose_project:
                    yield Label(f"Compose Project: {self.compose_project}", classes="info-label")
                if self.service_name:
                    yield Label(f"Service Name: {self.service_name}", classes="info-label")
            
            # Path input section
            with Container(id="path-section"):
                yield Label("Docker Compose Directory:", classes="info-label")
                yield Input(
                    value=self.current_path,
                    id="path-input",
                    placeholder="Enter path to docker-compose.yml (leave empty for simple recreate)"
                )
                # Dropdown for YAML files (hidden by default)
                yield Select(
                    [("No file selected", "")],  # Provide a default option
                    prompt="Select a compose file",
                    id="compose-file-select",
                    allow_blank=True
                )
                yield Label("Note: Leave empty to recreate without docker-compose", classes="info-label")
            
            # Compose detection status
            yield Label("", id="compose-status")
            
            # Warning
            yield Label(
                "⚠️ This will stop, remove and recreate the container",
                id="warning-text"
            )
            
            # Action buttons
            with Container(id="actions"):
                yield Button("Recreate with Compose", id="recreate", classes="action-button", variant="error")
                yield Button("Simple Recreate", id="simple-recreate", classes="action-button", variant="warning")
                yield Button("Cancel", id="cancel", classes="action-button", variant="default")
    
    @on(Input.Changed, "#path-input")
    def on_path_changed(self, event: Input.Changed) -> None:
        """Validate path and check for compose files."""
        path = event.value.strip()
        status_label = self.query_one("#compose-status", Label)
        select_widget = self.query_one("#compose-file-select", Select)
        
        # Reset selection
        self.selected_compose_file = None
        self.yaml_files = []
        
        if not path:
            status_label.update("")
            select_widget.styles.display = "none"
            return
        
        # Expand user path
        path = os.path.expanduser(path)
        
        if not os.path.exists(path):
            status_label.update("❌ Directory does not exist")
            status_label.styles.color = "red"
            select_widget.styles.display = "none"
            return
        
        if not os.path.isdir(path):
            status_label.update("❌ Path is not a directory")
            status_label.styles.color = "red"
            select_widget.styles.display = "none"
            return
        
        # Check for standard compose files
        compose_files = []
        for filename in ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml']:
            file_path = os.path.join(path, filename)
            if os.path.exists(file_path):
                compose_files.append(filename)
                self.selected_compose_file = filename  # Auto-select the first standard file found
        
        if compose_files:
            status_label.update(f"✓ Found: {', '.join(compose_files)}")
            status_label.styles.color = "green"
            select_widget.styles.display = "none"  # Hide dropdown if standard files found
        else:
            # No standard compose files, look for all YAML files
            try:
                all_files = os.listdir(path)
                self.yaml_files = [f for f in all_files 
                                 if f.endswith(('.yml', '.yaml')) and os.path.isfile(os.path.join(path, f))]
                
                if self.yaml_files:
                    # Show dropdown with YAML files
                    select_widget.styles.display = "block"
                    # Add placeholder as first option
                    select_options = [("Select a file...", "")] + [(f, f) for f in sorted(self.yaml_files)]
                    select_widget.set_options(select_options)
                    
                    status_label.update(f"⚠️ No standard compose file found. {len(self.yaml_files)} YAML file(s) available")
                    status_label.styles.color = "yellow"
                else:
                    status_label.update("⚠️ No docker-compose or YAML files found in directory")
                    status_label.styles.color = "yellow"
                    select_widget.styles.display = "none"
            except Exception as e:
                status_label.update(f"❌ Error reading directory: {e}")
                status_label.styles.color = "red"
                select_widget.styles.display = "none"
    
    @on(Select.Changed, "#compose-file-select")
    def on_file_selected(self, event: Select.Changed) -> None:
        """Handle YAML file selection from dropdown."""
        if event.value and event.value != "":  # Check for non-empty selection
            self.selected_compose_file = event.value
            status_label = self.query_one("#compose-status", Label)
            status_label.update(f"✓ Selected: {event.value}")
            status_label.styles.color = "green"
        else:
            self.selected_compose_file = None
    
    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "recreate":
            path = self.query_one("#path-input", Input).value.strip()
            if path:
                path = os.path.expanduser(path)
                # Use selected file if available, otherwise will auto-detect
                compose_file = self.selected_compose_file
                self.dismiss({
                    'action': 'recreate-compose',
                    'path': path,
                    'service': self.service_name or self.container.name,
                    'compose_file': compose_file
                })
            else:
                # No path - do simple recreate
                self.dismiss({
                    'action': 'recreate-simple'
                })
        elif event.button.id == "simple-recreate":
            # Simple recreate without compose
            self.dismiss({
                'action': 'recreate-simple'
            })
    
    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)


class ColumnSettingsModal(ModalScreen[Optional[List[Dict[str, Any]]]]):
    """Modal dialog to edit column min/max widths."""

    CSS = """
    ColumnSettingsModal { align: center middle; }
    #columns-dialog { 
        width: 70; 
        height: 80%; 
        max-height: 80%; 
        padding: 1 2; 
        background: $surface; 
        border: thick $primary;
        layout: vertical;
    }
    #columns-title { 
        text-align: center; 
        text-style: bold; 
        color: $primary; 
        margin: 0 0 1 0;
        dock: top;
        height: auto;
    }
    .row { layout: horizontal; height: auto; margin: 0 0 1 0; width: 100%; }
    .name { width: 20; }
    .field { width: 10; margin-left: 1; }
    #actions { 
        layout: horizontal; 
        margin-top: 1; 
        width: 100%;
        dock: bottom;
        height: auto;
    }
    .action-button { width: 1fr; margin: 0 1 0 0; }
    #columns-list { height: 1fr; width: 100%; overflow-y: auto; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, columns: List[Dict[str, Any]]):
        super().__init__()
        self._columns = [c.copy() for c in columns]

    def compose(self) -> ComposeResult:
        with Vertical(id="columns-dialog"):
            # Fixed top title
            yield Label("Column Settings", id="columns-title")
            
            # Scrollable middle section
            with ScrollableContainer(id="columns-list"):
                for i, col in enumerate(self._columns):
                    with Horizontal(classes="row"):
                        yield Label(col['name'], classes="name")
                        min_value = str(col.get('min_width', col.get('width', 10)))
                        max_val = col.get('max_width')
                        max_value = "" if max_val is None else str(max_val)
                        yield Label("min:")
                        yield Input(value=min_value, id=f"min_{i}", classes="field")
                        yield Label("max:")
                        yield Input(value=max_value, id=f"max_{i}", placeholder="none", classes="field")
            
            # Fixed bottom buttons
            with Container(id="actions"):
                yield Button("Save", id="save", classes="action-button", variant="primary")
                yield Button("Cancel", id="cancel", classes="action-button")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            result: List[Dict[str, Any]] = []
            for i, col in enumerate(self._columns):
                try:
                    min_input = self.query_one(f"#min_{i}", Input).value.strip()
                    max_input = self.query_one(f"#max_{i}", Input).value.strip()
                    min_w = max(1, int(min_input)) if min_input else max(1, int(col.get('min_width', 1)))
                    max_w = int(max_input) if max_input else None
                    if max_w is not None and max_w < min_w:
                        max_w = min_w
                    result.append({
                        **col,
                        'min_width': min_w,
                        'max_width': max_w,
                    })
                except Exception:
                    result.append(col)
            self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)


def run():
    """Run the Textual Docker TUI."""
    app = DockerTUIApp()
    app.run()


if __name__ == "__main__":
    run()
