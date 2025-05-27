#!/usr/bin/env python3
"""
Docker TUI - Log View Module
-----------
Handles container log viewing with advanced filtering and dynamic tail support.
"""
import curses
import re
import time
import subprocess
import os
from ..utils.utils import safe_addstr
import concurrent.futures
import aiohttp
from datetime import datetime, timezone
import json

def parse_filter_expression(filter_string):
    """Parse filter expression with AND/OR operators and parentheses
    
    Returns a parsed structure that can be evaluated against log lines.
    Supports:
    - Basic terms: word, +word (include), -word/!word (exclude)
    - AND operator: word AND word
    - OR operator: word OR word
    - Parentheses: (word OR word) AND word
    - Quoted strings: "multi word phrase"
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

def evaluate_filter(tokens, line, case_sensitive=False):
    """Evaluate parsed filter tokens against a log line
    
    Uses a simple recursive descent parser to evaluate the expression.
    """
    if not tokens:
        return True
    
    flags = 0 if case_sensitive else re.IGNORECASE
    
    def evaluate_term(term, line):
        """Evaluate a single term against the line"""
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
    
    def parse_expression(pos=0):
        """Parse and evaluate expression starting at position pos"""
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

def get_filter_indicator(filter_string):
    """Generate a concise filter indicator for the header"""
    if not filter_string:
        return ""
    
    # For complex expressions, show a simplified version
    if len(filter_string) > 30:
        return f" [FILTER: {filter_string[:27]}...] "
    else:
        return f" [FILTER: {filter_string}] "

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
    """Filter logs with advanced expression support"""
    if not filter_string:
        return logs, []  # Return original logs if no filter
    
    # Parse the filter expression
    tokens = parse_filter_expression(filter_string)
    if not tokens:
        return logs, []
    
    filtered_logs = []
    line_map = []  # Maps filtered line index to original line index
    
    # Process each log line
    for i, line in enumerate(logs):
        if evaluate_filter(tokens, line, case_sensitive):
            filtered_logs.append(line)
            line_map.append(i)
    
    return filtered_logs, line_map

def show_time_filter_dialog(stdscr):
    """Show dialog to set time range filter"""
    h, w = stdscr.getmaxyx()
    
    # Create dialog window
    dialog_width = 70
    dialog_height = 15
    dialog_y = (h - dialog_height) // 2
    dialog_x = (w - dialog_width) // 2
    
    dialog = curses.newwin(dialog_height, dialog_width, dialog_y, dialog_x)
    dialog.keypad(True)
    dialog.border()
    
    # Draw title
    title = " Time Range Filter "
    safe_addstr(dialog, 0, (dialog_width - len(title)) // 2, title)
    
    # Show current system time
    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    time_info = f"Current system time: {current_time_str}"
    safe_addstr(dialog, 2, (dialog_width - len(time_info)) // 2, time_info, curses.A_BOLD)
    
    # Draw instructions
    safe_addstr(dialog, 4, 2, "Filter logs by time range:")
    safe_addstr(dialog, 5, 2, "Format: YYYY-MM-DD HH:MM:SS (or partial like '2024-01-01')")
    safe_addstr(dialog, 6, 2, "Leave empty for no filter")
    safe_addstr(dialog, 7, 2, "Note: Only logs with timestamps will be shown")
    
    # Input fields
    safe_addstr(dialog, 9, 2, "From time: ")
    safe_addstr(dialog, 10, 2, "To time:   ")
    safe_addstr(dialog, 11, 2, "(empty = until present)")
    
    from_input = ""
    to_input = ""
    current_field = 0  # 0 = from, 1 = to
    
    curses.curs_set(1)  # Show cursor
    
    while True:
        # Clear input lines
        safe_addstr(dialog, 9, 12, " " * (dialog_width - 14))
        safe_addstr(dialog, 10, 12, " " * (dialog_width - 14))
        
        # Draw inputs
        safe_addstr(dialog, 9, 12, from_input, curses.A_REVERSE if current_field == 0 else 0)
        safe_addstr(dialog, 10, 12, to_input, curses.A_REVERSE if current_field == 1 else 0)
        
        # Position cursor
        if current_field == 0:
            dialog.move(9, 12 + len(from_input))
        else:
            dialog.move(10, 12 + len(to_input))
        
        dialog.refresh()
        
        ch = dialog.getch()
        
        if ch == 27:  # ESC - cancel
            curses.curs_set(0)
            return None
        elif ch == 9:  # Tab - switch field
            current_field = 1 - current_field
        elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            if current_field == 0 and from_input:
                from_input = from_input[:-1]
            elif current_field == 1 and to_input:
                to_input = to_input[:-1]
        elif ch == 10:  # Enter - confirm
            curses.curs_set(0)
            return {'from': from_input.strip(), 'to': to_input.strip()}
        elif ch < 256 and ch >= 32:  # Printable character
            if current_field == 0 and len(from_input) < 19:
                from_input += chr(ch)
            elif current_field == 1 and len(to_input) < 19:
                to_input += chr(ch)

def show_export_dialog(stdscr):
    """Show dialog to configure log export"""
    h, w = stdscr.getmaxyx()
    
    # Create dialog window
    dialog_width = 60
    dialog_height = 10
    dialog_y = (h - dialog_height) // 2
    dialog_x = (w - dialog_width) // 2
    
    dialog = curses.newwin(dialog_height, dialog_width, dialog_y, dialog_x)
    dialog.keypad(True)
    dialog.border()
    
    # Draw title
    title = " Export Logs "
    safe_addstr(dialog, 0, (dialog_width - len(title)) // 2, title)
    
    # Draw instructions
    safe_addstr(dialog, 2, 2, "Export location:")
    safe_addstr(dialog, 3, 2, "1. Current directory")
    safe_addstr(dialog, 4, 2, "2. Custom path")
    safe_addstr(dialog, 6, 2, "Enter choice (1/2) or ESC to cancel:")
    
    dialog.refresh()
    
    while True:
        ch = dialog.getch()
        
        if ch == 27:  # ESC - cancel
            return None
        elif ch == ord('1'):
            return {'type': 'current_dir'}
        elif ch == ord('2'):
            # Get custom path
            safe_addstr(dialog, 7, 2, "Enter path: ")
            dialog.refresh()
            
            path_input = ""
            curses.curs_set(1)
            
            while True:
                # Clear and redraw input
                safe_addstr(dialog, 7, 14, " " * (dialog_width - 16))
                safe_addstr(dialog, 7, 14, path_input)
                dialog.move(7, 14 + len(path_input))
                dialog.refresh()
                
                ch2 = dialog.getch()
                
                if ch2 == 27:  # ESC - cancel
                    curses.curs_set(0)
                    return None
                elif ch2 == curses.KEY_BACKSPACE or ch2 == 127 or ch2 == 8:
                    if path_input:
                        path_input = path_input[:-1]
                elif ch2 == 10:  # Enter - confirm
                    curses.curs_set(0)
                    return {'type': 'custom_path', 'path': path_input.strip()}
                elif ch2 < 256 and ch2 >= 32:  # Printable character
                    if len(path_input) < 50:
                        path_input += chr(ch2)

def parse_time_string(time_str):
    """Parse time string in various formats"""
    if not time_str:
        return None
    
    # Try different time formats
    formats = [
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M', 
        '%Y-%m-%d %H',
        '%Y-%m-%d',
        '%m-%d %H:%M:%S',
        '%m-%d %H:%M',
        '%m-%d',
        '%H:%M:%S',
        '%H:%M'
    ]
    
    current_year = datetime.now().year
    current_month = datetime.now().month
    current_day = datetime.now().day
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(time_str, fmt)
            
            # Fill in missing parts with current values
            if '%Y' not in fmt:
                parsed = parsed.replace(year=current_year)
            if '%m' not in fmt:
                parsed = parsed.replace(month=current_month)
            if '%d' not in fmt:
                parsed = parsed.replace(day=current_day)
            
            return parsed
        except ValueError:
            continue
    
    return None

def convert_to_docker_time_format(time_str, reference_logs=None):
    """Convert user time input to datetime object for Docker API"""
    if not time_str:
        return None
    
    # Parse the time string
    parsed_time = parse_time_string(time_str)
    if not parsed_time:
        return None
    
    # If this is a time-only input (no date components), use current date
    if ':' in time_str and not any(c in time_str for c in ['-', '/', 'T']):
        current_date = datetime.now().date()
        parsed_time = datetime.combine(current_date, parsed_time.time())
        

    
    # Return the datetime object directly - Docker API expects this, not a string!
    return parsed_time

def fetch_logs_with_time_filter(container, since=None, until=None, tail=None):
    """Fetch logs using Docker's native time filtering"""
    # Maximum number of logs to prevent memory issues and crashes
    MAX_LOGS_SAFE = 20000
    
    try:
        # Prepare Docker logs parameters
        log_params = {}
        
        if since:
            log_params['since'] = since
        if until:
            log_params['until'] = until
        if tail and tail > 0:
            log_params['tail'] = tail
        

        
        # Fetch logs with Docker's native filtering
        raw_logs = container.logs(**log_params).decode(errors='ignore').splitlines()
        
        # Check if we got too many logs and truncate for safety
        if len(raw_logs) > MAX_LOGS_SAFE:
            raw_logs = raw_logs[-MAX_LOGS_SAFE:]  # Keep the most recent logs
        
        return raw_logs
    except Exception as e:
        # If Docker filtering fails, fallback to regular logs
        if tail and tail > 0:
            return container.logs(tail=tail).decode(errors='ignore').splitlines()
        else:
            # For fallback, also apply safe limit
            fallback_logs = container.logs().decode(errors='ignore').splitlines()
            if len(fallback_logs) > MAX_LOGS_SAFE:
                fallback_logs = fallback_logs[-MAX_LOGS_SAFE:]
            return fallback_logs

