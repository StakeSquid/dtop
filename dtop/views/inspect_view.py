#!/usr/bin/env python3
"""
Docker TUI - Inspect View Module
-----------
Handles container inspect viewing with search and filtering capabilities.
"""
import curses
import json
import re
import time
from ..utils.utils import safe_addstr


def parse_filter_expression(filter_string):
    """Parse filter expression with AND/OR operators and parentheses
    
    Reuses the same logic as log_view for consistency.
    """
    if not filter_string:
        return None
    
    # Tokenize the filter string
    tokens = []
    current_token = ""
    in_quotes = False
    i = 0
    
    while i < len(filter_string):
        char = filter_string[i]
        
        if char == '"':
            if in_quotes:
                if current_token:
                    tokens.append(('TERM', current_token))
                    current_token = ""
                in_quotes = False
            else:
                if current_token:
                    tokens.append(('TERM', current_token))
                    current_token = ""
                in_quotes = True
        elif char == ' ' and not in_quotes:
            if current_token:
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
    
    if current_token:
        if current_token.upper() == 'AND':
            tokens.append(('AND', 'AND'))
        elif current_token.upper() == 'OR':
            tokens.append(('OR', 'OR'))
        else:
            tokens.append(('TERM', current_token))
    
    # If no operators, treat as implicit AND between terms
    if not any(t[0] in ('AND', 'OR') for t in tokens):
        new_tokens = []
        for i, token in enumerate(tokens):
            new_tokens.append(token)
            if (i < len(tokens) - 1 and 
                token[0] in ('TERM', 'RPAREN') and 
                tokens[i+1][0] in ('TERM', 'LPAREN')):
                new_tokens.append(('AND', 'AND'))
        tokens = new_tokens
    
    return tokens


def evaluate_filter(tokens, line, case_sensitive=False):
    """Evaluate parsed filter tokens against a line"""
    if not tokens:
        return True
    
    flags = 0 if case_sensitive else re.IGNORECASE
    
    def evaluate_term(term, line):
        if term.startswith('!') or term.startswith('-'):
            search_term = term[1:]
            if search_term:
                pattern = re.compile(re.escape(search_term), flags)
                return not pattern.search(line)
            return True
        elif term.startswith('+'):
            search_term = term[1:]
        else:
            search_term = term
        
        if search_term:
            pattern = re.compile(re.escape(search_term), flags)
            return bool(pattern.search(line))
        return True
    
    def parse_expression(pos=0):
        if pos >= len(tokens):
            return True, pos
        
        token_type, token_value = tokens[pos]
        
        if token_type == 'TERM':
            result = evaluate_term(token_value, line)
            pos += 1
        elif token_type == 'LPAREN':
            result, pos = parse_expression(pos + 1)
            if pos < len(tokens) and tokens[pos][0] == 'RPAREN':
                pos += 1
        else:
            return True, pos
        
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
                break
            else:
                break
        
        return result, pos
    
    result, _ = parse_expression()
    return result


def flatten_json(obj, parent_key='', sep='.'):
    """Flatten JSON object into a list of key-value pairs for easier searching"""
    items = []
    
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, (dict, list)):
                items.extend(flatten_json(v, new_key, sep))
            else:
                items.append((new_key, str(v)))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            new_key = f"{parent_key}[{i}]"
            if isinstance(item, (dict, list)):
                items.extend(flatten_json(item, new_key, sep))
            else:
                items.append((new_key, str(item)))
    else:
        items.append((parent_key, str(obj)))
    
    return items


def search_json_lines(lines, search_pattern, case_sensitive=False):
    """Search for pattern in JSON lines and return matching line indices"""
    if not search_pattern:
        return []
    
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(search_pattern), flags)
    
    matches = []
    for i, line in enumerate(lines):
        if pattern.search(line):
            matches.append(i)
    
    return matches


