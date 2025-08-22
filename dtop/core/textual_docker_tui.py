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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, Button, Switch
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
from .stats import schedule_stats_collection_sync


@dataclass
class ContainerInfo:
    """Container information wrapper."""
    container: Any
    stats: Dict[str, Any]


class ContainerActionModal(ModalScreen):
    """Modal dialog for container actions."""
    
    CSS = """
    ContainerActionModal {
        align: center middle;
    }
    
    #action-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }
    
    #action-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 0 0 1 0;
    }
    
    .action-button {
        width: 100%;
        margin: 0 0 1 0;
    }
    
    .action-section {
        margin: 1 0;
        border-top: dashed $primary-background;
        padding-top: 1;
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
            
            # Information section
            yield Static(f"Image: {self.container.image.tags[0] if self.container.image.tags else '<none>'}")
            yield Static(f"Status: {self.container.status}")
            yield Static(f"ID: {self.container.short_id}")
            
            # Actions section
            with Vertical(classes="action-section"):
                yield Button("📜 View Logs", id="logs", classes="action-button", variant="primary")
                yield Button("🔍 Inspect", id="inspect", classes="action-button", variant="primary")
            
            # Control section
            with Vertical(classes="action-section"):
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
    }
    
    #filter-input {
        width: 20;
        margin: 0 1;
    }
    
    #stats-bar {
        display: none;  /* Hide stats bar to save space */
    }
    
    #container-table {
        height: 100%;
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
        Binding("\\", "focus_filter", "Filter"),
        Binding("escape", "clear_filter", "Clear"),
        Binding("n", "toggle_normalize", "Normalize"),
        Binding("w", "toggle_wrap", "Wrap"),
        Binding("s", "sort_dialog", "Sort"),
        Binding("?", "help", "Help"),
        Binding("d", "toggle_dark", "Theme"),
    ]
    
    # Reactive properties
    filter_text = reactive("")
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
        self.stats_cache = defaultdict(dict)
        self.stats_lock = asyncio.Lock()
        self.executor = ThreadPoolExecutor(max_workers=30)
        self.columns = load_config()
        self.refresh_timer = None
        self.stats_timer = None
        self.sort_column = None
        self.sort_reverse = False
        self.selected_container_id = None
        self.last_refresh = 0
    
    def compose(self) -> ComposeResult:
        """Create the main UI."""
        with Vertical(id="main-container"):
            # Compact filter bar with controls
            with Horizontal(id="filter-bar"):
                yield Input(placeholder="Filter...", id="filter-input")
                yield Label("All", classes="status-indicator")
                yield Switch(value=self.show_all, id="show-all-switch", classes="compact-switch")
                yield Label("Auto", classes="status-indicator")
                yield Switch(value=self.auto_refresh, id="auto-refresh-switch", classes="compact-switch")
                yield Label("", id="connection-status")
            
            # Container table taking up most space
            table = DataTable(id="container-table", cursor_type="row", zebra_stripes=True)
            yield table
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize when app is mounted."""
        await self.connect_docker()
        await self.setup_table()
        await self.start_refresh_timers()
        
        # Focus the table for keyboard navigation
        table = self.query_one("#container-table", DataTable)
        table.focus()
    
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
                width=col.get('min_width', 20)
            )
    
    async def start_refresh_timers(self) -> None:
        """Start automatic refresh timers."""
        if self.auto_refresh:
            self.refresh_timer = self.set_interval(
                self.refresh_interval,
                self.refresh_containers,
                name="refresh"
            )
            self.stats_timer = self.set_interval(
                1.0,
                self.update_stats,
                name="stats"
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
            
            # Update table display
            await self.update_table()
            
            # Schedule stats collection for running containers
            running = [c for c in self.containers if c.status == 'running']
            if running:
                self.executor.submit(schedule_stats_collection_sync, self, running)
            
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
        stats = self.stats_cache.get(container.id, {})
        
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
        
        # Remember current selection
        current_row_key = None
        current_row_index = 0
        if table.cursor_coordinate:
            try:
                current_row_index = table.cursor_coordinate.row
                current_row_key = table.get_row_at(current_row_index)[0]
            except:
                pass
        
        # Clear and rebuild table
        table.clear()
        
        for container in self.filtered_containers:
            row_data = self.build_row_data(container)
            table.add_row(*row_data, key=container.id)
        
        # Restore selection if possible
        if current_row_key and table.row_count > 0:
            # Try to find the same container
            found = False
            for i, row_key in enumerate(table.rows):
                if row_key.value == current_row_key.value:
                    table.cursor_coordinate = Coordinate(i, 0)
                    found = True
                    break
            
            # If not found, try to maintain position
            if not found and table.row_count > 0:
                new_index = min(current_row_index, table.row_count - 1)
                table.cursor_coordinate = Coordinate(new_index, 0)
        elif table.row_count > 0:
            # Set cursor to first row if no previous selection
            table.cursor_coordinate = Coordinate(0, 0)
    
    def build_row_data(self, container) -> List:
        """Build row data for a container."""
        row_data = []
        stats = self.stats_cache.get(container.id, {})
        
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
    
    @work(thread=True)
    def update_stats(self) -> None:
        """Update container stats in background."""
        if not self.docker_client:
            return
        
        running_containers = [c for c in self.containers if c.status == 'running']
        if running_containers:
            schedule_stats_collection_sync(self, running_containers)
    
    def get_selected_container(self) -> Optional[Any]:
        """Get currently selected container."""
        table = self.query_one("#container-table", DataTable)
        
        # Try to get from cursor coordinate
        if table.cursor_coordinate and table.row_count > 0:
            try:
                row_index = table.cursor_coordinate.row
                if 0 <= row_index < table.row_count:
                    row_key = table.get_row_at(row_index)[0]
                    if row_key and row_key.value:
                        return self.container_map.get(row_key.value)
            except Exception as e:
                self.log.debug(f"Error getting selected container: {e}")
        
        # Fallback to stored selected container ID
        if hasattr(self, 'selected_container_id') and self.selected_container_id:
            return self.container_map.get(self.selected_container_id)
        
        return None
    
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
                if self.stats_timer:
                    self.stats_timer.stop()
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
    
    def action_clear_filter(self) -> None:
        """Clear filter."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = ""
        self.filter_text = ""
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
    
    async def on_unmount(self) -> None:
        """Cleanup when app closes."""
        if self.refresh_timer:
            self.refresh_timer.stop()
        if self.stats_timer:
            self.stats_timer.stop()
        self.executor.shutdown(wait=False)


def run():
    """Run the Textual Docker TUI."""
    app = DockerTUIApp()
    app.run()


if __name__ == "__main__":
    run()