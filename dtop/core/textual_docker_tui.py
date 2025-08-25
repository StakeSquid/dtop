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
import time
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from textual import on, work
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, Button, Switch, RichLog
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
    
    #header-bar {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    
    #app-title {
        text-style: bold;
    }
    
    #filter-bar {
        height: 1;
        background: $panel;
        padding: 0 1;
        border-bottom: solid $primary;
        dock: top;
    }

    .search-input {
        width: 20;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
    }

    #search-input {
        width: 20;
        margin: 0 1;
    }

    #filter-input {
        width: 20;
        margin: 0 1;
    }

    .filter-input {
        width: 20;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
    }

    #match-status {
        width: 14;
        color: $text-muted;
    }
    
    #stats-bar {
        display: none;  /* Hide stats bar to save space */
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
    
    .status-indicator {
        margin: 0 0 0 1;
        width: auto;
    }
    
    .compact-switch {
        width: 3;
        height: 1;
        margin: 0 1 0 0;
    }
    
    #connection-status {
        text-align: right;
        width: 20;
        margin: 0 0 0 1;
    }
    
    Footer {
        background: $primary;
        height: 1;
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
    current_match_index = reactive(-1)
    total_matches = reactive(0)
    normalize_logs = reactive(True)
    wrap_lines = reactive(True)
    show_all = reactive(True)
    auto_refresh = reactive(True)
    refresh_interval = reactive(2.0)
    
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
        # Header bar docked at top (like logs)
        with Horizontal(id="filter-bar"):
            yield Input(placeholder="Search", id="search-input", classes="search-input")
            yield Input(placeholder="Filter", id="filter-input", classes="filter-input")
            yield Label("", id="match-status")
            yield Label("All", classes="status-indicator")
            yield Switch(value=self.show_all, id="show-all-switch", classes="compact-switch")
            yield Label("Auto", classes="status-indicator")
            yield Switch(value=self.auto_refresh, id="auto-refresh-switch", classes="compact-switch")
            yield Label("", id="connection-status")

        # Container table fills remaining space
        table = DataTable(id="container-table", cursor_type="row", zebra_stripes=True)
        yield table

        # Footer docked at bottom
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize when app is mounted."""
        await self.connect_docker()
        await self.setup_table()
        await self.start_stats_collection()
        await self.start_refresh_timers()
        
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
    
    async def connect_docker(self) -> None:
        """Connect to Docker daemon."""
        try:
            self.docker_client = docker.from_env()
            status = self.query_one("#connection-status", Label)
            status.update("✅ Connected")
            await self.refresh_containers()
        except docker.errors.DockerException as e:
            status = self.query_one("#connection-status", Label)
            status.update("❌ Disconnected")
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
        if self.auto_refresh:
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
            # Get all containers or just running based on setting
            if self.show_all:
                self.containers = self.docker_client.containers.list(all=True)
            else:
                self.containers = self.docker_client.containers.list(all=False)
            
            # Build container map for quick lookup
            self.container_map = {c.id: c for c in self.containers}
            
            # Apply filter and sort
            await self.apply_filter_and_sort()
            # Recompute search matches when list changes
            self._compute_search_matches()
            
            # Update table display
            await self.update_table()
            
            # Update stats manager with running containers
            running_ids = [c.id for c in self.containers if c.status == 'running']
            self.stats_manager.update_containers(running_ids)
            
        except Exception as e:
            self.log.error(f"Refresh error: {e}")
    
    async def apply_filter_and_sort(self) -> None:
        """Apply filtering and sorting to containers."""
        # Filter
        if self.filter_text:
            filter_lower = self.filter_text.lower()
            self.filtered_containers = [
                c for c in self.containers
                if filter_lower in c.name.lower() or
                   (c.image.tags and filter_lower in c.image.tags[0].lower()) or
                   filter_lower in c.status.lower() or
                   filter_lower in c.short_id.lower()
            ]
        else:
            self.filtered_containers = self.containers.copy()
        
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
    
    def build_row_data(self, container) -> List:
        """Build row data for a container."""
        row_data = []
        stats = self.stats_manager.get_stats(container.id) or {}
        
        for col in self.columns:
            col_name = col['name']
            
            if col_name == 'NAME':
                row_data.append(container.name)
            elif col_name == 'IMAGE':
                image = container.image.tags[0] if container.image.tags else '<none>'
                row_data.append(image)
            elif col_name == 'STATUS':
                status = container.status
                # Add color to status
                if "running" in status.lower():
                    row_data.append(Text(status, style="green"))
                elif "exited" in status.lower() or "stopped" in status.lower():
                    row_data.append(Text(status, style="red"))
                elif "paused" in status.lower():
                    row_data.append(Text(status, style="yellow"))
                else:
                    row_data.append(status)
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
                row_data.append(created)
            elif col_name == 'UPTIME':
                uptime = self.calculate_uptime(container)
                row_data.append(uptime)
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
    
    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row double-click or Enter key."""
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
        asyncio.create_task(self.refresh_containers())

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change for containers list."""
        self.search_text = event.value
        self._compute_search_matches()

    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        """Jump to first match when submitting search."""
        if self._search_matches:
            self._jump_to_current_match()

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
    
    @on(Switch.Changed)
    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle switch toggles."""
        switch_id = event.switch.id
        
        if switch_id == "show-all-switch":
            self.show_all = event.value
            asyncio.create_task(self.refresh_containers())
        elif switch_id == "auto-refresh-switch":
            self.auto_refresh = event.value
            if event.value:
                asyncio.create_task(self.start_refresh_timers())
            else:
                if self.refresh_timer:
                    self.refresh_timer.stop()
        elif switch_id == "normalize-switch":
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
                self.notify("Exec shell requires terminal - use 'docker exec -it' instead", severity="information")
            elif action == "recreate":
                self.notify("Recreate requires docker-compose", severity="information")
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
        """Focus filter input."""
        self.query_one("#filter-input", Input).focus()

    def action_focus_search(self) -> None:
        """Focus search input."""
        self.query_one("#search-input", Input).focus()
    
    def action_clear_filter(self) -> None:
        """Clear filter."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = ""
        self.filter_text = ""
        # Also clear search if present
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.value = ""
        except Exception:
            pass
        self.search_text = ""
        self._compute_search_matches()
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
