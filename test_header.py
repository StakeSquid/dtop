#!/usr/bin/env python3
"""Simple header test with toggle on / or \ keys."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Select, Label, Static, DataTable
from textual.reactive import reactive
from textual import on

class TestHeaderApp(App):
    CSS = """
    #main {
        height: 100%;
    }
    
    #header {
        /* Overlay on top of content */
        dock: top;
        layer: above;
        height: 4;      
        width: 100%;
        padding: 0;
        background: $panel;
        border-bottom: solid $primary;
    }
    
    Input {
        width: 20;
        height: 3;    
        padding: 0;   
        margin: 0 0;  
    }
    
    Select {
        width: 15;
        height: 3;    
        margin: 0 0;  
    }
    
    Label {
        height: 3;
        padding: 1;
        margin: 0 0;
    }
    
    #content {
        height: 100%;
        padding: 2;
        background: $surface;
    }
    
    #container-table {
        height: 1fr;
    }
    
    DataTable > .datatable--header {
        background: $primary;
        color: $text;
        text-style: bold;
    }
    """
    
    BINDINGS = [
        Binding("slash", "show_search", "Search", show=True),
        Binding("backslash", "show_filter", "Filter", show=True),
        Binding("escape", "hide_header", "Hide", show=True),
    ]
    
    show_header = reactive(False)
    search_text = ""
    filter_text = ""
    
    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            with Horizontal(id="header"):
                yield Input(placeholder="Search", id="search-input")
                yield Input(placeholder="Filter", id="filter-input")
                yield Select(
                    [("All", "all"), 
                     ("Running", "running"), 
                     ("Exited", "exited")],
                    prompt="Status",
                    value="all"
                )
                yield Label("✓ Connected")
            
            # Add container table instead of static text
            yield DataTable(id="container-table", cursor_type="row", zebra_stripes=True)
    
    def on_mount(self) -> None:
        """Hide header initially and setup table."""
        self.query_one("#header").visible = False
        
        # Setup fake container table
        table = self.query_one("#container-table", DataTable)
        
        # Add columns
        table.add_column("NAME", width=30)
        table.add_column("IMAGE", width=50)
        table.add_column("STATUS", width=15)
        table.add_column("CPU%", width=10)
        table.add_column("MEM%", width=10)
        
        # Add some fake container data
        table.add_row("nginx-proxy", "nginx:alpine", "running", "0.1%", "0.3%")
        table.add_row("postgres-db", "postgres:14", "running", "2.5%", "5.2%")
        table.add_row("redis-cache", "redis:latest", "running", "0.5%", "1.1%")
        table.add_row("app-backend", "myapp:latest", "exited", "0.0%", "0.0%")
        table.add_row("mongodb", "mongo:5.0", "running", "3.2%", "8.5%")
    
    def watch_show_header(self, show: bool) -> None:
        """Toggle header visibility."""
        header = self.query_one("#header")
        header.visible = show
    
    def action_show_search(self) -> None:
        """Show header and focus search."""
        self.show_header = True
        self.query_one("#search-input").focus()
    
    def action_show_filter(self) -> None:
        """Show header and focus filter."""
        self.show_header = True
        self.query_one("#filter-input").focus()
    
    def action_hide_header(self) -> None:
        """Hide the header."""
        self.show_header = False
    
    def on_key(self, event) -> None:
        """Handle key press events."""
        if event.key == "/":
            self.action_show_search()
        elif event.key == "\\":
            self.action_show_filter()
        elif event.key == "escape":
            self.action_hide_header()
    
    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in search/filter inputs."""
        if event.input.id == "search-input":
            self.search_text = event.value
            self.notify(f"Search applied: {self.search_text}", timeout=2)
        elif event.input.id == "filter-input":
            self.filter_text = event.value
            self.notify(f"Filter applied: {self.filter_text}", timeout=2)
        
        # Hide the header after applying
        self.show_header = False
    
    @on(DataTable.RowSelected)
    @on(DataTable.HeaderSelected)
    def on_table_interaction(self, event) -> None:
        """Hide header when clicking on the table."""
        if self.show_header:
            self.show_header = False
    
    def on_click(self, event) -> None:
        """Handle clicks to close header when clicking outside."""
        if self.show_header:
            # Simple check: if click is below the header area (y > 4 since header height is 4)
            if event.y > 4:
                self.show_header = False

if __name__ == "__main__":
    app = TestHeaderApp()
    app.run()