def filter_logs_by_time(logs, from_time=None, to_time=None, debug=False):
    """Filter logs by time range"""
    if not from_time and not to_time:
        return logs, list(range(len(logs)))
    
    filtered_logs = []
    line_map = []
    
    # Parse time bounds
    from_dt = parse_time_string(from_time) if from_time else None
    to_dt = parse_time_string(to_time) if to_time else None
    

    
    # Collect log timestamps to determine the appropriate date context
    log_dates = []
    if from_dt or to_dt:
        for line in logs:
            log_time = extract_log_timestamp(line)
            if log_time:
                log_dates.append(log_time.date())
    
    # Determine target date for time-only filters
    if log_dates:
        # Use the most recent date from logs
        target_date = max(log_dates)
    else:
        # Fallback to current date
        target_date = datetime.now().date()
    

    
    # Adjust time bounds based on what information they contain
    if from_dt:
        # If only time was specified (no date), use target date
        if from_time and ':' in from_time and not any(c in from_time for c in ['-', '/']):
            from_dt = datetime.combine(target_date, from_dt.time())
        # If partial date (no year), use the year from logs
        elif '%Y' not in (from_time or '') and log_dates:
            from_dt = from_dt.replace(year=target_date.year)
    
    if to_dt:
        # If only time was specified (no date), use target date
        if to_time and ':' in to_time and not any(c in to_time for c in ['-', '/']):
            to_dt = datetime.combine(target_date, to_dt.time())
        # If partial date (no year), use the year from logs
        elif '%Y' not in (to_time or '') and log_dates:
            to_dt = to_dt.replace(year=target_date.year)
    

    
    logs_without_timestamps = 0
    logs_before_range = 0
    logs_after_range = 0
    logs_in_range = 0
    
    for i, line in enumerate(logs):
        # Try to extract timestamp from log line
        log_time = extract_log_timestamp(line)
        

        
        # Only include logs that have timestamps and are within range
        if log_time:
            # Check if log time is within range
            if from_dt and log_time < from_dt:
                logs_before_range += 1
                continue
            if to_dt and log_time > to_dt:
                logs_after_range += 1
                continue
            
            # Log is within time range
            filtered_logs.append(line)
            line_map.append(i)
            logs_in_range += 1
        else:
            logs_without_timestamps += 1
        # Note: logs without timestamps are excluded when time filtering is active
    

    
    return filtered_logs, line_map

