#!/usr/bin/env python3
"""
Docker TUI - Log View Module
-----------
Handles container log viewing and search/filter functionality.
"""
import curses
import re
import time
import subprocess
import os
from utils import safe_addstr

def get_filter_indicator(filter_string):
    """Generate a concise filter indicator for the header"""
    if not filter_string:
        return ""
    
    # Parse filters the same way as filter_logs does
    filters = []
    current_filter = ""
    in_quotes = False
    i = 0
    
    while i < len(filter_string):
        char = filter_string[i]
        
        if char == '"':
            in_quotes = not in_quotes
            i += 1
        elif char == ' ' and not in_quotes:
            if current_filter:
                filters.append(current_filter)
                current_filter = ""
            i += 1
        else:
            current_filter += char
            i += 1
    
    if current_filter:
        filters.append(current_filter)
    
    # Count inclusion and exclusion filters
    inclusions = []
    exclusions = []
    
    for f in filters:
        if f.startswith('!') or f.startswith('-'):
            exclusions.append(f[1:])
        elif f.startswith('+'):
            inclusions.append(f[1:])
        elif f:
            inclusions.append(f)
    
    parts = []
    if inclusions:
        inc_str = ','.join(inclusions[:2])
        if len(inclusions) > 2:
            inc_str += "..."
        parts.append(f"+{inc_str}")
    if exclusions:
        exc_str = ','.join(exclusions[:2])
        if len(exclusions) > 2:
            exc_str += "..."
        parts.append(f"-{exc_str}")
    
    return f" [FILTER: {' '.join(parts)}]"

