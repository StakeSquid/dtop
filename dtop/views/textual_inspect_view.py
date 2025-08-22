#!/usr/bin/env python3
"""
Docker TUI - Textual Inspect View
-----------
Container inspection viewer using Textual with JSON navigation and search.
"""
import json
import re
from typing import Dict, Any, List, Optional, Tuple

from textual import on, work
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Tree, Input, Label, Static
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.syntax import Syntax
from rich.json import JSON


class InspectViewScreen(Screen):
    """Container inspection viewer with tree navigation and search."""
    
    CSS = """
    #inspect-header {
        height: 2;
        padding: 0 1;
        background: $panel;
        border-bottom: solid $primary;
    }
    
    #container-title {
        width: 40;
        text-style: bold;
    }
    
    #search-input {
        width: 25;
        margin: 0 1;
    }
    
    #match-status {
        width: 15;
        color: $text-muted;
    }
    
    #view-mode {
        width: 10;
        text-align: right;
    }
    
    #inspect-stats {
        text-align: right;
        color: $text-muted;
    }
    
    #content-scroll {
        height: 100%;
    }
    
    #inspect-tree {
        height: 100%;
        border: none;
    }
    
    #json-view {
        height: 100%;
        border: none;
        padding: 1;
    }
    
    .hidden {
        display: none;
    }
    
    Footer {
        height: 1;
    }
    """
    
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("/", "focus_search", "Search"),
        Binding("n", "next_match", "Next"),
        Binding("p", "prev_match", "Previous"),
        Binding("c", "copy_path", "Copy Path"),
        Binding("v", "copy_value", "Copy Value"),
        Binding("e", "expand_all", "Expand All"),
        Binding("shift+e", "collapse_all", "Collapse All"),
        Binding("j", "view_json", "JSON View"),
        Binding("t", "view_tree", "Tree View"),
    ]
    
    # Reactive properties
    search_term = reactive("")
    view_mode = reactive("tree")  # "tree" or "json"
    current_match_index = reactive(0)
    total_matches = reactive(0)
    
    def __init__(self, container):
        super().__init__()
        self.container = container
        self.inspect_data = {}
        self.matches = []
        self.flattened_data = []
        self.current_path = []
    
    def compose(self) -> ComposeResult:
        """Create the inspect view UI."""
        # Compact header
        with Horizontal(id="inspect-header"):
            yield Label(f"🔍 {self.container.name[:30]}", id="container-title")
            yield Input(placeholder="Search...", id="search-input")
            yield Label("", id="match-status")
            yield Label(f"{self.view_mode[:4].upper()}", id="view-mode")
            yield Label("", id="inspect-stats")
        
        # Content area taking most space
        with ScrollableContainer(id="content-scroll"):
            yield Tree("Container Data", id="inspect-tree")
            yield Static("", id="json-view", classes="hidden")
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Load container data when mounted."""
        self.load_inspect_data()
    
    @work(thread=True)
    def load_inspect_data(self) -> None:
        """Load container inspection data."""
        try:
            data = self.container.attrs
            self.app.call_from_thread(self.handle_data_loaded, data, None)
        except Exception as e:
            self.app.call_from_thread(self.handle_data_loaded, None, str(e))
    
    class DataLoaded(Message):
        """Message when inspect data is loaded."""
        def __init__(self, data: Optional[Dict], error: Optional[str] = None):
            super().__init__()
            self.data = data
            self.error = error
    
    def handle_data_loaded(self, data: Optional[Dict], error: Optional[str] = None) -> None:
        """Handle loaded inspect data."""
        if error:
            self.app.notify(f"Error loading data: {error}", severity="error")
            return
        
        self.inspect_data = data
        self.flattened_data = self.flatten_json(self.inspect_data)
        
        if self.view_mode == "tree":
            self.build_tree()
        else:
            self.show_json()
        
        self.update_stats()
    
    def flatten_json(self, obj: Any, parent_key: str = '', sep: str = '.') -> List[Tuple[str, Any]]:
        """Flatten JSON object for searching."""
        items = []
        
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, (dict, list)):
                    items.extend(self.flatten_json(v, new_key, sep))
                else:
                    items.append((new_key, v))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                new_key = f"{parent_key}[{i}]"
                if isinstance(item, (dict, list)):
                    items.extend(self.flatten_json(item, new_key, sep))
                else:
                    items.append((new_key, item))
        else:
            items.append((parent_key, obj))
        
        return items
    
    def build_tree(self) -> None:
        """Build tree view of inspect data."""
        tree = self.query_one("#inspect-tree", Tree)
        tree.clear()
        
        def add_node(parent_node, data: Any, key: str = ""):
            """Recursively add nodes to tree."""
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (dict, list)):
                        # Add expandable node
                        if isinstance(v, dict):
                            label = f"📁 {k} ({len(v)} items)"
                        else:
                            label = f"📋 {k} [{len(v)} items]"
                        
                        child = parent_node.add(label, expand=False)
                        add_node(child, v, k)
                    else:
                        # Add leaf node with value
                        value_str = str(v)
                        if len(value_str) > 100:
                            value_str = value_str[:97] + "..."
                        
                        # Color code based on type
                        if isinstance(v, bool):
                            style = "cyan"
                        elif isinstance(v, (int, float)):
                            style = "magenta"
                        elif v is None:
                            style = "dim"
                        else:
                            style = "green"
                        
                        label = Text.assemble(
                            (f"{k}: ", "bold"),
                            (value_str, style)
                        )
                        parent_node.add_leaf(label)
            
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, (dict, list)):
                        label = f"[{i}]"
                        child = parent_node.add(label, expand=False)
                        add_node(child, item, str(i))
                    else:
                        value_str = str(item)
                        if len(value_str) > 100:
                            value_str = value_str[:97] + "..."
                        
                        label = Text.assemble(
                            (f"[{i}]: ", "bold"),
                            (value_str, "green")
                        )
                        parent_node.add_leaf(label)
        
        # Build the tree
        tree.root.expand()
        add_node(tree.root, self.inspect_data)
        
        # Apply search highlighting if needed
        if self.search_term:
            self.highlight_search_in_tree()
    
    def show_json(self) -> None:
        """Show JSON view of inspect data."""
        json_widget = self.query_one("#json-view", Static)
        tree_widget = self.query_one("#inspect-tree", Tree)
        
        # Hide tree, show JSON
        tree_widget.add_class("hidden")
        json_widget.remove_class("hidden")
        
        # Format JSON with syntax highlighting
        if self.search_term:
            # Highlight search terms in JSON
            json_str = json.dumps(self.inspect_data, indent=2)
            highlighted = self.highlight_json_search(json_str)
            json_widget.update(highlighted)
        else:
            # Use Rich's JSON rendering
            json_widget.update(JSON.from_data(self.inspect_data))
    
    def highlight_json_search(self, json_str: str) -> Text:
        """Highlight search terms in JSON string."""
        text = Text()
        pattern = re.compile(re.escape(self.search_term), re.IGNORECASE)
        
        lines = json_str.split('\n')
        for line in lines:
            matches = list(pattern.finditer(line))
            
            if matches:
                last_end = 0
                for match in matches:
                    # Add text before match
                    text.append(line[last_end:match.start()])
                    # Add highlighted match
                    text.append(line[match.start():match.end()], style="reverse yellow")
                    last_end = match.end()
                # Add remaining text
                text.append(line[last_end:] + '\n')
            else:
                text.append(line + '\n')
        
        return text
    
    def highlight_search_in_tree(self) -> None:
        """Highlight search matches in tree view."""
        # This would require walking the tree and highlighting matches
        # Simplified for now
        self.find_matches()
    
    def find_matches(self) -> None:
        """Find all matches in flattened data."""
        self.matches = []
        
        if not self.search_term:
            return
        
        search_lower = self.search_term.lower()
        
        for path, value in self.flattened_data:
            # Search in both path and value
            if search_lower in path.lower() or search_lower in str(value).lower():
                self.matches.append((path, value))
        
        self.total_matches = len(self.matches)
        self.current_match_index = 0 if self.matches else -1
        
        self.update_match_status()
    
    def update_stats(self) -> None:
        """Update statistics display."""
        stats_label = self.query_one("#inspect-stats", Label)
        
        # Count items
        total_items = len(self.flattened_data)
        stats = f"Items: {total_items}"
        
        # Add type breakdown
        type_counts = {}
        for _, value in self.flattened_data:
            type_name = type(value).__name__
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        if type_counts:
            top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            types_str = ", ".join([f"{t}: {c}" for t, c in top_types])
            stats += f" | Types: {types_str}"
        
        stats_label.update(stats)
    
    def update_match_status(self) -> None:
        """Update match status display."""
        match_label = self.query_one("#match-status", Label)
        
        if self.matches:
            current = self.current_match_index + 1 if self.current_match_index >= 0 else 0
            match_label.update(f"Match {current}/{self.total_matches}")
        elif self.search_term:
            match_label.update("No matches")
        else:
            match_label.update("")
    
    def action_dismiss(self) -> None:
        """Go back to main screen."""
        self.app.pop_screen()
    
    def action_focus_search(self) -> None:
        """Focus search input."""
        self.query_one("#search-input", Input).focus()
    
    def action_next_match(self) -> None:
        """Go to next match."""
        if self.matches and self.current_match_index < len(self.matches) - 1:
            self.current_match_index += 1
            self.jump_to_match()
    
    def action_prev_match(self) -> None:
        """Go to previous match."""
        if self.matches and self.current_match_index > 0:
            self.current_match_index -= 1
            self.jump_to_match()
    
    def jump_to_match(self) -> None:
        """Jump to current match."""
        if not self.matches or self.current_match_index < 0:
            return
        
        path, value = self.matches[self.current_match_index]
        
        # In tree view, expand path to match
        if self.view_mode == "tree":
            # This would require tree navigation logic
            pass
        
        self.update_match_status()
        self.app.notify(f"Match: {path} = {value}", timeout=2)
    
    def action_expand_all(self) -> None:
        """Expand all tree nodes."""
        if self.view_mode == "tree":
            tree = self.query_one("#inspect-tree", Tree)
            tree.root.expand_all()
            self.app.notify("Expanded all nodes")
    
    def action_collapse_all(self) -> None:
        """Collapse all tree nodes."""
        if self.view_mode == "tree":
            tree = self.query_one("#inspect-tree", Tree)
            tree.root.collapse_all()
            self.app.notify("Collapsed all nodes")
    
    def action_view_json(self) -> None:
        """Switch to JSON view."""
        if self.view_mode != "json":
            self.view_mode = "json"
            self.query_one("#view-mode", Label).update(f"Mode: {self.view_mode.upper()}")
            self.show_json()
    
    def action_view_tree(self) -> None:
        """Switch to tree view."""
        if self.view_mode != "tree":
            self.view_mode = "tree"
            self.query_one("#view-mode", Label).update(f"Mode: {self.view_mode.upper()}")
            
            # Hide JSON, show tree
            json_widget = self.query_one("#json-view", Static)
            tree_widget = self.query_one("#inspect-tree", Tree)
            json_widget.add_class("hidden")
            tree_widget.remove_class("hidden")
            
            self.build_tree()
    
    def action_copy_path(self) -> None:
        """Copy current path to clipboard."""
        if self.matches and self.current_match_index >= 0:
            path, _ = self.matches[self.current_match_index]
            # Would need clipboard integration
            self.app.notify(f"Path: {path}")
    
    def action_copy_value(self) -> None:
        """Copy current value to clipboard."""
        if self.matches and self.current_match_index >= 0:
            _, value = self.matches[self.current_match_index]
            # Would need clipboard integration
            self.app.notify(f"Value: {value}")
    
    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change."""
        self.search_term = event.value
        self.find_matches()
        
        if self.view_mode == "tree":
            self.build_tree()  # Rebuild with highlighting
        else:
            self.show_json()  # Refresh with highlighting