def extract_log_timestamp(log_line):
    """Extract timestamp from a log line"""
    # Common timestamp patterns in logs (in order of specificity)
    patterns = [
        # Docker format: 2024-01-01T12:00:00.000000000Z
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6,9}Z?)',
        # ISO 8601 format: 2024-01-01T12:00:00.000Z
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,3}Z?)',
        # ISO 8601 without microseconds: 2024-01-01T12:00:00Z
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)',
        # Standard format: 2024-01-01 12:00:00
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
        # RFC3339 with timezone: 2024-01-01T12:00:00+00:00
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})',
        # Syslog format: Jan 01 12:00:00
        r'([A-Za-z]{3} +\d{1,2} \d{2}:\d{2}:\d{2})',
        # Time only with microseconds: 12:00:00.000
        r'(\d{2}:\d{2}:\d{2}\.\d{1,6})',
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
                '%Y-%m-%dT%H:%M:%S%z',  # RFC3339 with timezone
                '%b %d %H:%M:%S',
                '%H:%M:%S.%f',
                '%H:%M:%S'
            ]
            
            for fmt in formats:
                try:
                    parsed = datetime.strptime(timestamp_str, fmt)
                    
                    # For formats without year, use current year
                    if '%Y' not in fmt:
                        parsed = parsed.replace(year=datetime.now().year)
                    
                    return parsed
                except ValueError:
                    continue
    
    return None

