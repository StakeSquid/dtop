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
        dock: top;
    }

    .search-input {
        width: 25;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
    }

    .filter-input {
        width: 25;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
    }
    
    #container-title {
        width: 40;
        text-style: bold;
    }
    
    #search-input {
        width: 25;
        margin: 0 1;
    }

    #filter-input {
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
    
    #content-scroll { height: 1fr; }
    
    #inspect-tree { height: 100%; border: none; }
    
    #json-view {
        height: 100%;
        border: none;
        padding: 1;
    }
    
    .hidden {
        display: none;
    }
    
    Footer { height: 1; dock: bottom; }
    """
    
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("/", "focus_search", "Search"),
        Binding("\\", "focus_filter", "Filter"),
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
    filter_term = reactive("")
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
            yield Input(placeholder="Search", id="search-input", classes="search-input")
            yield Input(placeholder="Filter", id="filter-input", classes="filter-input")
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
        # Apply filter to compute the view data if any
        view_data = self.apply_filter(self.inspect_data) if self.filter_term else self.inspect_data
        self.flattened_data = self.flatten_json(view_data)
        
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
        self._path_to_node = {}

        data = self.apply_filter(self.inspect_data) if self.filter_term else self.inspect_data

        def highlight_str(s: str) -> Text:
            if not self.search_term:
                return Text(s)
            pattern = re.compile(re.escape(self.search_term), re.IGNORECASE)
            out = Text()
            idx = 0
            for m in pattern.finditer(s):
                if m.start() > idx:
                    out.append(s[idx:m.start()])
                out.append(s[m.start():m.end()], style="reverse yellow")
                idx = m.end()
            out.append(s[idx:])
            return out

        def highlight_parts(key_text: str, value_text: str, value_style: str) -> Text:
            # Build a Text label with highlighting for both key and value
            label = Text()
            if self.search_term:
                label += highlight_str(f"{key_text}: ")
                # For value, split and highlight
                val_high = highlight_str(value_text)
                val_high.stylize(value_style)
                label += val_high
            else:
                label.append(f"{key_text}: ", style="bold")
                label.append(value_text, style=value_style)
            return label

        def add_node(parent_node, data: Any, key: str = "", parent_path: str = ""):
            """Recursively add nodes to tree."""
            def make_path(base: str, k: str) -> str:
                if base:
                    if k.startswith("["):
                        return f"{base}{k}"
                    return f"{base}.{k}"
                return k

            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (dict, list)):
                        # Add expandable node
                        if isinstance(v, dict):
                            raw_label = f"📁 {k} ({len(v)} items)"
                        else:
                            raw_label = f"📋 {k} [{len(v)} items]"

                        child = parent_node.add(highlight_str(raw_label) if self.search_term else raw_label, expand=False)
                        full_path = make_path(parent_path, k)
                        try:
                            child.data = full_path
                        except Exception:
                            pass
                        self._path_to_node[full_path] = child
                        add_node(child, v, k, full_path)
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

                        lbl = highlight_parts(k, value_str, style)
                        leaf = parent_node.add_leaf(lbl)
                        full_path = make_path(parent_path, k)
                        try:
                            leaf.data = full_path
                        except Exception:
                            pass
                        self._path_to_node[full_path] = leaf

            elif isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, (dict, list)):
                        raw_label = f"[{i}]"
                        child = parent_node.add(highlight_str(raw_label) if self.search_term else raw_label, expand=False)
                        full_path = make_path(parent_path, f"[{i}]")
                        try:
                            child.data = full_path
                        except Exception:
                            pass
                        self._path_to_node[full_path] = child
                        add_node(child, item, str(i), full_path)
                    else:
                        value_str = str(item)
                        if len(value_str) > 100:
                            value_str = value_str[:97] + "..."

                        lbl = highlight_parts(f"[{i}]", value_str, "green")
                        leaf = parent_node.add_leaf(lbl)
                        full_path = make_path(parent_path, f"[{i}]")
                        try:
                            leaf.data = full_path
                        except Exception:
                            pass
                        self._path_to_node[full_path] = leaf
        
        # Build the tree
        tree.root.expand()
        add_node(tree.root, data, parent_path="")
        
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
        
        # Use filtered data if filter is active
        data = self.apply_filter(self.inspect_data) if self.filter_term else self.inspect_data
        # Format JSON with syntax highlighting
        if self.search_term:
            # Highlight search terms in JSON
            json_str = json.dumps(data, indent=2)
            highlighted = self.highlight_json_search(json_str)
            json_widget.update(highlighted)
        else:
            # Use Rich's JSON rendering
            json_widget.update(JSON.from_data(data))
    
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
        
        # Use filtered flattened data if filter active
        view_data = self.flattened_data
        for path, value in view_data:
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
        """Clear filters/search or go back to main screen."""
        if self.search_term or self.filter_term:
            # Clear and refresh
            self.search_term = ""
            self.filter_term = ""
            # Recompute flattened data
            self.flattened_data = self.flatten_json(self.inspect_data)
            if self.view_mode == "tree":
                self.build_tree()
            else:
                self.show_json()
            self.update_match_status()
            self.update_stats()
        else:
            self.app.pop_screen()
    
    def action_focus_search(self) -> None:
        """Focus search input."""
        self.query_one("#search-input", Input).focus()
    
    def action_focus_filter(self) -> None:
        """Focus filter input."""
        self.query_one("#filter-input", Input).focus()
    
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
            try:
                tree = self.query_one("#inspect-tree", Tree)
                node = self._path_to_node.get(path)
                if node is not None:
                    # Expand parents up to root
                    parent = getattr(node, "parent", None)
                    while parent is not None:
                        try:
                            parent.expand()
                        except Exception:
                            pass
                        parent = getattr(parent, "parent", None)
                    # Select and try to scroll into view using node.id for compatibility
                    try:
                        node_id = getattr(node, "id", None)
                        if node_id is not None:
                            try:
                                tree.select_node(node_id)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                            try:
                                tree.scroll_to_node(node_id)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        else:
                            # Fallback: attempt with node reference
                            try:
                                tree.select_node(node)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                            try:
                                tree.scroll_to_node(node)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
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

    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        self.filter_term = event.value
        # Recompute flattened data based on filter
        view_data = self.apply_filter(self.inspect_data) if self.filter_term else self.inspect_data
        self.flattened_data = self.flatten_json(view_data)
        self.find_matches()
        if self.view_mode == "tree":
            self.build_tree()
        else:
            self.show_json()

    def apply_filter(self, data: Any) -> Any:
        """Return a pruned copy of data that keeps only nodes whose key or value contain the filter term.

        - Matching is case-insensitive substring on keys and primitive values.
        - Containers (dict/list) are included if any descendant matches.
        """
        term = (self.filter_term or "").lower()
        if not term:
            return data

        def match_value(v: Any) -> bool:
            if isinstance(v, (dict, list)):
                return False
            try:
                return term in str(v).lower()
            except Exception:
                return False

        def prune(obj: Any, key_name: Optional[str] = None) -> Optional[Any]:
            # If key itself matches, keep entire subtree
            if key_name and term in key_name.lower():
                return obj
            if isinstance(obj, dict):
                out = {}
                for k, v in obj.items():
                    pruned = prune(v, str(k))
                    if pruned is not None:
                        out[k] = pruned
                return out if out else None
            if isinstance(obj, list):
                out_list = []
                for idx, item in enumerate(obj):
                    pruned = prune(item, f"[{idx}]")
                    if pruned is not None:
                        out_list.append(pruned)
                return out_list if out_list else None
            return obj if match_value(obj) else None

        pruned = prune(data)
        # If nothing matched, return empty of same type
        if pruned is None:
            if isinstance(data, dict):
                return {}
            if isinstance(data, list):
                return []
        return pruned
