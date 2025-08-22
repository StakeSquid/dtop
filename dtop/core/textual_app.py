#!/usr/bin/env python3
"""
Docker TUI - Textual Application
-----------
Main DockerTUI application using Textual framework.
"""
import asyncio
import datetime
import docker
import json
from typing import Optional, List, Dict, Any
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, Button
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual.binding import Binding
from textual.message import Message
from textual.timer import Timer
from rich.text import Text

from ..utils.utils import format_bytes, format_datetime, format_timedelta, get_speed_color
from ..utils.config import load_config, save_config
from .stats import schedule_stats_collection_sync


class ContainerActionModal(ModalScreen):
    """Modal dialog for container actions."""
    
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
    ]
    
    def __init__(self, container, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = container
        self.selected_action = None
    
    def compose(self) -> ComposeResult:
        """Create the action menu UI."""
        is_running = self.container.status == "running"
        is_paused = self.container.status == "paused"
        
        with Vertical(id="action-modal"):
            yield Label(f"Container: {self.container.name}", id="modal-title")
            yield Button("View Logs", id="action-logs", variant="primary")
            yield Button("Inspect", id="action-inspect", variant="primary")
            
            if is_running:
                yield Button("Stop", id="action-stop", variant="warning")
            else:
                yield Button("Start", id="action-start", variant="success")
            
            if is_running and not is_paused:
                yield Button("Pause", id="action-pause", variant="warning")
            elif is_paused:
                yield Button("Unpause", id="action-unpause", variant="success")
            
            if is_running:
                yield Button("Restart", id="action-restart", variant="warning")
                yield Button("Exec Shell", id="action-exec", variant="primary")
            
            yield Button("Recreate", id="action-recreate", variant="danger")
            yield Button("Cancel", id="action-cancel", variant="default")
    
    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id
        if button_id == "action-cancel":
            self.dismiss()
        else:
            self.selected_action = button_id
            self.dismiss(button_id)


class LogViewScreen(Screen):
    """Screen for viewing container logs."""
    
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("n", "toggle_normalize", "Toggle Normalize"),
        Binding("w", "toggle_wrap", "Toggle Wrap"),
        Binding("/", "search", "Search"),
        Binding("f", "filter", "Filter"),
    ]
    
    def __init__(self, container, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = container
        self.normalize_logs = True
        self.wrap_lines = True
        self.search_term = ""
        self.filter_term = ""
    
    def compose(self) -> ComposeResult:
        """Create the log view UI."""
        yield Header()
        with Container(id="log-container"):
            yield Label(f"Logs for {self.container.name}", id="log-title")
            yield ScrollableContainer(
                Static("Loading logs...", id="log-content"),
                id="log-scroll"
            )
        yield Footer()
    
    async def on_mount(self) -> None:
        """Load logs when screen is mounted."""
        await self.load_logs()
    
    @work(thread=True)
    def load_logs(self) -> None:
        """Load container logs in background."""
        try:
            logs = self.container.logs(tail=1000, timestamps=True).decode('utf-8')
            self.post_message(self.LogsLoaded(logs))
        except Exception as e:
            self.post_message(self.LogsLoaded(f"Error loading logs: {e}"))
    
    class LogsLoaded(Message):
        """Message when logs are loaded."""
        def __init__(self, logs: str):
            super().__init__()
            self.logs = logs
    
    def on_logs_loaded(self, message: LogsLoaded) -> None:
        """Handle loaded logs."""
        log_widget = self.query_one("#log-content", Static)
        log_widget.update(message.logs)
    
    def action_toggle_normalize(self) -> None:
        """Toggle log normalization."""
        self.normalize_logs = not self.normalize_logs
        self.notify(f"Normalization: {'ON' if self.normalize_logs else 'OFF'}")
    
    def action_toggle_wrap(self) -> None:
        """Toggle line wrapping."""
        self.wrap_lines = not self.wrap_lines
        self.notify(f"Line wrap: {'ON' if self.wrap_lines else 'OFF'}")
    
    def action_dismiss(self) -> None:
        """Go back to main screen."""
        self.app.pop_screen()


class InspectViewScreen(Screen):
    """Screen for inspecting container details."""
    
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("/", "search", "Search"),
    ]
    
    def __init__(self, container, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = container
    
    def compose(self) -> ComposeResult:
        """Create the inspect view UI."""
        yield Header()
        with Container(id="inspect-container"):
            yield Label(f"Inspect: {self.container.name}", id="inspect-title")
            yield ScrollableContainer(
                Static("Loading...", id="inspect-content"),
                id="inspect-scroll"
            )
        yield Footer()
    
    async def on_mount(self) -> None:
        """Load container details when mounted."""
        await self.load_inspect_data()
    
    @work(thread=True)
    def load_inspect_data(self) -> None:
        """Load container inspection data."""
        try:
            data = self.container.attrs
            formatted = json.dumps(data, indent=2)
            self.post_message(self.InspectLoaded(formatted))
        except Exception as e:
            self.post_message(self.InspectLoaded(f"Error: {e}"))
    
    class InspectLoaded(Message):
        """Message when inspect data is loaded."""
        def __init__(self, data: str):
            super().__init__()
            self.data = data
    
    def on_inspect_loaded(self, message: InspectLoaded) -> None:
        """Handle loaded inspect data."""
        content = self.query_one("#inspect-content", Static)
        content.update(message.data)
    
    def action_dismiss(self) -> None:
        """Go back to main screen."""
        self.app.pop_screen()


class DockerTUIApp(App):
    """Main Docker TUI Application using Textual."""
    
    CSS = """
    #container-table {
        height: 100%;
        border: solid $primary;
    }
    
    #filter-container {
        height: 3;
        background: $surface;
        padding: 0 1;
    }
    
    #stats-bar {
        height: 1;
        background: $surface;
        color: $text;
        text-align: center;
    }
    
    DataTable > .datatable--cursor {
        background: $primary 50%;
    }
    
    DataTable > .datatable--header {
        background: $primary;
        color: $text;
        text-style: bold;
    }
    
    #action-modal {
        width: 40;
        height: auto;
        padding: 1;
        background: $surface;
        border: thick $primary;
    }
    
    #modal-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    
    Button {
        width: 100%;
        margin: 0 0 1 0;
    }
    
    #log-container, #inspect-container {
        height: 100%;
    }
    
    #log-title, #inspect-title {
        text-align: center;
        text-style: bold;
        background: $primary;
        color: $text;
        height: 3;
        padding: 1;
    }
    
    #log-scroll, #inspect-scroll {
        height: 100%;
        border: solid $primary;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "view_logs", "Logs"),
        Binding("i", "inspect", "Inspect"),
        Binding("enter", "show_actions", "Actions"),
        Binding("/", "filter", "Filter"),
        Binding("escape", "clear_filter", "Clear Filter"),
        Binding("n", "toggle_normalize", "Normalize"),
        Binding("w", "toggle_wrap", "Wrap"),
    ]
    
    # Reactive properties
    filter_text = reactive("")
    normalize_logs = reactive(True)
    wrap_lines = reactive(True)
    
    def __init__(self):
        super().__init__()
        self.docker_client = None
        self.containers = []
        self.filtered_containers = []
        self.stats_cache = defaultdict(dict)
        self.stats_lock = asyncio.Lock()
        self.executor = ThreadPoolExecutor(max_workers=30)
        self.columns = load_config()
        self.refresh_timer = None
        self.stats_timer = None
        
    def compose(self) -> ComposeResult:
        """Create the main UI."""
        yield Header()
        
        with Vertical():
            # Filter bar
            with Horizontal(id="filter-container"):
                yield Label("Filter: ")
                yield Input(placeholder="Type to filter containers...", id="filter-input")
                yield Label(f"Normalize: {'ON' if self.normalize_logs else 'OFF'}", id="norm-status")
                yield Label(f"Wrap: {'ON' if self.wrap_lines else 'OFF'}", id="wrap-status")
            
            # Stats bar
            yield Static("Connecting to Docker...", id="stats-bar")
            
            # Container table
            table = DataTable(id="container-table")
            table.cursor_type = "row"
            table.zebra_stripes = True
            yield table
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize when app is mounted."""
        try:
            self.docker_client = docker.from_env()
            await self.setup_table()
            await self.refresh_containers()
            
            # Start refresh timers
            self.refresh_timer = self.set_interval(2.0, self.refresh_containers)
            self.stats_timer = self.set_interval(1.0, self.update_stats)
            
        except docker.errors.DockerException as e:
            self.query_one("#stats-bar", Static).update(f"Error: {e}")
            self.notify("Failed to connect to Docker", severity="error")
    
    async def setup_table(self) -> None:
        """Setup the data table columns."""
        table = self.query_one("#container-table", DataTable)
        
        # Add columns based on configuration
        for col in self.columns:
            table.add_column(col['name'], key=col['name'].lower().replace(' ', '_'))
    
    async def refresh_containers(self) -> None:
        """Refresh container list."""
        if not self.docker_client:
            return
        
        try:
            self.containers = self.docker_client.containers.list(all=True)
            await self.apply_filter()
            await self.update_table()
            
            # Update stats bar
            stats_text = f"Containers: {len(self.filtered_containers)}/{len(self.containers)}"
            if self.filter_text:
                stats_text += f" | Filter: '{self.filter_text}'"
            self.query_one("#stats-bar", Static).update(stats_text)
            
        except Exception as e:
            self.notify(f"Error refreshing: {e}", severity="error")
    
    async def apply_filter(self) -> None:
        """Apply filter to containers."""
        if not self.filter_text:
            self.filtered_containers = self.containers
        else:
            filter_lower = self.filter_text.lower()
            self.filtered_containers = [
                c for c in self.containers
                if filter_lower in c.name.lower() or
                   (c.image.tags and filter_lower in c.image.tags[0].lower())
            ]
    
    async def update_table(self) -> None:
        """Update the data table with container info."""
        table = self.query_one("#container-table", DataTable)
        
        # Clear and rebuild table
        table.clear()
        
        for container in self.filtered_containers:
            row_data = []
            
            # Get stats for this container
            stats = self.stats_cache.get(container.id, {})
            
            for col in self.columns:
                if col['name'] == 'NAME':
                    row_data.append(container.name)
                elif col['name'] == 'IMAGE':
                    row_data.append(container.image.tags[0] if container.image.tags else '<none>')
                elif col['name'] == 'STATUS':
                    # Create colored status text
                    status = container.status
                    if "running" in status.lower():
                        row_data.append(Text(status, style="green"))
                    elif "exited" in status.lower() or "stopped" in status.lower():
                        row_data.append(Text(status, style="red"))
                    elif "paused" in status.lower():
                        row_data.append(Text(status, style="yellow"))
                    else:
                        row_data.append(status)
                elif col['name'] == 'CPU%':
                    cpu_pct = stats.get('cpu', 0)
                    row_data.append(f"{cpu_pct:.1f}")
                elif col['name'] == 'MEM%':
                    mem_pct = stats.get('mem', 0)
                    row_data.append(f"{mem_pct:.1f}")
                elif col['name'] == 'NET I/O':
                    net_in = stats.get('net_in_rate', 0)
                    net_out = stats.get('net_out_rate', 0)
                    text = f"{format_bytes(net_in, '/s')}↓ {format_bytes(net_out, '/s')}↑"
                    row_data.append(text)
                elif col['name'] == 'DISK I/O':
                    disk_read = stats.get('block_read_rate', 0)
                    disk_write = stats.get('block_write_rate', 0)
                    text = f"{format_bytes(disk_read, '/s')}R {format_bytes(disk_write, '/s')}W"
                    row_data.append(text)
                elif col['name'] == 'CREATED AT':
                    created = format_datetime(container.attrs.get('Created', ''))
                    row_data.append(created)
                elif col['name'] == 'UPTIME':
                    if container.attrs.get('State', {}).get('Running'):
                        try:
                            start = datetime.datetime.fromisoformat(
                                container.attrs['State']['StartedAt'][:-1]
                            )
                            uptime = format_timedelta(datetime.datetime.utcnow() - start)
                            row_data.append(uptime)
                        except:
                            row_data.append('-')
                    else:
                        row_data.append('-')
                else:
                    row_data.append('')
            
            table.add_row(*row_data, key=container.id)
    
    @work(thread=True)
    def update_stats(self) -> None:
        """Update container stats in background."""
        if not self.docker_client:
            return
        
        running_containers = [c for c in self.containers if c.status == 'running']
        if running_containers:
            # This would call the existing stats collection logic
            schedule_stats_collection_sync(self, running_containers)
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes."""
        if event.input.id == "filter-input":
            self.filter_text = event.value
            asyncio.create_task(self.refresh_containers())
    
    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row selection."""
        # Store selected container for actions
        if event.row_key and event.row_key.value:
            self.selected_container_id = event.row_key.value
    
    def get_selected_container(self) -> Optional[Any]:
        """Get currently selected container."""
        if hasattr(self, 'selected_container_id'):
            for container in self.filtered_containers:
                if container.id == self.selected_container_id:
                    return container
        
        # Fallback to first container if none selected
        if self.filtered_containers:
            return self.filtered_containers[0]
        return None
    
    def action_show_actions(self) -> None:
        """Show container actions menu."""
        container = self.get_selected_container()
        if container:
            def handle_action(action: str) -> None:
                if action:
                    self.execute_container_action(container, action)
            
            self.push_screen(ContainerActionModal(container), handle_action)
    
    def execute_container_action(self, container, action: str) -> None:
        """Execute a container action."""
        try:
            if action == "action-logs":
                self.push_screen(LogViewScreen(container))
            elif action == "action-inspect":
                self.push_screen(InspectViewScreen(container))
            elif action == "action-stop":
                container.stop()
                self.notify(f"Stopped {container.name}")
            elif action == "action-start":
                container.start()
                self.notify(f"Started {container.name}")
            elif action == "action-restart":
                container.restart()
                self.notify(f"Restarted {container.name}")
            elif action == "action-pause":
                container.pause()
                self.notify(f"Paused {container.name}")
            elif action == "action-unpause":
                container.unpause()
                self.notify(f"Unpaused {container.name}")
            elif action == "action-exec":
                # This would need terminal integration
                self.notify("Exec shell not yet implemented in Textual version")
            elif action == "action-recreate":
                self.notify("Recreate not yet implemented")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
    
    def action_view_logs(self) -> None:
        """View logs for selected container."""
        container = self.get_selected_container()
        if container:
            self.push_screen(LogViewScreen(container))
    
    def action_inspect(self) -> None:
        """Inspect selected container."""
        container = self.get_selected_container()
        if container:
            self.push_screen(InspectViewScreen(container))
    
    def action_filter(self) -> None:
        """Focus filter input."""
        self.query_one("#filter-input", Input).focus()
    
    def action_clear_filter(self) -> None:
        """Clear filter."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = ""
        self.filter_text = ""
    
    def action_toggle_normalize(self) -> None:
        """Toggle log normalization."""
        self.normalize_logs = not self.normalize_logs
        self.query_one("#norm-status", Label).update(
            f"Normalize: {'ON' if self.normalize_logs else 'OFF'}"
        )
        self.notify(f"Normalization: {'ON' if self.normalize_logs else 'OFF'}")
    
    def action_toggle_wrap(self) -> None:
        """Toggle line wrapping."""
        self.wrap_lines = not self.wrap_lines
        self.query_one("#wrap-status", Label).update(
            f"Wrap: {'ON' if self.wrap_lines else 'OFF'}"
        )
        self.notify(f"Line wrap: {'ON' if self.wrap_lines else 'OFF'}")
    
    def action_refresh(self) -> None:
        """Manual refresh."""
        asyncio.create_task(self.refresh_containers())
        self.notify("Refreshed")
    
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