def filter_json_lines(lines, json_data, filter_string, case_sensitive=False):
    """Filter JSON lines by creating a filtered JSON structure showing only matching paths"""
    if not filter_string:
        return lines, list(range(len(lines)))
    
    tokens = parse_filter_expression(filter_string)
    if not tokens:
        return lines, list(range(len(lines)))
    
    # Get all key-value pairs from flattened JSON
    flattened = flatten_json(json_data)
    
    # Find matching key-value pairs
    matching_paths = []
    for key, value in flattened:
        # Create a searchable string from key and value
        search_content = f"{key} {value}"
        if evaluate_filter(tokens, search_content, case_sensitive):
            matching_paths.append((key, value))
    
    if not matching_paths:
        return [], []
    
    # Create a clean, readable filtered output
    result_lines = [
        f"# Filtered results for: {filter_string}",
        f"# Showing {len(matching_paths)} matching key-value pairs",
        "",
    ]
    
    # Group by top-level section for better readability
    sections = {}
    for key_path, value in matching_paths:
        top_level = key_path.split('.')[0] if '.' in key_path else key_path
        if top_level not in sections:
            sections[top_level] = []
        sections[top_level].append((key_path, value))
    
    # Output each section
    for section_name, items in sorted(sections.items()):
        result_lines.append(f"## {section_name}")
        result_lines.append("")
        
        for key_path, value in sorted(items):
            # Format value nicely
            if isinstance(value, str) and len(value) > 100:
                # Truncate very long values
                display_value = value[:97] + "..."
            else:
                display_value = str(value)
            
            # Show the full path and value
            result_lines.append(f"  {key_path}: {display_value}")
        
        result_lines.append("")  # Empty line between sections
    
    # Remove trailing empty line
    if result_lines and result_lines[-1] == "":
        result_lines.pop()
    
    line_map = list(range(len(result_lines)))
    return result_lines, line_map