def export_logs_to_file(logs, container_name, export_config, filter_info=None):
    """Export logs to file with metadata"""
    try:
        # Determine export path
        if export_config['type'] == 'current_dir':
            export_dir = os.getcwd()
        else:
            export_dir = export_config['path']
            if not os.path.exists(export_dir):
                os.makedirs(export_dir, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{container_name}_logs_{timestamp}.txt"
        filepath = os.path.join(export_dir, filename)
        
        # Write logs with metadata
        with open(filepath, 'w', encoding='utf-8') as f:
            # Write header with export info
            f.write(f"# Docker Container Logs Export\n")
            f.write(f"# Container: {container_name}\n")
            f.write(f"# Export Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total Lines: {len(logs)}\n")
            
            if filter_info:
                f.write(f"# Filters Applied:\n")
                if filter_info.get('text_filter'):
                    f.write(f"#   Text Filter: {filter_info['text_filter']}\n")
                if filter_info.get('time_filter'):
                    f.write(f"#   Time Filter: {filter_info['time_filter']}\n")
                if filter_info.get('search_term'):
                    f.write(f"#   Search Term: {filter_info['search_term']}\n")
            
            f.write(f"# " + "="*50 + "\n\n")
            
            # Write the actual logs
            for line in logs:
                f.write(line + '\n')
        
        return filepath
    except Exception as e:
        return None

def show_tail_dialog(stdscr, current_tail):
    """Show dialog to change the tail (number of lines) value"""
    h, w = stdscr.getmaxyx()
    
    # Create dialog window
    dialog_width = 50
    dialog_height = 8
    dialog_y = (h - dialog_height) // 2
    dialog_x = (w - dialog_width) // 2
    
    dialog = curses.newwin(dialog_height, dialog_width, dialog_y, dialog_x)
    dialog.keypad(True)
    dialog.border()
    
    # Draw title
    title = " Change Number of Log Lines "
    safe_addstr(dialog, 0, (dialog_width - len(title)) // 2, title)
    
    # Draw instructions
    safe_addstr(dialog, 2, 2, "Enter number of lines to show:")
    safe_addstr(dialog, 3, 2, "(0 = all lines, default = 500)")
    
    # Input field
    input_str = str(current_tail) if current_tail > 0 else ""
    
    curses.curs_set(1)  # Show cursor
    
    while True:
        # Clear input line
        safe_addstr(dialog, 4, 2, " " * (dialog_width - 4))
        safe_addstr(dialog, 4, 2, input_str)
        
        # Position cursor
        dialog.move(4, 2 + len(input_str))
        dialog.refresh()
        
        ch = dialog.getch()
        
        if ch == 27:  # ESC - cancel
            curses.curs_set(0)
            return current_tail
        elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            if input_str:
                input_str = input_str[:-1]
        elif ch == 10:  # Enter - confirm
            try:
                new_tail = int(input_str) if input_str else 500
                if new_tail < 0:
                    new_tail = 0
                curses.curs_set(0)
                return new_tail
            except ValueError:
                # Invalid input - show error
                safe_addstr(dialog, 5, 2, "Invalid number! Please try again.", 
                           curses.color_pair(4))
                dialog.refresh()
                time.sleep(1)
                safe_addstr(dialog, 5, 2, " " * (dialog_width - 4))
        elif ch >= ord('0') and ch <= ord('9'):
            if len(input_str) < 6:  # Limit to 6 digits
                input_str += chr(ch)
    
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
        
        # Initialize tail value (default 500)
        tail_lines = getattr(tui, 'log_tail_lines', 500)
        
        # Fetch initial logs
        if tail_lines == 0:
            raw_logs = container.logs().decode(errors='ignore').splitlines()
        else:
            raw_logs = container.logs(tail=tail_lines).decode(errors='ignore').splitlines()
        
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
        
        # Time filter state
        time_filter_active = False
        time_filter_from = None
        time_filter_to = None
        time_filtered_logs = []
        time_filtered_line_map = []
        
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
        
        # ADDED: Maximum logs to keep in memory
        MAX_LOG_LINES = 25000  # Reduced to prevent memory issues and crashes
        LOG_CLEANUP_INTERVAL = 100  # Clean up every 100 new lines
        new_lines_since_cleanup = 0
        
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
        tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
        stdscr.attroff(curses.color_pair(5))
        
        # Draw footer with help
        if filtering_active or time_filter_active:
            if tui.wrap_log_lines:
                footer_text = " ↑/↓:Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
            else:
                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
        elif tui.wrap_log_lines:
            footer_text = " ↑/↓:Scroll | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | T:Tail | R:Time | E:Export | /:Search | \\:Filter | ESC:Back "
        else:
            footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | T:Tail | R:Time | E:Export | /:Search | \\:Filter | ESC:Back "
        
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
            
            # Update logs in follow mode (but not when time filtering is active)
            if follow_mode and not time_filter_active and current_time - last_log_time >= log_update_interval:
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
                            
                            # ADDED: Cleanup old logs if we exceed the limit
                            new_lines_since_cleanup += len(truly_new_logs)
                            
                            if new_lines_since_cleanup >= LOG_CLEANUP_INTERVAL:
                                new_lines_since_cleanup = 0
                                
                                # Trim all_raw_logs if too large
                                if len(all_raw_logs) > MAX_LOG_LINES:
                                    excess = len(all_raw_logs) - MAX_LOG_LINES
                                    all_raw_logs = all_raw_logs[excess:]
                                    
                                # Trim original_logs if too large
                                if len(original_logs) > MAX_LOG_LINES:
                                    excess = len(original_logs) - MAX_LOG_LINES
                                    original_logs = original_logs[excess:]
                                    
                                    # If filtering is active, reapply filters to trimmed logs
                                    if filtering_active or time_filter_active:
                                        # Start with original logs
                                        filtered_logs = original_logs
                                        
                                        # Apply time filter first if active
                                        if time_filter_active:
                                            filtered_logs, _ = filter_logs_by_time(filtered_logs, time_filter_from, time_filter_to)
                                        
                                        # Then apply text filter if active
                                        if filtering_active:
                                            filtered_logs, filtered_line_map = filter_logs(filtered_logs, filter_string, case_sensitive)
                                        
                                        logs = filtered_logs
                                    else:
                                        logs = original_logs
                                        
                                    # Rebuild pad with trimmed logs
                                    pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                                    pad = pad_info['pad']
                                    line_positions = pad_info['line_positions']
                                    actual_lines_count = pad_info['actual_lines']
                                    
                                    # Adjust position if needed
                                    if pos > actual_lines_count - (h-4):
                                        pos = max(0, actual_lines_count - (h-4))
                            
                            # If filtering is active, apply filters to new logs
                            if filtering_active or time_filter_active:
                                # Start with original logs
                                filtered_logs = original_logs
                                
                                # Apply time filter first if active
                                if time_filter_active:
                                    filtered_logs, _ = filter_logs_by_time(filtered_logs, time_filter_from, time_filter_to)
                                
                                # Then apply text filter if active
                                if filtering_active:
                                    filtered_logs, filtered_line_map = filter_logs(filtered_logs, filter_string, case_sensitive)
                                
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
                            next_match = next_search_match(search_matches, current_match - 1, line_positions, tui.wrap_log_lines, w)
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
                            tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
                            safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                            stdscr.attroff(curses.color_pair(5))
                            
                            # Restore normal footer
                            if filtering_active or time_filter_active:
                                if tui.wrap_log_lines:
                                    footer_text = " ↑/↓:Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                                else:
                                    footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                            elif tui.wrap_log_lines:
                                footer_text = " ↑/↓:Scroll | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | T:Tail | R:Time | E:Export | /:Search | \\:Filter | ESC:Back "
                            else:
                                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | T:Tail | R:Time | E:Export | /:Search | \\:Filter | ESC:Back "
                            
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
                help_text = "Syntax: term AND/OR term, (term OR term), +include -exclude \"multi word\" | Tab:Case"
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
                        tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
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
                            tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator
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
                    tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                    header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
                    safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                    stdscr.attroff(curses.color_pair(5))
                    
                    # Update footer if filtering is active
                    if filtering_active or time_filter_active:
                        if tui.wrap_log_lines:
                            footer_text = " ↑/↓:Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                        else:
                            footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                        
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
                    
                    # Show the actual filter expression
                    empty_msg1 = "No logs matching filter:"
                    empty_msg2 = filter_string
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
                        tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
                        safe_addstr(stdscr, 0, (w-len(header_text))//2, header_text, curses.color_pair(5) | curses.A_BOLD)
                        stdscr.attroff(curses.color_pair(5))
                        
                        # Update footer based on filter state
                        if filtering_active or time_filter_active:
                            if tui.wrap_log_lines:
                                footer_text = " ↑/↓:Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                            else:
                                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                            
                            stdscr.attron(curses.color_pair(6))
                            safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                            stdscr.attroff(curses.color_pair(6))
                        
                        stdscr.refresh()
                    elif ch in (ord('t'), ord('T')):  # Change tail lines
                        new_tail = show_tail_dialog(stdscr, tail_lines)
                        if new_tail != tail_lines:
                            tail_lines = new_tail
                            tui.log_tail_lines = tail_lines  # Store in TUI state
                            
                            # Reload logs with new tail value
                            stdscr.clear()
                            safe_addstr(stdscr, h//2, (w-25)//2, "Reloading logs, please wait...", curses.A_BOLD)
                            stdscr.refresh()
                            
                            # Fetch logs with new tail value
                            if tail_lines == 0:
                                raw_logs = container.logs().decode(errors='ignore').splitlines()
                            else:
                                raw_logs = container.logs(tail=tail_lines).decode(errors='ignore').splitlines()
                            
                            # Reset everything
                            all_raw_logs = raw_logs.copy()
                            logs = normalize_container_logs(tui.normalize_logs, tui.normalize_logs_script, raw_logs) if tui.normalize_logs else raw_logs
                            original_logs = logs.copy()
                            
                            # Apply filters if active
                            if filtering_active or time_filter_active:
                                # Start with original logs
                                filtered_logs = original_logs
                                
                                # Apply time filter first if active
                                if time_filter_active:
                                    filtered_logs, _ = filter_logs_by_time(filtered_logs, time_filter_from, time_filter_to)
                                
                                # Then apply text filter if active
                                if filtering_active:
                                    filtered_logs, filtered_line_map = filter_logs(filtered_logs, filter_string, case_sensitive)
                                
                                logs = filtered_logs
                            
                            # Rebuild pad
                            pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                            pad = pad_info['pad']
                            line_positions = pad_info['line_positions']
                            actual_lines_count = pad_info['actual_lines']
                            
                            # Update line count
                            last_logical_lines_count = len(logs)
                            last_log_line = logs[-1] if logs else ""
                            last_log_count = len(logs)
                            
                            # Reapply search if needed
                            if search_string:
                                search_result = search_and_highlight(pad, logs, search_string, line_positions, w, case_sensitive, pos)
                                search_matches = search_result['matches']
                                current_match = search_result['current_match']
                                highlight_search_matches(pad, line_positions, tui.wrap_log_lines, w, search_matches, current_match)
                            
                            # Go to end if in follow mode
                            if follow_mode:
                                pos = max(0, actual_lines_count - (h-4))
                            else:
                                pos = 0
                            
                            # Force redraw
                            stdscr.clear()
                            last_display_time = 0
                    elif ch in (ord('r'), ord('R')):  # Time range filter
                        time_filter_config = show_time_filter_dialog(stdscr)
                        if time_filter_config:
                            time_filter_from = time_filter_config['from']
                            time_filter_to = time_filter_config['to']
                            
                            if time_filter_from or time_filter_to:
                                # Show loading message
                                stdscr.clear()
                                safe_addstr(stdscr, h//2, (w-30)//2, "Applying time filter, please wait...", curses.A_BOLD)
                                stdscr.refresh()
                                
                                # Convert user input to Docker time format
                                docker_since = convert_to_docker_time_format(time_filter_from)
                                docker_until = convert_to_docker_time_format(time_filter_to)
                                

                                
                                # Use Docker's native time filtering
                                try:
                                    # IMPORTANT: Ignore tail when time filtering - fetch ALL logs in time range
                                    # Note: fetch_logs_with_time_filter has built-in safety limits to prevent crashes
                                    raw_logs = fetch_logs_with_time_filter(
                                        container, 
                                        since=docker_since, 
                                        until=docker_until,
                                        tail=None  # NO TAIL LIMIT when time filtering (but function applies safety limits)
                                    )
                                    
                                    # Store raw logs for reference
                                    all_raw_logs = raw_logs.copy()
                                    
                                    # Process logs through normalize_logs.py if needed
                                    logs = normalize_container_logs(tui.normalize_logs, tui.normalize_logs_script, raw_logs) if tui.normalize_logs else raw_logs
                                    original_logs = logs.copy()  # These are now the time-filtered logs
                                    time_filter_active = True
                                    
                                    # Show warning if logs were truncated for safety
                                    if len(raw_logs) == 20000:  # This indicates truncation occurred
                                        truncation_msg = "Warning: Large log set truncated to 20,000 most recent entries for performance"
                                        safe_addstr(stdscr, h//2+1, (w-len(truncation_msg))//2, truncation_msg, curses.color_pair(3))
                                        stdscr.refresh()
                                        time.sleep(2)
                                    
                                    # Apply text filtering if it was active before
                                    if filtering_active:
                                        filtered_logs, filtered_line_map = filter_logs(logs, filter_string, case_sensitive)
                                        logs = filtered_logs
                                    
                                except Exception as e:
                                    # Fallback to Python filtering if Docker filtering fails
                                    time_filtered_logs, time_filtered_line_map = filter_logs_by_time(
                                        original_logs, time_filter_from, time_filter_to
                                    )
                                    time_filter_active = True
                                    
                                    # If text filtering is also active, apply it to time-filtered logs
                                    if filtering_active:
                                        filtered_logs, filtered_line_map = filter_logs(
                                            time_filtered_logs, filter_string, case_sensitive
                                        )
                                        logs = filtered_logs
                                    else:
                                        logs = time_filtered_logs
                                
                                # Rebuild pad
                                pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                                pad = pad_info['pad']
                                line_positions = pad_info['line_positions']
                                actual_lines_count = pad_info['actual_lines']
                                
                                # Update line count
                                last_logical_lines_count = len(logs)
                                
                                # Go to start of filtered logs
                                pos = 0
                                follow_mode = False  # Disable follow mode when time filtering
                                
                                # Show filtering results temporarily
                                if filtering_active:
                                    filter_info = f"Time filter: {len(original_logs)} logs fetched, {len(logs)} after text filter"
                                else:
                                    filter_info = f"Time filter applied: {len(logs)} logs fetched"
                                stdscr.clear()
                                safe_addstr(stdscr, h//2, (w-len(filter_info))//2, filter_info, curses.A_BOLD)
                                stdscr.refresh()
                                time.sleep(1.5)  # Show for 1.5 seconds
                                
                                # Force redraw
                                stdscr.clear()
                                last_display_time = 0
                            else:
                                # Clear time filter - need to reload full logs
                                time_filter_active = False
                                time_filter_from = None
                                time_filter_to = None
                                
                                # Show loading message
                                stdscr.clear()
                                safe_addstr(stdscr, h//2, (w-25)//2, "Reloading full logs...", curses.A_BOLD)
                                stdscr.refresh()
                                
                                # Reload all logs
                                if tail_lines == 0:
                                    raw_logs = container.logs().decode(errors='ignore').splitlines()
                                else:
                                    raw_logs = container.logs(tail=tail_lines).decode(errors='ignore').splitlines()
                                
                                # Process logs
                                logs = normalize_container_logs(tui.normalize_logs, tui.normalize_logs_script, raw_logs) if tui.normalize_logs else raw_logs
                                original_logs = logs.copy()
                                
                                # Apply text filtering if active
                                if filtering_active:
                                    filtered_logs, filtered_line_map = filter_logs(
                                        original_logs, filter_string, case_sensitive
                                    )
                                    logs = filtered_logs
                                
                                # Rebuild pad
                                pad_info = rebuild_log_pad(logs, w, h, tui.wrap_log_lines)
                                pad = pad_info['pad']
                                line_positions = pad_info['line_positions']
                                actual_lines_count = pad_info['actual_lines']
                                
                                last_logical_lines_count = len(logs)
                                stdscr.clear()
                                last_display_time = 0
                    elif ch in (ord('e'), ord('E')):  # Export logs
                        export_config = show_export_dialog(stdscr)
                        if export_config:
                            # Prepare filter info for export metadata
                            filter_info = {}
                            if filtering_active:
                                filter_info['text_filter'] = filter_string
                            if time_filter_active:
                                time_range = ""
                                if time_filter_from:
                                    time_range += f"from {time_filter_from}"
                                if time_filter_to:
                                    if time_range:
                                        time_range += f" to {time_filter_to}"
                                    else:
                                        time_range = f"until {time_filter_to}"
                                if not time_range:
                                    time_range = "all time"
                                filter_info['time_filter'] = time_range
                            if search_string:
                                filter_info['search_term'] = search_string
                            
                            # Export current filtered logs
                            filepath = export_logs_to_file(
                                logs, container.name, export_config, 
                                filter_info if filter_info else None
                            )
                            
                            if filepath:
                                # Show success message
                                success_msg = f"Logs exported to: {filepath}"
                                safe_addstr(stdscr, h-2, (w-len(success_msg))//2, success_msg, curses.A_BOLD)
                                stdscr.refresh()
                                time.sleep(2)
                            else:
                                # Show error message
                                error_msg = "Export failed!"
                                safe_addstr(stdscr, h-2, (w-len(error_msg))//2, error_msg, curses.color_pair(4))
                                stdscr.refresh()
                                time.sleep(2)
                            
                            # Clear message
                            safe_addstr(stdscr, h-2, 0, " " * w)
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
                                
                                # If filtering is active, apply filters to normalized logs
                                if filtering_active or time_filter_active:
                                    # Start with original logs
                                    filtered_logs = original_logs
                                    
                                    # Apply time filter first if active
                                    if time_filter_active:
                                        filtered_logs, _ = filter_logs_by_time(filtered_logs, time_filter_from, time_filter_to)
                                    
                                    # Then apply text filter if active
                                    if filtering_active:
                                        filtered_logs, filtered_line_map = filter_logs(filtered_logs, filter_string, case_sensitive)
                                    
                                    logs = filtered_logs
                                else:
                                    logs = original_logs
                            else:
                                # Use raw logs
                                original_logs = all_raw_logs.copy()
                                
                                # If filtering is active, apply filters to raw logs
                                if filtering_active or time_filter_active:
                                    # Start with original logs
                                    filtered_logs = original_logs
                                    
                                    # Apply time filter first if active
                                    if time_filter_active:
                                        filtered_logs, _ = filter_logs_by_time(filtered_logs, time_filter_from, time_filter_to)
                                    
                                    # Then apply text filter if active
                                    if filtering_active:
                                        filtered_logs, filtered_line_map = filter_logs(filtered_logs, filter_string, case_sensitive)
                                    
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
                            tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
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
                        if filtering_active or time_filter_active:
                            if tui.wrap_log_lines:
                                footer_text = " ↑/↓:Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                            else:
                                footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | F:Follow | R:Time | E:Export | /:Search | \\:Filter | ESC:Clear | Q:Back "
                        elif tui.wrap_log_lines:
                            footer_text = " ↑/↓:Scroll | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | T:Tail | R:Time | E:Export | /:Search | \\:Filter | ESC:Back "
                        else:
                            footer_text = " ↑/↓:Scroll | ←/→:H-Scroll | PgUp/Dn | F:Follow | N:Normalize | W:Wrap | T:Tail | R:Time | E:Export | /:Search | \\:Filter | ESC:Back "
                        
                        stdscr.attron(curses.color_pair(6))
                        safe_addstr(stdscr, h-1, 0, footer_text + " " * (w - len(footer_text)), curses.color_pair(6))
                        stdscr.attroff(curses.color_pair(6))
                        
                        # Update header immediately to reflect changed wrapping mode
                        stdscr.attron(curses.color_pair(5))
                        normalized_indicator = " [NORMALIZED]" if tui.normalize_logs else " [RAW]"
                        wrap_indicator = " [WRAP]" if tui.wrap_log_lines else " [NOWRAP]"
                        search_indicator = f" [SEARCH: {search_string}]" if search_string else ""
                        filter_indicator = f" [FILTER: {filter_string}]" if filtering_active else ""
                        tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                        header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator + filter_indicator
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
                        help_text = "Syntax: term AND/OR term, (term OR term), +include -exclude \"multi word\" | Tab:Case"
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
                        # If filtering is active and ESC is pressed, clear the filters first
                        if ch == 27 and (filtering_active or time_filter_active):
                            filtering_active = False
                            time_filter_active = False
                            filter_string = ""
                            time_filter_from = None
                            time_filter_to = None
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
                            tail_indicator = f" [TAIL: {tail_lines if tail_lines > 0 else 'ALL'}]"
                            header_text = f" Logs: {container.name} " + (" [FOLLOW]" if follow_mode else " [STATIC]") + normalized_indicator + wrap_indicator + tail_indicator + search_indicator
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
        error_msg = str(e)
        if len(error_msg) > w - 20:
            error_msg = error_msg[:w-23] + "..."
        safe_addstr(stdscr, h//2, (w-len(error_msg)-10)//2, f"Error: {error_msg}", curses.A_BOLD)
        safe_addstr(stdscr, h//2+1, (w-25)//2, "Press any key to continue...", curses.A_DIM)
        
        # If the error is memory-related, show additional help
        if "memory" in error_msg.lower() or "alloc" in error_msg.lower():
            help_msg = "Try using time filters or reducing log count"
            safe_addstr(stdscr, h//2+2, (w-len(help_msg))//2, help_msg, curses.A_DIM)
        
        stdscr.refresh()
        stdscr.getch()
    
    finally:
        # Restore screen state
        stdscr.clear()
        stdscr.nodelay(True)  # Restore non-blocking mode
        stdscr.refresh()
