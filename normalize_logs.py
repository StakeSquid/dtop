#!/usr/bin/env python3
import sys
import json
import datetime
import shlex
import re

# Regex to match ANSI escape sequences and strip color codes
ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

def strip_ansi(s):
    """
    Remove any ANSI escape sequences (color codes) from the string.
    """
    return ANSI_ESCAPE.sub('', s)

# Preferred order for extra fields in various log types
GLOBAL_PREFERRED_KEYS = [
    "component", "hostname", "name", "pid",
    "indexer", "operator", "protocolNetwork",
    "filter", "deployment", "function", "publishedSubgraphs"
]
WALRUS_PREFERRED_KEYS = ["target", "filename", "line_number"]


def format_timestamp(ts):
    """
    Convert ISO8601 timestamp (with trailing Z) to MM-DD|HH:MM:SS.mmm
    """
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", ""))
        return dt.strftime("%m-%d|%H:%M:%S.%f")[:-3]
    except Exception:
        return ts


def format_timestamp_t(ts):
    """
    Convert t= style timestamps (e.g. '2025-03-26T12:06:31+0000') to MM-DD|HH:MM:SS.mmm
    """
    try:
        if len(ts) >= 5 and (ts[-5] in ['+', '-'] and ts[-3] != ':'):
            ts = ts[:-2] + ':' + ts[-2:]
        dt = datetime.datetime.fromisoformat(ts)
        return dt.strftime("%m-%d|%H:%M:%S.%f")[:-3]
    except Exception:
        return ts


def format_number(num):
    """Format integer or numeric string with commas."""
    try:
        return f"{int(num):,}"
    except Exception:
        return num


def shorten_hash(h):
    """Shorten a hash by keeping first 6 and last 5 characters."""
    if isinstance(h, str) and len(h) > 12:
        return f"{h[:6]}..{h[-5:]}"
    return h


def format_extra_fields(extra, skip_keys, preferred_keys=None):
    """
    Format extra fields in a preferred order, omitting skip_keys.
    """
    items = {}
    for key, value in extra.items():
        if key in skip_keys:
            continue
        # Format numbers
        try:
            int_value = int(value)
            value = format_number(int_value)
        except Exception:
            pass
        # Compact JSON for dicts
        if isinstance(value, dict):
            value = json.dumps(value, separators=(',', ':'))
        items[key] = value

    parts = []
    if preferred_keys:
        for key in preferred_keys:
            if key in items:
                parts.append(f"{key}={items.pop(key)}")
    for key in sorted(items.keys()):
        parts.append(f"{key}={items[key]}")
    return " ".join(parts)


def process_json_line(obj):
    """
    Geth-style JSON logs with severity, timestamp, and message.
    """
    severity = obj.get("severity", "INFO").upper()
    timestamp = format_timestamp(obj.get("timestamp", ""))
    message = obj.get("message", "")
    line = f"{severity} [{timestamp}] {message}"
    skip = {"severity", "timestamp", "message", "logger", "logging.googleapis.com/labels"}
    extra = {}
    # Block info
    if "block_number" in obj:
        extra["number"] = format_number(obj["block_number"])
    if "block_Id" in obj:
        extra["hash"] = shorten_hash(obj["block_Id"])
    # Other fields
    for key, value in obj.items():
        if key in skip or key in {"block_number", "block_Id"}:
            continue
        extra[key] = value
    extra_str = format_extra_fields(extra, set(), GLOBAL_PREFERRED_KEYS)
    if extra_str:
        line += " " + extra_str
    return line


def process_alt_json_line(obj):
    """
    IndexerAgent-style JSON with numeric level, epoch ms time, and msg.
    """
    level_map = {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR", 50: "CRITICAL"}
    try:
        level = int(obj.get("level", 20))
    except Exception:
        level = 20
    severity = level_map.get(level, str(level))
    try:
        ts = float(obj.get("time", 0)) / 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        timestamp = dt.strftime("%m-%d|%H:%M:%S.%f")[:-3]
    except Exception:
        timestamp = str(obj.get("time", ""))
    message = obj.get("msg", "")
    line = f"{severity} [{timestamp}] {message}"
    skip = {"level", "time", "msg"}
    extra = {}
    for key, value in obj.items():
        if key in skip:
            continue
        extra[key] = value
    extra_str = format_extra_fields(extra, set(), GLOBAL_PREFERRED_KEYS)
    if extra_str:
        line += " " + extra_str
    return line


def process_kv_line(line):
    """
    Key=value style logs (t=, lvl=, msg=, etc.).
    """
    try:
        tokens = shlex.split(line)
    except Exception:
        return line
    kv = {}
    for token in tokens:
        if '=' not in token:
            continue
        key, value = token.split('=', 1)
        kv[key] = value
    ts = kv.get('t', '')
    timestamp = format_timestamp_t(ts)
    severity = kv.get('lvl', 'INFO').upper()
    message = kv.get('msg', '')
    line_out = f"{severity} [{timestamp}] {message}"
    extra = {}
    if 'id' in kv and ':' in kv['id']:
        hash_part, num_part = kv['id'].split(':', 1)
        extra['hash'] = shorten_hash(hash_part)
        extra['number'] = format_number(num_part)
        kv.pop('id')
    else:
        if 'hash' in kv:
            extra['hash'] = shorten_hash(kv.pop('hash'))
        if 'number' in kv:
            extra['number'] = format_number(kv.pop('number'))
    for key, value in kv.items():
        if key in {'t','lvl','msg'}:
            continue
        extra[key] = value
    extra_str = format_extra_fields(extra, set(), GLOBAL_PREFERRED_KEYS)
    if extra_str:
        line_out += " " + extra_str
    return line_out


def process_walrus_line(obj):
    """
    Walrus-style logs with nested fields object.
    """
    level = obj.get('level', 'INFO').upper()
    timestamp = format_timestamp(obj.get('timestamp', ''))
    fields = obj.get('fields', {})
    message = fields.get('message', '')
    line = f"{level} [{timestamp}] {message}"
    extra = {k: v for k, v in fields.items() if k != 'message'}
    for key in WALRUS_PREFERRED_KEYS:
        if key in obj:
            extra[key] = obj[key]
    extra_str = format_extra_fields(extra, set(), WALRUS_PREFERRED_KEYS)
    if extra_str:
        line += " " + extra_str
    return line


def main():
    for line in sys.stdin:
        # Strip ANSI color codes and newline
        line = strip_ansi(line.rstrip('\n'))
        try:
            obj = json.loads(line)
            if 'fields' in obj and isinstance(obj['fields'], dict):
                print(process_walrus_line(obj))
            elif 'level' in obj and 'time' in obj:
                print(process_alt_json_line(obj))
            elif 'severity' in obj and 'timestamp' in obj:
                print(process_json_line(obj))
            else:
                print(line)
            continue
        except json.JSONDecodeError:
            pass
        if line.startswith('t=') or line.startswith('lvl='):
            print(process_kv_line(line))
            continue
        # Already formatted plain text
        print(line)

if __name__ == '__main__':
    main()