def show_inspect(tui, stdscr, container):
    """Display container inspect information with search and filtering"""
    try:
        # Get terminal size
        h, w = stdscr.getmaxyx()
        
        # Clear and show loading message
        stdscr.clear()
        safe_addstr(stdscr, h//2, (w-30)//2, "Loading inspect data, please wait...", curses.A_BOLD)
        stdscr.refresh()
        
        # Get inspect data
        inspect_data = container.attrs
        
        # Format JSON with nice indentation
        json_text = json.dumps(inspect_data, indent=2, default=str)
        original_lines = json_text.splitlines()
        lines = original_lines.copy()
        
        # Initialize state
        pos = 0
        h_scroll = 0
        max_line_length = max(len(line) for line in lines) if lines else 0
        
        # Search state
        search_string = ""
        search_input = ""
        search_mode = False
        search_matches = []
        current_match = -1
        
        # Filter state
        filter_string = ""
        filter_input = ""
        filter_mode = False
        filtering_active = False
        filtered_lines = []
        filtered_line_map = []
        case_sensitive = False
        
        # Set up non-blocking input
        stdscr.nodelay(True)
        
        # Main viewing loop
        running = True
        needs_redraw = True
        
        while running:
            # Check for terminal resize
            try:
                new_h, new_w = stdscr.getmaxyx()
                if new_h != h or new_w != w:
                    h, w = new_h, new_w
                    needs_redraw = True
            except curses.error:
                pass
            
            # Only redraw if needed
            if needs_redraw:
                # Clear screen
                stdscr.clear()
                
                # Draw header with background color
                stdscr.attron(curses.color_pair(5))
                safe_addstr(stdscr, 0, 0, " " * w)
                header_text = f" Inspect: {container.name} "
                
                # Add search/filter indicators
                if search_string:
                    header_text += f" [SEARCH: {search_string}]"
                if filtering_active:
                    header_text += f" [FILTER: {filter_string}]"
                
                safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                stdscr.attroff(curses.color_pair(5))
                
                # Draw line info
                line_info = f" Line: {pos+1}/{len(lines)} "
                safe_addstr(stdscr, 1, w-len(line_info)-1, line_info)
                
                # Show search matches count
                if search_string and search_matches:
                    match_info = f" {current_match + 1}/{len(search_matches)} matches "
                    safe_addstr(stdscr, 1, 0, match_info, curses.A_BOLD)
                
                # Show filter info
                if filtering_active:
                    # Check if this is a filtered JSON structure by looking for the header
                    if lines and lines[0].startswith("# Filtered results"):
                        # Extract match count from the header
                        match_count = "unknown"
                        for line in lines[:5]:
                            if "matching key-value pairs" in line:
                                parts = line.split()
                                for i, part in enumerate(parts):
                                    if part.isdigit():
                                        match_count = part
                                        break
                                break
                        filter_info = f" Found: {match_count} key-value pairs "
                    else:
                        filter_info = f" Filtered: {len(filtered_lines)}/{len(original_lines)} lines "
                    
                    if not (search_string and search_matches):
                        safe_addstr(stdscr, 1, 0, filter_info, curses.A_BOLD)
                
                # Draw footer with help
                if search_mode:
                    # Search mode footer
                    search_prompt = " Search: "
                    stdscr.attron(curses.color_pair(6))
                    safe_addstr(stdscr, h-1, 0, search_prompt, curses.color_pair(6) | curses.A_BOLD)
                    safe_addstr(stdscr, h-1, len(search_prompt), search_input + " " * (w - len(search_prompt) - len(search_input) - 1), curses.color_pair(6))
                    
                    case_text = "Case: " + ("ON" if case_sensitive else "OFF") + " (Tab)"
                    safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                    stdscr.attroff(curses.color_pair(6))
                    
                    # Show cursor
                    curses.curs_set(1)
                    stdscr.move(h-1, len(search_prompt) + len(search_input))
                elif filter_mode:
                    # Filter mode footer
                    filter_prompt = " Filter: "
                    stdscr.attron(curses.color_pair(6))
                    safe_addstr(stdscr, h-1, 0, filter_prompt, curses.color_pair(6) | curses.A_BOLD)
                    safe_addstr(stdscr, h-1, len(filter_prompt), filter_input + " " * (w - len(filter_prompt) - len(filter_input) - 1), curses.color_pair(6))
                    
                    case_text = "Case: " + ("ON" if case_sensitive else "OFF")
                    safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                    stdscr.attroff(curses.color_pair(6))
                    
                    # Show filter help
                    help_text = "Syntax: term AND/OR term, +include -exclude \"multi word\" | Filters JSON keys/values"
                    if w > len(help_text) + 15:
                        safe_addstr(stdscr, h-2, (w - len(help_text)) // 2, help_text, curses.A_DIM)
                    
                    # Show cursor
                    curses.curs_set(1)
                    stdscr.move(h-1, len(filter_prompt) + len(filter_input))
                else:
                    # Normal mode footer
                    if filtering_active:
                        footer_text = " ↑/↓:Scroll | /:Search | \\:Change Filter | ESC:Clear Filter | n/N:Next/Prev | Q:Back "
                    else:
                        footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | PgUp/Dn:Page | /:Search | \\:Filter | n/N:Next/Prev | ESC/Q:Back "
                    
                    stdscr.attron(curses.color_pair(6))
                    safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                    stdscr.attroff(curses.color_pair(6))
                    
                    curses.curs_set(0)
                
                # Display content
                content_start = 2
                content_height = h - content_start - 1
                
                # Show empty state if filtering with no results
                if filtering_active and not lines:
                    empty_msg1 = "No content matching filter:"
                    empty_msg2 = filter_string
                    empty_msg3 = "(Press \\ to change filter or ESC to clear)"
                    
                    center_y = h // 2
                    safe_addstr(stdscr, center_y - 1, (w - len(empty_msg1)) // 2, empty_msg1, curses.A_BOLD)
                    safe_addstr(stdscr, center_y, (w - len(empty_msg2)) // 2, empty_msg2, curses.A_DIM)
                    safe_addstr(stdscr, center_y + 1, (w - len(empty_msg3)) // 2, empty_msg3, curses.A_DIM)
                else:
                    # Display JSON lines
                    for i in range(content_height):
                        line_idx = pos + i
                        if line_idx < len(lines):
                            line = lines[line_idx]
                            
                            # Handle horizontal scrolling
                            if h_scroll > 0:
                                line = line[h_scroll:] if h_scroll < len(line) else ""
                            
                            # Truncate line if too long
                            if len(line) > w - 2:
                                line = line[:w - 3] + "…"
                            
                            # Highlight search matches
                            if search_string and line_idx in search_matches:
                                # Find the match position in the line
                                flags = 0 if case_sensitive else re.IGNORECASE
                                pattern = re.compile(re.escape(search_string), flags)
                                
                                y = content_start + i
                                x = 0
                                
                                # Draw line with highlights
                                for match in pattern.finditer(lines[line_idx]):
                                    start, end = match.span()
                                    # Adjust for horizontal scroll
                                    if h_scroll > 0:
                                        start -= h_scroll
                                        end -= h_scroll
                                    
                                    # Draw text before match
                                    if start > x:
                                        safe_addstr(stdscr, y, x, line[x:start])
                                    
                                    # Draw match with highlight
                                    if start >= 0 and start < len(line):
                                        match_text = line[start:min(end, len(line))]
                                        if line_idx == search_matches[current_match]:
                                            # Current match - bright highlight
                                            safe_addstr(stdscr, y, max(0, start), match_text, curses.color_pair(10))
                                        else:
                                            # Other matches - dimmer highlight
                                            safe_addstr(stdscr, y, max(0, start), match_text, curses.color_pair(9))
                                        x = min(end, len(line))
                                
                                # Draw rest of line
                                if x < len(line):
                                    safe_addstr(stdscr, y, x, line[x:])
                            else:
                                # Normal line
                                safe_addstr(stdscr, content_start + i, 0, line)
                
                # Draw scrollbar
                if len(lines) > content_height:
                    scrollbar_pos = content_start
                    if len(lines) > content_height:
                        scrollbar_pos = content_start + int((pos / (len(lines) - content_height)) * (content_height - 1))
                    
                    for i in range(content_start, h-1):
                        if i == scrollbar_pos:
                            safe_addstr(stdscr, i, w-1, "█")
                        else:
                            safe_addstr(stdscr, i, w-1, "│")
                
                stdscr.refresh()
                needs_redraw = False
            
            # Handle input
            key = stdscr.getch()
            
            # Only process input if a key was pressed
            if key == -1:  # No input
                time.sleep(0.05)  # Longer sleep to reduce CPU usage
                continue
            
            if search_mode:
                # Handle search input
                if key == 27:  # ESC
                    search_mode = False
                    curses.curs_set(0)
                    needs_redraw = True
                elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
                    if search_input:
                        search_input = search_input[:-1]
                        # For backspace, just update the input line instead of full redraw
                        search_prompt = " Search: "
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, search_prompt + search_input + " " * (w - len(search_prompt) - len(search_input) - 1), curses.color_pair(6))
                        case_text = "Case: " + ("ON" if case_sensitive else "OFF") + " (Tab)"
                        safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(6))
                        stdscr.move(h-1, len(search_prompt) + len(search_input))
                        stdscr.refresh()
                elif key == 10:  # Enter
                    if search_input:
                        search_string = search_input
                        # Perform search
                        search_matches = search_json_lines(lines, search_string, case_sensitive)
                        if search_matches:
                            # Find closest match to current position
                            current_match = 0
                            for i, match_pos in enumerate(search_matches):
                                if match_pos >= pos:
                                    current_match = i
                                    break
                            # Jump to first match
                            pos = search_matches[current_match]
                    search_mode = False
                    curses.curs_set(0)
                    needs_redraw = True
                elif key == 9:  # Tab - toggle case sensitivity
                    case_sensitive = not case_sensitive
                    needs_redraw = True
                elif key < 256 and key >= 32:  # Printable character
                    search_input += chr(key)
                    # For typing, just update the input line instead of full redraw
                    search_prompt = " Search: "
                    stdscr.attron(curses.color_pair(6))
                    safe_addstr(stdscr, h-1, 0, search_prompt + search_input + " " * (w - len(search_prompt) - len(search_input) - 1), curses.color_pair(6))
                    case_text = "Case: " + ("ON" if case_sensitive else "OFF") + " (Tab)"
                    safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                    stdscr.attroff(curses.color_pair(6))
                    stdscr.move(h-1, len(search_prompt) + len(search_input))
                    stdscr.refresh()
            
            elif filter_mode:
                # Handle filter input
                if key == 27:  # ESC
                    filter_mode = False
                    curses.curs_set(0)
                    needs_redraw = True
                elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
                    if filter_input:
                        filter_input = filter_input[:-1]
                        # For backspace, just update the input line instead of full redraw
                        filter_prompt = " Filter: "
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, filter_prompt + filter_input + " " * (w - len(filter_prompt) - len(filter_input) - 1), curses.color_pair(6))
                        case_text = "Case: " + ("ON" if case_sensitive else "OFF")
                        safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(6))
                        stdscr.move(h-1, len(filter_prompt) + len(filter_input))
                        stdscr.refresh()
                elif key == 10:  # Enter
                    if filter_input:
                        filter_string = filter_input
                        # Apply filter
                        filtered_lines, filtered_line_map = filter_json_lines(
                            original_lines, inspect_data, filter_string, case_sensitive
                        )
                        
                        filtering_active = True
                        lines = filtered_lines
                        
                        # Reset position and search
                        pos = 0
                        search_matches = []
                        current_match = -1
                        
                        # Update max line length
                        max_line_length = max(len(line) for line in lines) if lines else 0
                    else:
                        # Clear filter
                        filtering_active = False
                        filter_string = ""
                        lines = original_lines
                        pos = 0
                        max_line_length = max(len(line) for line in lines) if lines else 0
                    
                    filter_mode = False
                    curses.curs_set(0)
                    needs_redraw = True
                elif key == 9:  # Tab - toggle case sensitivity
                    case_sensitive = not case_sensitive
                    needs_redraw = True
                elif key < 256 and key >= 32:  # Printable character
                    filter_input += chr(key)
                    # For typing, just update the input line instead of full redraw
                    filter_prompt = " Filter: "
                    stdscr.attron(curses.color_pair(6))
                    safe_addstr(stdscr, h-1, 0, filter_prompt + filter_input + " " * (w - len(filter_prompt) - len(filter_input) - 1), curses.color_pair(6))
                    case_text = "Case: " + ("ON" if case_sensitive else "OFF")
                    safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                    stdscr.attroff(curses.color_pair(6))
                    stdscr.move(h-1, len(filter_prompt) + len(filter_input))
                    stdscr.refresh()
            
            else:
                # Normal mode input
                if key == curses.KEY_DOWN:
                    if pos < len(lines) - 1:
                        pos += 1
                        needs_redraw = True
                elif key == curses.KEY_UP:
                    if pos > 0:
                        pos -= 1
                        needs_redraw = True
                elif key == curses.KEY_NPAGE:  # Page Down
                    pos = min(len(lines) - 1, pos + content_height)
                    needs_redraw = True
                elif key == curses.KEY_PPAGE:  # Page Up
                    pos = max(0, pos - content_height)
                    needs_redraw = True
                elif key == curses.KEY_RIGHT:  # Right arrow
                    h_scroll = min(h_scroll + 10, max(0, max_line_length - (w - 5)))
                    needs_redraw = True
                elif key == curses.KEY_LEFT:  # Left arrow
                    h_scroll = max(0, h_scroll - 10)
                    needs_redraw = True
                elif key == curses.KEY_HOME:  # Home
                    pos = 0
                    h_scroll = 0
                    needs_redraw = True
                elif key == curses.KEY_END:  # End
                    pos = max(0, len(lines) - content_height)
                    needs_redraw = True
                elif key == ord('/'):  # Start search
                    search_mode = True
                    search_input = search_string
                    needs_redraw = True
                elif key == ord('\\'):  # Start filter
                    filter_mode = True
                    filter_input = filter_string
                    needs_redraw = True
                elif key == ord('n'):  # Next search match
                    if search_matches and current_match < len(search_matches) - 1:
                        current_match += 1
                        pos = search_matches[current_match]
                        needs_redraw = True
                elif key == ord('N'):  # Previous search match
                    if search_matches and current_match > 0:
                        current_match -= 1
                        pos = search_matches[current_match]
                        needs_redraw = True
                elif key == curses.KEY_MOUSE:
                    try:
                        _, mx, my, _, button_state = curses.getmouse()
                        # Scroll with mouse wheel
                        if button_state & curses.BUTTON4_PRESSED:  # Wheel up
                            pos = max(0, pos - 3)
                            needs_redraw = True
                        elif button_state & curses.BUTTON5_PRESSED:  # Wheel down
                            pos = min(len(lines) - 1, pos + 3)
                            needs_redraw = True
                    except curses.error:
                        pass
                elif key == 27:  # ESC
                    if filtering_active:
                        # Clear filter
                        filtering_active = False
                        filter_string = ""
                        lines = original_lines
                        pos = 0
                        search_matches = []
                        current_match = -1
                        max_line_length = max(len(line) for line in lines) if lines else 0
                        needs_redraw = True
                    else:
                        running = False
                elif key in (ord('q'), ord('Q')):
                    running = False
    
    except Exception as e:
        # Show error and wait for key
        stdscr.clear()
        safe_addstr(stdscr, h//2, (w-len(str(e))-10)//2, f"Error: {e}", curses.A_BOLD)
        safe_addstr(stdscr, h//2+1, (w-25)//2, "Press any key to continue...", curses.A_DIM)
        stdscr.refresh()
        stdscr.getch()
    
    finally:
        # Restore screen state
        stdscr.clear()
        stdscr.nodelay(True)
        stdscr.refresh()