def normalize_container_logs(normalize_logs, normalize_script, log_lines):
    """Pipe logs through normalize_logs.py script"""
    if not normalize_logs or not os.path.isfile(normalize_script):
        return log_lines
    
    try:
        # Join log lines with newlines to create input
        log_text = "\n".join(log_lines)
        
        # Make sure normalize_logs.py is executable
        if not os.access(normalize_script, os.X_OK):
            os.chmod(normalize_script, 0o755)
        
        # Run normalize_logs.py as a subprocess
        process = subprocess.Popen(
            [normalize_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Send logs to stdin and get normalized output
        stdout, stderr = process.communicate(input=log_text, timeout=3)
        
        # Check if there was an error
        if process.returncode != 0 or stderr:
            error_logs = log_lines.copy()
            error_logs.insert(0, f"Log normalization error: {stderr.strip()}")
            error_logs.insert(1, "Showing raw logs instead.")
            return error_logs
        
        # Split output into lines and return
        normalized_logs = stdout.splitlines()
        return normalized_logs
        
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
        # Handle subprocess errors
        error_logs = log_lines.copy()
        error_logs.insert(0, f"Log normalization error: {str(e)}")
        error_logs.insert(1, "Showing raw logs instead.")
        return error_logs

def rebuild_log_pad(logs, width, height, wrap_log_lines):
    """Rebuild the log pad with current wrapping and normalization settings"""
    # Handle empty logs case
    if not logs:
        # Create a minimal pad for empty state
        new_pad = curses.newpad(10, max(width-2, 10))
        return {
            'pad': new_pad,
            'line_positions': [],
            'actual_lines': 0
        }
    
    # Estimate pad size needed
    pad_height = max(len(logs)+100, 500)
    
    # If wrapping is enabled, we might need more space
    if wrap_log_lines:
        # Roughly estimate how many extra lines we might need for wrapping
        extra_lines = sum(max(1, len(line) // (width-3)) for line in logs)
        pad_height += extra_lines
    
    # Create new pad with appropriate dimensions
    pad_width = max(width-2, 10)
    if not wrap_log_lines:
        # For non-wrapped mode, make pad wider to accommodate long lines
        pad_width = max(pad_width, max((len(line) for line in logs), default=width) + 10)
        
    new_pad = curses.newpad(pad_height, pad_width)
    
    # Fill pad with logs - handle wrapping
    line_positions = []  # Track the starting position of each logical line
    current_line = 0
    
    for i, line in enumerate(logs):
        line_positions.append(current_line)
        if wrap_log_lines:
            # Split the line into wrapped segments
            remaining = line
            while remaining:
                segment = remaining[:width-3]
                try:
                    new_pad.addstr(current_line, 0, segment)
                except curses.error:
                    pass
                current_line += 1
                remaining = remaining[width-3:]
        else:
            # No wrapping - just add the whole line
            try:
                new_pad.addstr(current_line, 0, line)
            except curses.error:
                pass
            current_line += 1
    
    # Return pad and metadata
    return {
        'pad': new_pad,
        'line_positions': line_positions,
        'actual_lines': current_line
    }

def search_and_highlight(pad, logs, search_pattern, line_positions, w, case_sensitive=False, start_pos=0):
    """Find search matches and update the pad with highlights"""
    # Initialize search results
    search_matches = []
    
    if not search_pattern:
        return {'matches': search_matches, 'current_match': -1}
        
    # Find all matches in all lines
    flags = 0 if case_sensitive else re.IGNORECASE
    
    # Process each log line
    for i, line in enumerate(logs):
        # Find all matches in this line
        for match in re.finditer(re.escape(search_pattern), line, flags):
            # Get match position
            start, end = match.span()
            
            # Store the match with its logical line index and character position
            search_matches.append((i, start, end - start))
    
    # Sort matches by logical line index then by position
    search_matches.sort()
    
    # Find closest match to current position
    current_match = -1
    if search_matches:
        # Find the closest match to the current position by binary search
        closest_idx = 0
        if start_pos > 0:
            # Convert start_pos to logical line
            logical_line = 0
            for i, pos in enumerate(line_positions):
                if pos > start_pos:
                    logical_line = i - 1
                    break
                if i == len(line_positions) - 1:
                    logical_line = i
            
            # Find first match on or after logical_line
            closest_idx = 0
            for i, (match_line, _, _) in enumerate(search_matches):
                if match_line >= logical_line:
                    closest_idx = i
                    break
        
        # Clamp to valid range
        current_match = max(0, min(closest_idx, len(search_matches) - 1))
    
    # Return the search results
    return {
        'matches': search_matches,
        'current_match': current_match
    }

def highlight_search_matches(pad, line_positions, wrap_log_lines, w, search_matches, current_match):
    """Draw search match highlights on the pad"""
    if not search_matches:
        return
    
    # First pass: highlight all matches
    for i, (line_idx, start_pos, length) in enumerate(search_matches):
        # If in wrapped mode, find the actual pad line and position
        if wrap_log_lines:
            pad_line = line_positions[line_idx]
            wrap_offset = 0
            char_pos = 0
            
            # Calculate the actual position in the pad
            while char_pos + (w-3) < start_pos:
                pad_line += 1
                char_pos += (w-3)
            
            # Calculate the starting position on this line
            start_col = start_pos - char_pos
            
            # Handle multiple wraps if the match spans multiple wrapped lines
            remaining = length
            while remaining > 0:
                # How much can fit on this line
                segment_length = min(remaining, (w-3) - start_col)
                
                # Draw this segment with the appropriate color
                attr = curses.color_pair(10) if i == current_match else curses.color_pair(9)
                try:
                    for x in range(segment_length):
                        # Change attribute for each character
                        pad.chgat(pad_line, start_col + x, 1, attr)
                except curses.error:
                    pass
                
                # Move to next line if needed
                remaining -= segment_length
                if remaining > 0:
                    pad_line += 1
                    start_col = 0
        else:
            # Non-wrapped mode: simply highlight at the absolute position
            attr = curses.color_pair(10) if i == current_match else curses.color_pair(9)
            try:
                pad_line = line_positions[line_idx]
                for x in range(length):
                    pad.chgat(pad_line, start_pos + x, 1, attr)
            except curses.error:
                pass

def next_search_match(search_matches, current_match, line_positions, wrap_log_lines, w):
    """Move to the next search match and return position to scroll to"""
    if not search_matches:
        return None
        
    # Move to next match
    new_match = (current_match + 1) % len(search_matches)
    
    # Get the match details
    line_idx, char_pos, _ = search_matches[new_match]
    
    # Convert to pad position
    if wrap_log_lines:
        # Calculate wrapped line position
        pad_line = line_positions[line_idx]
        wrap_width = w - 3
        while char_pos >= wrap_width:
            pad_line += 1
            char_pos -= wrap_width
    else:
        # Just use the direct line position
        pad_line = line_positions[line_idx]
        
    # Return the match position and index
    return {
        'position': pad_line,
        'match_index': new_match
    }

def prev_search_match(search_matches, current_match, line_positions, wrap_log_lines, w):
    """Move to the previous search match and return position to scroll to"""
    if not search_matches:
        return None
        
    # Move to previous match
    new_match = (current_match - 1) % len(search_matches)
    
    # Get the match details
    line_idx, char_pos, _ = search_matches[new_match]
    
    # Convert to pad position
    if wrap_log_lines:
        # Calculate wrapped line position
        pad_line = line_positions[line_idx]
        wrap_width = w - 3
        while char_pos >= wrap_width:
            pad_line += 1
            char_pos -= wrap_width
    else:
        # Just use the direct line position
        pad_line = line_positions[line_idx]
        
    # Return the match position and index
    return {
        'position': pad_line,
        'match_index': new_match
    }

def filter_logs(logs, filter_string, case_sensitive=False):
    """Filter logs with support for inclusion and exclusion filters
    
    Filter syntax:
    - "text" or "+text" : include lines containing "text"
    - "!text" or "-text" : exclude lines containing "text"
    - Multiple filters separated by spaces, e.g. "include -exclude +another"
    - Use quotes for multi-word filters: "error -\"debug info\""
    """
    if not filter_string:
        return logs, []  # Return original logs if no filter
    
    # Parse filter string into individual filters
    filters = []
    current_filter = ""
    in_quotes = False
    i = 0
    
    while i < len(filter_string):
        char = filter_string[i]
        
        if char == '"':
            in_quotes = not in_quotes
            i += 1
        elif char == ' ' and not in_quotes:
            if current_filter:
                filters.append(current_filter)
                current_filter = ""
            i += 1
        else:
            current_filter += char
            i += 1
    
    # Add the last filter if any
    if current_filter:
        filters.append(current_filter)
    
    if not filters:
        return logs, []
    
    filtered_logs = []
    line_map = []  # Maps filtered line index to original line index
    flags = 0 if case_sensitive else re.IGNORECASE
    
    # Process each log line
    for i, line in enumerate(logs):
        include_line = True
        has_inclusion_filter = False
        passes_inclusion = False
        
        # Check if we have any inclusion filters
        for filter_term in filters:
            if filter_term and not (filter_term.startswith('!') or filter_term.startswith('-')):
                has_inclusion_filter = True
                break
        
        # Apply each filter
        for filter_term in filters:
            if not filter_term:
                continue
                
            # Determine filter type
            if filter_term.startswith('!') or filter_term.startswith('-'):
                # Exclusion filter
                search_term = filter_term[1:]
                if search_term:
                    pattern = re.compile(re.escape(search_term), flags)
                    if pattern.search(line):
                        include_line = False
                        break
            else:
                # Inclusion filter (with optional + prefix)
                search_term = filter_term[1:] if filter_term.startswith('+') else filter_term
                if search_term:
                    pattern = re.compile(re.escape(search_term), flags)
                    if pattern.search(line):
                        passes_inclusion = True
        
        # If we have inclusion filters, the line must pass at least one
        if has_inclusion_filter and not passes_inclusion:
            include_line = False
        
        if include_line:
            filtered_logs.append(line)
            line_map.append(i)
    
    return filtered_logs, line_map
    
def show_logs(tui, stdscr, container):
    """Display container logs with follow mode and search"""
    try:
        # Get terminal size
        h, w = stdscr.getmaxyx()
        
        # Temporarily stop refresh
        stdscr.nodelay(False)
        curses.curs_set(0)
        
        # Clear and show loading message
        stdscr.clear()
        safe_addstr(stdscr, h//2, (w-25)//2, "Loading logs, please wait...", curses.A_BOLD)
        stdscr.refresh()
        
        # Fetch initial logs
        raw_logs = container.logs(tail=500).decode(errors='ignore').splitlines()
        
        # Process logs through normalize_logs.py
        logs = normalize_container_logs(tui.normalize_logs, tui.normalize_logs_script, raw_logs) if tui.normalize_logs else raw_logs
        
        # Set up follow mode
        follow_mode = True
        last_log_time = time.time()
        log_update_interval = 0.5  # seconds (faster updates)
        
        # Track last log line to avoid duplicates
        last_log_line = logs[-1] if logs else ""
        last_log_count = len(logs)
        
        # Create a pad for scrolling and get the metadata
        pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
        pad = pad_info['pad']
        line_positions = pad_info['line_positions']
        actual_lines_count = pad_info['actual_lines']
        
        # Start at the end of logs if in follow mode
        pos = max(0, actual_lines_count - (h-4)) if follow_mode else 0
        
        # Horizontal scroll
        h_scroll = 0
        max_line_length = max([len(line) for line in logs], default=0)
        
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
        # Initial state flags
        filtering_active = False
        filtered_logs = []
        filtered_line_map = []  # Maps filtered index to original index
        original_logs = logs.copy()  # Keep a copy of original logs
        case_sensitive = False
        
        # Flags to control loop flow
        skip_normal_input = False
        just_processed_search = False
        just_processed_filter = False
        
        # Initial draw of screen
        stdscr.refresh()
        pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
        
        # Reduce refresh rate to avoid flashing
        draw_interval = 0.3  # seconds between screen refreshes
        
        # Main log viewing loop
        running = True
        last_display_time = 0
        all_raw_logs = raw_logs.copy()  # Keep track of ALL raw logs for toggling
        
        # Track logical lines for accurate navigation
        last_logical_lines_count = len(logs)
        
        # Track UI states to avoid unnecessary redraws
        last_follow_mode = follow_mode
        last_normalize_logs = tui.normalize_logs
        last_wrap_lines = tui.wrap_log_lines
        
        # Draw the static parts of the UI once at the beginning
        stdscr.clear()
        
        # Draw header
        stdscr.attron(curses.color_pair(5))
        safe_addstr(stdscr, 0, 0, " " * w)
        normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
        wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
        search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
        filter_indicator = get_filter_indicator(filter_string) if filtering_active else ""
        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
        stdscr.attroff(curses.color_pair(5))
        
        # Draw footer with help
        if filtering_active:
            if tui.wrap_log_lines:
                footer_text = " ↑/↓:Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
            else:
                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
        elif tui.wrap_log_lines:
            footer_text = " ↑/↓:Scroll | PgUp/Dn:Page | F:Toggle Follow | N:Normalize | W:Wrap | /:Search | \\:Filter | ESC:Back "
        else:
            footer_text = " ↑/↓:Scroll | ←/→:Scroll H | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | /:Search | \\:Filter | ESC:Back "
        
        stdscr.attron(curses.color_pair(6))
        safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
        stdscr.attroff(curses.color_pair(6))
        
        while running:
            # Clear the skip_normal_input flag at the start of each iteration
            if just_processed_search or just_processed_filter:
                skip_normal_input = True
                just_processed_search = False
                just_processed_filter = False
            else:
                skip_normal_input = False
            
            current_time = time.time()
            
            # Update logs in follow mode
            if follow_mode and current_time - last_log_time >= log_update_interval:
                try:
                    # Use tail to get only new logs since we last checked
                    # This approach avoids duplicates by only getting logs we haven't seen
                    raw_new_logs = container.logs(
                        tail=50,  # Reduced from 100 to minimize overlap
                        stream=False
                    ).decode(errors='ignore').splitlines()
                    
                    if raw_new_logs:
                        # Find where the new logs start (avoid duplicates)
                        new_start_idx = 0
                        if last_log_count > 0 and len(raw_new_logs) > last_log_count:
                            # We have more logs than before, find the overlap
                            for i in range(len(raw_new_logs) - last_log_count):
                                if raw_new_logs[i:i+last_log_count] == all_raw_logs[-last_log_count:]:
                                    new_start_idx = i + last_log_count
                                    break
                        elif last_log_line and raw_new_logs:
                            # Find where the last log line appears in the new logs
                            try:
                                last_idx = raw_new_logs.index(last_log_line)
                                new_start_idx = last_idx + 1
                            except ValueError:
                                # Last line not found, these must all be new
                                new_start_idx = 0
                        
                        # Extract only truly new logs
                        truly_new_logs = raw_new_logs[new_start_idx:] if new_start_idx < len(raw_new_logs) else []
                        
                        if truly_new_logs:
                            # Update tracking variables
                            last_log_line = raw_new_logs[-1]
                            last_log_count = min(50, len(raw_new_logs))  # Track up to 50 lines
                            
                            # Update raw_logs with new content for toggling
                            all_raw_logs.extend(truly_new_logs)
                            
                            # Process new logs through normalize_logs.py if normalization is on
                            new_logs = normalize_container_logs(tui.normalize_logs, tui.normalize_logs_script, truly_new_logs) if tui.normalize_logs else truly_new_logs
                            
                            # Add to original logs
                            original_logs.extend(new_logs)
                            
                            # If filtering is active, apply filter to new logs
                            if filtering_active:
                                # Apply filter to all logs (original + new)
                                filtered_logs, filtered_line_map = filter_logs(original_logs, filter_string, case_sensitive)
                                logs = filtered_logs
                                
                                # Rebuild pad with filtered logs
                                pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                                pad = pad_info['pad']
                                line_positions = pad_info['line_positions']
                                actual_lines_count = pad_info['actual_lines']
                            else:
                                # Add to current logs
                                logs.extend(new_logs)
                                
                                # Check if we need to resize the pad
                                new_lines_estimate = len(new_logs)
                                if tui.wrap_log_lines:
                                    # Estimate additional space needed for wrapping
                                    new_lines_estimate += sum(max(1, len(line) // (w-3)) for line in new_logs)
                                    
                                if actual_lines_count + new_lines_estimate >= pad.getmaxyx()[0]:
                                    # Need a new pad - rebuild with all logs
                                    pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                                    pad = pad_info['pad']
                                    line_positions = pad_info['line_positions']
                                    actual_lines_count = pad_info['actual_lines']
                                else:
                                    # Append new logs to existing pad
                                    current_line = actual_lines_count
                                    for i, line in enumerate(new_logs):
                                        line_positions.append(current_line)
                                        if tui.wrap_log_lines:
                                            # Split the line into wrapped segments
                                            remaining = line
                                            while remaining:
                                                segment = remaining[:w-3]
                                                try:
                                                    pad.addstr(current_line, 0, segment)
                                                except curses.error:
                                                    pass
                                                current_line += 1
                                                remaining = remaining[w-3:]
                                        else:
                                            # No wrapping - just add the whole line
                                            try:
                                                pad.addstr(current_line, 0, line)
                                            except curses.error:
                                                pass
                                            current_line += 1
                                    
                                    # Update line counts
                                    actual_lines_count = current_line
                            
                            # Update line count
                            last_logical_lines_count = len(logs)
                            
                            # Reapply search highlights if we have a search pattern
                            if search_string:
                                search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                                search_matches = search_result['matches']
                                current_match = search_result['current_match']
                                highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                            
                            # Auto-scroll to bottom in follow mode
                            if follow_mode:
                                pos = max(0, actual_lines_count - (h-4))
                except Exception:
                    pass  # Ignore errors in log fetching
                
                last_log_time = current_time
            
            # Always ensure pos is valid
            if actual_lines_count > 0:
                pos = max(0, min(pos, actual_lines_count - 1))
            else:
                pos = 0
            
            # Handle search input mode
            if search_mode:
                # Create input line at bottom
                search_prompt = " Search: "
                stdscr.attron(curses.color_pair(6))
                safe_addstr(stdscr, h-1, 0, search_prompt, curses.color_pair(6) | curses.A_BOLD)
                safe_addstr(stdscr, h-1, len(search_prompt), search_input + " " * (w - len(search_prompt) - len(search_input) - 1), curses.color_pair(6))
                
                # Show case sensitivity indicator
                case_text = "Case: " + ("ON" if case_sensitive else "OFF") + " (Tab)"
                safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                
                # Show search status if there's a current search
                if search_string and search_matches:
                    match_info = f" {current_match + 1}/{len(search_matches)} matches "
                    safe_addstr(stdscr, 1, 0, match_info, curses.A_BOLD)
                
                stdscr.attroff(curses.color_pair(6))
                
                # Show cursor at end of input
                curses.curs_set(1)  # Show cursor
                stdscr.move(h-1, len(search_prompt) + len(search_input))
                stdscr.refresh()
                
                # Get character
                ch = stdscr.getch()
                
                if ch == 27:  # Escape - exit search mode
                    search_mode = False
                    curses.curs_set(0)  # Hide cursor
                    just_processed_search = True  # Skip normal key handling this iteration
                elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:  # Backspace
                    if search_input:
                        search_input = search_input[:-1]
                elif ch == 10:  # Enter - perform search
                    if search_input:
                        search_string = search_input
                        
                        # Perform search
                        search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                        search_matches = search_result['matches']
                        current_match = search_result['current_match']
                        
                        # Update UI if search was successful
                        if search_matches:
                            # Jump to first match
                            next_match = next_search_match(search_matches, current_match, line_positions, tui.wrap_log_lines, w)
                            if next_match:
                                pos = next_match['position']
                                current_match = next_match['match_index']
                            follow_mode = False  # Disable follow mode when searching
                            
                            # Apply highlights
                            highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                            
                            # Exit search mode but keep the string
                            search_mode = False
                            curses.curs_set(0)  # Hide cursor
                            
                            # Clear input buffer completely to prevent Enter key from being processed again
                            stdscr.nodelay(True)
                            while stdscr.getch() != -1:
                                pass  # Discard any input
                            stdscr.nodelay(False)
                            
                            # Force refresh
                            stdscr.clear()
                            
                            # Update header with search info
                            stdscr.attron(curses.color_pair(5))
                            safe_addstr(stdscr, 0, 0, " " * w)
                            normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                            wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                            search_indicator = f" [SEARCH: {search_string}]"
                            filter_indicator = get_filter_indicator(filter_string) if filtering_active else ""
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
                            safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                            stdscr.attroff(curses.color_pair(5))
                            
                            # Restore normal footer
                            if filtering_active:
                                if tui.wrap_log_lines:
                                    footer_text = " ↑/↓:Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                                else:
                                    footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                            elif tui.wrap_log_lines:
                                footer_text = " ↑/↓:Scroll | PgUp/Dn:Page | F:Toggle Follow | N:Normalize | W:Wrap | /:Search | \\:Filter | ESC:Back "
                            else:
                                footer_text = " ↑/↓:Scroll | ←/→:Scroll H | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | /:Search | \\:Filter | ESC:Back "
                            
                            stdscr.attron(curses.color_pair(6))
                            safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                            stdscr.attroff(curses.color_pair(6))
                            
                            # Force an immediate pad refresh
                            pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
                            stdscr.refresh()
                            
                            # Skip normal key handling in this iteration
                            just_processed_search = True
                        else:
                            # No matches found - show message
                            safe_addstr(stdscr, h-2, 0, f" No matches found for '{search_string}' ", curses.A_BOLD)
                            stdscr.refresh()
                            time.sleep(1)  # Show message briefly
                            
                            # Clear any remaining input in the buffer
                            stdscr.nodelay(True)
                            while stdscr.getch() != -1:
                                pass
                            stdscr.nodelay(False)
                    else:
                        # Empty search string - clear search
                        search_string = ""
                        search_matches = []
                        current_match = -1
                        search_mode = False
                        curses.curs_set(0)  # Hide cursor
                        
                        # Clear any remaining input in the buffer
                        stdscr.nodelay(True)
                        while stdscr.getch() != -1:
                            pass
                        stdscr.nodelay(False)
                        
                        just_processed_search = True  # Skip normal key handling this iteration
                elif ch == 9:  # Tab - toggle case sensitivity
                    case_sensitive = not case_sensitive
                elif ch == 14:  # Ctrl+N - next match
                    if search_string and search_matches:
                        next_match = next_search_match(search_matches, current_match, line_positions, tui.wrap_log_lines, w)
                        if next_match:
                            pos = next_match['position']
                            current_match = next_match['match_index']
                        follow_mode = False
                elif ch == 16:  # Ctrl+P - previous match
                    if search_string and search_matches:
                        prev_match = prev_search_match(search_matches, current_match, line_positions, tui.wrap_log_lines, w)
                        if prev_match:
                            pos = prev_match['position']
                            current_match = prev_match['match_index']
                        follow_mode = False
                elif ch < 256 and ch >= 32:  # Printable character
                    search_input += chr(ch)
            
            # Handle filter input mode
            elif filter_mode:
                # Create input line at bottom
                filter_prompt = " Filter: "
                stdscr.attron(curses.color_pair(6))
                safe_addstr(stdscr, h-1, 0, filter_prompt, curses.color_pair(6) | curses.A_BOLD)
                safe_addstr(stdscr, h-1, len(filter_prompt), filter_input + " " * (w - len(filter_prompt) - len(filter_input) - 1), curses.color_pair(6))
                
                # Show filter help
                help_text = "Space-separated filters: word +include -exclude \"multi word\" | Tab:Case"
                if w > len(help_text) + 15:
                    safe_addstr(stdscr, h-2, (w - len(help_text)) // 2, help_text, curses.A_DIM)
                
                # Show case sensitivity indicator
                case_text = "Case: " + ("ON" if case_sensitive else "OFF")
                safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                stdscr.attroff(curses.color_pair(6))
                
                # Show cursor at end of input
                curses.curs_set(1)  # Show cursor
                stdscr.move(h-1, len(filter_prompt) + len(filter_input))
                stdscr.refresh()
                
                # Get character
                ch = stdscr.getch()
                
                if ch == 27:  # Escape - exit filter mode
                    filter_mode = False
                    curses.curs_set(0)  # Hide cursor
                    just_processed_filter = True  # Skip normal key handling this iteration
                elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:  # Backspace
                    if filter_input:
                        filter_input = filter_input[:-1]
                elif ch == 10:  # Enter - apply filter
                    if filter_input:
                        # Store filter string
                        filter_string = filter_input
                        
                        # Apply filter to logs
                        filtered_logs, filtered_line_map = filter_logs(original_logs, filter_string, case_sensitive)
                        
                        # Apply filter regardless of whether there are matches
                        filtering_active = True
                        logs = filtered_logs
                        
                        # Rebuild pad with filtered logs
                        pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                        pad = pad_info['pad']
                        line_positions = pad_info['line_positions']
                        actual_lines_count = pad_info['actual_lines']
                        
                        # Update line count
                        last_logical_lines_count = len(logs)
                        
                        # Apply search highlighting if there's a search pattern
                        if search_string:
                            search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                            search_matches = search_result['matches']
                            current_match = search_result['current_match']
                            highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                        
                        # Exit filter mode
                        filter_mode = False
                        curses.curs_set(0)  # Hide cursor
                        
                        # Clear input buffer
                        stdscr.nodelay(True)
                        while stdscr.getch() != -1:
                            pass
                        stdscr.nodelay(False)
                        
                        # Update header with filter info
                        stdscr.attron(curses.color_pair(5))
                        safe_addstr(stdscr, 0, 0, " " * w)
                        normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                        search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                        filter_indicator = get_filter_indicator(filter_string)
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
                        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        
                        # Update filter info in status line
                        filter_info = f" Filtered: {len(filtered_logs)}/{len(original_logs)} lines "
                        safe_addstr(stdscr, 1, 0, filter_info, curses.A_BOLD)
                        
                        # Reset position to start of filtered logs
                        pos = 0
                        
                        just_processed_filter = True
                    else:
                        # Empty filter string - clear filter
                        if filtering_active:
                            filtering_active = False
                            filter_string = ""
                            logs = original_logs
                            
                            # Rebuild pad with all logs
                            pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                            pad = pad_info['pad']
                            line_positions = pad_info['line_positions']
                            actual_lines_count = pad_info['actual_lines']
                            
                            # Update line count
                            last_logical_lines_count = len(logs)
                            
                            # Apply search highlighting if there's a search pattern
                            if search_string:
                                search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                                search_matches = search_result['matches']
                                current_match = search_result['current_match']
                                highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                            
                            # Update header without filter info
                            stdscr.attron(curses.color_pair(5))
                            safe_addstr(stdscr, 0, 0, " " * w)
                            normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                            wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                            search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator
                            safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                            stdscr.attroff(curses.color_pair(5))
                            
                            # Clear filter info
                            safe_addstr(stdscr, 1, 0, " " * 30)
                            
                            # Show search status if there's a current search
                            if search_string and search_matches:
                                match_info = f" {current_match + 1}/{len(search_matches)} matches "
                                safe_addstr(stdscr, 1, 0, match_info, curses.A_BOLD)
                        
                        # Exit filter mode
                        filter_mode = False
                        curses.curs_set(0)  # Hide cursor
                        
                        # Clear input buffer
                        stdscr.nodelay(True)
                        while stdscr.getch() != -1:
                            pass
                        stdscr.nodelay(False)
                        
                        just_processed_filter = True
                elif ch == 9:  # Tab - toggle case sensitivity
                    case_sensitive = not case_sensitive
                elif ch < 256 and ch >= 32:  # Printable character
                    filter_input += chr(ch)
            
            # Update display regularly regardless of new logs or position changes
            elif current_time - last_display_time >= draw_interval:  # Use the specified draw interval
                # Update header only when needed (status change)
                if follow_mode != last_follow_mode or tui.normalize_logs != last_normalize_logs or tui.wrap_log_lines != last_wrap_lines or (filtering_active and not logs):
                    stdscr.attron(curses.color_pair(5))
                    safe_addstr(stdscr, 0, 0, " " * w)
                    normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                    wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                    search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                    filter_indicator = f" [FILTER: {filter_string}]" if filtering_active else ""
                    header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
                    safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                    stdscr.attroff(curses.color_pair(5))
                    
                    # Update footer if filtering is active
                    if filtering_active:
                        if tui.wrap_log_lines:
                            footer_text = " ↑/↓:Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                        else:
                            footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                        
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                        stdscr.attroff(curses.color_pair(6))
                    
                    # Track current state
                    last_follow_mode = follow_mode
                    last_normalize_logs = tui.normalize_logs
                    last_wrap_lines = tui.wrap_log_lines
                
                # Update line counter
                if line_positions:
                    logical_pos = 0
                    for i, line_pos in enumerate(line_positions):
                        if line_pos > pos:
                            break
                        logical_pos = i
                    
                    line_info = f" Line: {logical_pos+1}/{last_logical_lines_count} "
                    safe_addstr(stdscr, 1, w-len(line_info)-1, line_info)
                else:
                    # No lines to display
                    line_info = f" Line: 0/{last_logical_lines_count} "
                    safe_addstr(stdscr, 1, w-len(line_info)-1, line_info)
                
                # Show search status if there's a current search
                if search_string and search_matches:
                    match_info = f" {current_match + 1}/{len(search_matches)} matches "
                    safe_addstr(stdscr, 1, 0, match_info, curses.A_BOLD)
                
                # Show filter status if active
                if filtering_active:
                    filter_info = f" Filtered: {len(filtered_logs)}/{len(original_logs)} lines "
                    if not (search_string and search_matches):  # Don't overwrite search info
                        safe_addstr(stdscr, 1, 0, filter_info, curses.A_BOLD)
                
                # Update scrollbar
                scrollbar_height = h - 4
                if actual_lines_count > scrollbar_height and scrollbar_height > 0:
                    scrollbar_pos = 2
                    if actual_lines_count > scrollbar_height:
                        scrollbar_pos = 2 + int((pos / (actual_lines_count - scrollbar_height)) * (scrollbar_height - 1))
                    for i in range(2, h-2):
                        if i == scrollbar_pos:
                            safe_addstr(stdscr, i, w-1, "█")
                        else:
                            safe_addstr(stdscr, i, w-1, "│")
                
                # Determine horizontal scroll position
                if not tui.wrap_log_lines:
                    # Update max line length
                    max_line_length = max([len(line) for line in logs], default=0)
                    
                    # Show horizontal scrollbar if needed
                    if max_line_length > w-3:
                        # Calculate horizontal scrollbar position indicators
                        scrollbar_width = w - 4
                        total_width = max_line_length
                        visible_width = w - 3
                        
                        # Create base scrollbar
                        h_scrollbar = "◄" + "─" * (scrollbar_width - 2) + "►"
                        
                        # Calculate thumb position and size
                        if total_width > 0:
                            thumb_pos = int((h_scroll / total_width) * scrollbar_width)
                            thumb_size = max(1, int((visible_width / total_width) * scrollbar_width))
                            thumb_end = min(scrollbar_width - 1, thumb_pos + thumb_size)
                            
                            # Replace characters with the thumb
                            h_scrollbar_list = list(h_scrollbar)
                            for i in range(thumb_pos + 1, thumb_end + 1):
                                if 1 <= i < len(h_scrollbar_list) - 1:  # Avoid overwriting the arrows
                                    h_scrollbar_list[i] = "═"
                            h_scrollbar = "".join(h_scrollbar_list)
                        
                        # Show horizontal position
                        pos_text = f" {h_scroll+1}-{min(h_scroll+visible_width, total_width)}/{total_width} "
                        safe_addstr(stdscr, h-2, 0, h_scrollbar, curses.A_DIM)
                        safe_addstr(stdscr, h-2, w-len(pos_text), pos_text, curses.A_DIM)
                
                # Apply search highlights if needed
                if search_string and search_matches:
                    highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                
                # Display empty state message if filtering and no logs
                if filtering_active and not logs:
                    # Clear the content area
                    for i in range(2, h-2):
                        safe_addstr(stdscr, i, 0, " " * (w-1))
                    
                    # Parse filter to show what's active
                    filter_desc = []
                    filters = []
                    current_filter = ""
                    in_quotes = False
                    i = 0
                    
                    while i < len(filter_string):
                        char = filter_string[i]
                        if char == '"':
                            in_quotes = not in_quotes
                            i += 1
                        elif char == ' ' and not in_quotes:
                            if current_filter:
                                filters.append(current_filter)
                                current_filter = ""
                            i += 1
                        else:
                            current_filter += char
                            i += 1
                    
                    if current_filter:
                        filters.append(current_filter)
                    
                    for f in filters:
                        if f.startswith('!') or f.startswith('-'):
                            filter_desc.append(f"excluding '{f[1:]}'")
                        elif f.startswith('+'):
                            filter_desc.append(f"including '{f[1:]}'")
                        elif f:
                            filter_desc.append(f"including '{f}'")
                    
                    # Show waiting message
                    empty_msg1 = "No logs matching filter:"
                    empty_msg2 = " AND ".join(filter_desc) if filter_desc else filter_string
                    empty_msg3 = "Waiting for matching logs..."
                    empty_msg4 = "(Press \\ to change filter or ESC to clear)"
                    
                    center_y = h // 2
                    safe_addstr(stdscr, center_y - 2, (w - len(empty_msg1)) // 2, empty_msg1, curses.A_BOLD)
                    safe_addstr(stdscr, center_y - 1, (w - len(empty_msg2)) // 2, empty_msg2, curses.A_DIM)
                    safe_addstr(stdscr, center_y, (w - len(empty_msg3)) // 2, empty_msg3, curses.A_DIM)
                    safe_addstr(stdscr, center_y + 1, (w - len(empty_msg4)) // 2, empty_msg4, curses.A_DIM)
                    
                    stdscr.refresh()
                else:
                    # Always refresh the pad
                    try:
                        pad.refresh(pos, h_scroll, 2, 0, h-2, w-2)
                        stdscr.refresh()
                    except curses.error:
                        # Handle potential pad errors
                        pass
                
                last_display_time = current_time
            
            # Handle key input in normal mode (but skip if we just processed a search/filter)
            if not search_mode and not filter_mode and not skip_normal_input:
                # Check for user input with short timeout to maintain display
                stdscr.timeout(100)  # 100ms timeout for getch
                ch = stdscr.getch()
                
                if ch != -1:
                    if ch == curses.KEY_DOWN:
                        # Scroll down one line
                        if pos < actual_lines_count - 1:
                            pos += 1
                            follow_mode = False
                    elif ch == curses.KEY_UP:
                        # Scroll up one line
                        if pos > 0:
                            pos -= 1
                            follow_mode = False
                    elif ch == curses.KEY_NPAGE:  # Page Down
                        # Scroll down one page
                        pos = min(actual_lines_count - 1, pos + (h-5))
                        follow_mode = False
                    elif ch == curses.KEY_PPAGE:  # Page Up
                        # Scroll up one page
                        pos = max(0, pos - (h-5))
                        follow_mode = False
                    elif ch == ord(' '):  # Space - page down
                        pos = min(actual_lines_count - 1, pos + (h-5))
                        follow_mode = False
                    elif ch == curses.KEY_HOME:  # Home - go to start
                        pos = 0
                        follow_mode = False
                    elif ch == ord('g'):  # g - go to start
                        pos = 0
                        follow_mode = False
                    elif ch == curses.KEY_END:  # End - go to end
                        pos = max(0, actual_lines_count - (h-4))
                        follow_mode = True
                    elif ch == ord('G'):  # G - go to end
                        pos = max(0, actual_lines_count - (h-4))
                        follow_mode = True
                    elif ch in (ord('f'), ord('F')):  # Toggle follow mode
                        follow_mode = not follow_mode
                        if follow_mode:
                            pos = max(0, actual_lines_count - (h-4))
                        
                        # Update header
                        stdscr.attron(curses.color_pair(5))
                        safe_addstr(stdscr, 0, 0, " " * w)
                        normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                        search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                        filter_indicator = get_filter_indicator(filter_string) if filtering_active else ""
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
                        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        
                        # Update footer based on filter state
                        if filtering_active:
                            if tui.wrap_log_lines:
                                footer_text = " ↑/↓:Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                            else:
                                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                            
                            stdscr.attron(curses.color_pair(6))
                            safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                            stdscr.attroff(curses.color_pair(6))
                        
                        stdscr.refresh()
                    elif ch in (ord('n'), ord('N')):  # Toggle normalization or next/prev search
                        if ch == ord('n') and search_string and search_matches:
                            # Use 'n' for next search match
                            next_match = next_search_match(search_matches, current_match, line_positions, tui.wrap_log_lines, w)
                            if next_match:
                                pos = next_match['position']
                                current_match = next_match['match_index']
                            follow_mode = False
                        elif ch == ord('N') and search_string and search_matches:
                            # Use 'N' for previous search match
                            prev_match = prev_search_match(search_matches, current_match, line_positions, tui.wrap_log_lines, w)
                            if prev_match:
                                pos = prev_match['position']
                                current_match = prev_match['match_index']
                            follow_mode = False
                        elif ch == ord('n'):  # Only 'n' toggles normalization when not searching
                            tui.normalize_logs = not tui.normalize_logs
                            
                            # Renormalize or revert to raw logs
                            if tui.normalize_logs:
                                # Normalize the original logs first
                                normalized_original = normalize_container_logs(tui.normalize_logs, tui.normalize_logs_script, all_raw_logs)
                                original_logs = normalized_original
                                
                                # If filtering is active, apply filter to normalized logs
                                if filtering_active:
                                    filtered_logs, filtered_line_map = filter_logs(original_logs, filter_string, case_sensitive)
                                    logs = filtered_logs
                                else:
                                    logs = original_logs
                            else:
                                # Use raw logs
                                original_logs = all_raw_logs.copy()
                                
                                # If filtering is active, apply filter to raw logs
                                if filtering_active:
                                    filtered_logs, filtered_line_map = filter_logs(original_logs, filter_string, case_sensitive)
                                    logs = filtered_logs
                                else:
                                    logs = original_logs
                            
                            # Rebuild pad with updated content
                            pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                            pad = pad_info['pad']
                            line_positions = pad_info['line_positions']
                            actual_lines_count = pad_info['actual_lines']
                            
                            # Update line count
                            last_logical_lines_count = len(logs)
                            
                            # Update header immediately
                            stdscr.attron(curses.color_pair(5))
                            normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                            wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                            search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                            filter_indicator = get_filter_indicator(filter_string) if filtering_active else ""
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
                            safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                            stdscr.attroff(curses.color_pair(5))
                            stdscr.refresh()
                            
                            # Reapply search if needed
                            if search_string:
                                search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                                search_matches = search_result['matches']
                                current_match = search_result['current_match']
                                highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                            
                            # Maintain position proportionally
                            if last_logical_lines_count > 0:
                                pos = min(pos, actual_lines_count - 1)
                            else:
                                pos = 0
                    elif ch in (ord('w'), ord('W')):  # Toggle line wrapping
                        tui.wrap_log_lines = not tui.wrap_log_lines
                        
                        # Reset horizontal scroll if switching to wrapped mode
                        if tui.wrap_log_lines:
                            h_scroll = 0
                        
                        # Rebuild pad with new wrapping setting
                        pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                        pad = pad_info['pad']
                        line_positions = pad_info['line_positions']
                        actual_lines_count = pad_info['actual_lines']
                        
                        # Update footer immediately to show horizontal scroll keys if unwrapped
                        if filtering_active:
                            if tui.wrap_log_lines:
                                footer_text = " ↑/↓:Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                            else:
                                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | /:Search | \\:Change Filter | ESC:Clear Filter | Q:Back "
                        elif tui.wrap_log_lines:
                            footer_text = " ↑/↓:Scroll | PgUp/Dn:Page | F:Toggle Follow | N:Normalize | W:Wrap | /:Search | \\:Filter | ESC:Back "
                        else:
                            footer_text = " ↑/↓:Scroll | ←/→:Scroll H | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | /:Search | \\:Filter | ESC:Back "
                        
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                        stdscr.attroff(curses.color_pair(6))
                        
                        # Update header immediately to reflect changed wrapping mode
                        stdscr.attron(curses.color_pair(5))
                        normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                        search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                        filter_indicator = f" [FILTER: {filter_string}]" if filtering_active else ""
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator + filter_indicator
                        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        stdscr.refresh()
                        
                        # Reapply search if needed
                        if search_string:
                            search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                            search_matches = search_result['matches']
                            current_match = search_result['current_match']
                            highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                        
                        # Maintain position proportionally
                        if actual_lines_count > 0:
                            # Try to keep the same logical line visible
                            logical_pos = 0
                            for i, line_pos in enumerate(line_positions):
                                if line_pos > pos:
                                    break
                                logical_pos = i
                            
                            # Go to that logical line in new pad
                            if logical_pos < len(line_positions):
                                pos = line_positions[logical_pos]
                            else:
                                pos = 0
                        else:
                            pos = 0
                    elif ch == ord('/'):  # Start search
                        search_mode = True
                        search_input = search_string  # Initialize with previous search
                        
                        # Show search prompt
                        search_prompt = " Search: "
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, search_prompt, curses.color_pair(6) | curses.A_BOLD)
                        safe_addstr(stdscr, h-1, len(search_prompt), search_input + " " * (w - len(search_prompt) - len(search_input) - 1), curses.color_pair(6))
                        
                        # Show case sensitivity indicator
                        case_text = "Case: " + ("ON" if case_sensitive else "OFF") + " (Tab)"
                        safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(6))
                        
                        curses.curs_set(1)  # Show cursor
                        stdscr.move(h-1, len(search_prompt) + len(search_input))
                        stdscr.refresh()
                    elif ch == ord('\\'):  # Start filter
                        filter_mode = True
                        filter_input = filter_string  # Initialize with previous filter
                        
                        # Show filter prompt
                        filter_prompt = " Filter: "
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, filter_prompt, curses.color_pair(6) | curses.A_BOLD)
                        safe_addstr(stdscr, h-1, len(filter_prompt), filter_input + " " * (w - len(filter_prompt) - len(filter_input) - 1), curses.color_pair(6))
                        
                        # Show filter help
                        help_text = "Space-separated filters: word +include -exclude \"multi word\" | Tab:Case"
                        if w > len(help_text) + 15:
                            safe_addstr(stdscr, h-2, (w - len(help_text)) // 2, help_text, curses.A_DIM)
                        
                        # Show case sensitivity indicator
                        case_text = "Case: " + ("ON" if case_sensitive else "OFF")
                        safe_addstr(stdscr, h-1, w - len(case_text) - 1, case_text, curses.color_pair(6) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(6))
                        
                        curses.curs_set(1)  # Show cursor
                        stdscr.move(h-1, len(filter_prompt) + len(filter_input))
                        stdscr.refresh()
                    elif ch == curses.KEY_RIGHT and not tui.wrap_log_lines:  # Right arrow for horizontal scroll
                        # Only allow horizontal scrolling in unwrapped mode
                        h_scroll = min(h_scroll + 10, max_line_length - (w - 5))
                        h_scroll = max(0, h_scroll)  # Ensure positive
                    elif ch == curses.KEY_LEFT and not tui.wrap_log_lines:  # Left arrow for horizontal scroll
                        h_scroll = max(0, h_scroll - 10)  # Scroll left by 10 characters
                    elif ch == curses.KEY_MOUSE:
                        try:
                            _, mx, my, _, button_state = curses.getmouse()
                            # Scroll with mouse wheel
                            if button_state & curses.BUTTON4_PRESSED:  # Wheel up
                                pos = max(0, pos - 3)
                                follow_mode = False
                            elif button_state & curses.BUTTON5_PRESSED:  # Wheel down
                                pos = min(actual_lines_count - 1, pos + 3)
                                follow_mode = False
                            # Horizontal scrolling with Shift+wheel or horizontal wheel
                            elif not tui.wrap_log_lines and button_state & (1 << 8):  # Horizontal wheel left
                                h_scroll = max(0, h_scroll - 10)
                            elif not tui.wrap_log_lines and button_state & (1 << 9):  # Horizontal wheel right
                                h_scroll = min(h_scroll + 10, max_line_length - (w - 5))
                                h_scroll = max(0, h_scroll)
                            # Click on scrollbar to jump
                            elif button_state & curses.BUTTON1_CLICKED and mx == w-1 and 2 <= my < h-2:
                                # Calculate position from click on scrollbar
                                click_percent = (my - 2) / (h - 4)
                                pos = int(click_percent * actual_lines_count)
                                follow_mode = False
                        except curses.error:
                            pass
                    elif ch in (27, ord('q'), ord('Q')):  # ESC or Q to exit
                        # If filtering is active and ESC is pressed, clear the filter first
                        if ch == 27 and filtering_active:
                            filtering_active = False
                            filter_string = ""
                            logs = original_logs
                            
                            # Rebuild pad with all logs
                            pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                            pad = pad_info['pad']
                            line_positions = pad_info['line_positions']
                            actual_lines_count = pad_info['actual_lines']
                            
                            # Update line count
                            last_logical_lines_count = len(logs)
                            
                            # Apply search highlighting if there's a search pattern
                            if search_string:
                                search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                                search_matches = search_result['matches']
                                current_match = search_result['current_match']
                                highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                            
                            # Update header without filter info
                            stdscr.attron(curses.color_pair(5))
                            safe_addstr(stdscr, 0, 0, " " * w)
                            normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                            wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                            search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + search_indicator
                            safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                            stdscr.attroff(curses.color_pair(5))
                            
                            # Clear filter info from status line
                            safe_addstr(stdscr, 1, 0, " " * 30)
                            
                            # Show search status if there's a current search
                            if search_string and search_matches:
                                match_info = f" {current_match + 1}/{len(search_matches)} matches "
                                safe_addstr(stdscr, 1, 0, match_info, curses.A_BOLD)
                            
                            # Force refresh
                            stdscr.refresh()
                        else:
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
        stdscr.nodelay(True)  # Restore non-blocking mode
        stdscr.refresh()