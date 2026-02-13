# dtop - Docker Terminal UI

[![PyPI version](https://badge.fury.io/py/dtop.svg)](https://badge.fury.io/py/dtop)
[![Python versions](https://img.shields.io/pypi/pyversions/dtop.svg)](https://pypi.org/project/dtop/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A terminal UI for managing and monitoring Docker containers. Real-time stats, advanced log viewing, container lifecycle control, and full keyboard-driven workflow.

<img width="2214" height="646" alt="image" src="https://github.com/user-attachments/assets/e468135e-4c6e-483d-a282-907db088ae77" />
<img width="2213" height="822" alt="image" src="https://github.com/user-attachments/assets/e2dbe385-6922-4bb7-b896-6679e703549d" />
<img width="770" height="164" alt="image" src="https://github.com/user-attachments/assets/ada5da1f-9888-4408-a621-e0088980f2c1" />
<img width="1149" height="361" alt="image" src="https://github.com/user-attachments/assets/8ac930d5-a5a8-47af-9e9e-b25fb2e5058d" />
<img width="2211" height="951" alt="image" src="https://github.com/user-attachments/assets/29c3ff81-fa1d-484c-9fc2-5288e04b2020" />


## Features

- **Real-time stats** — CPU, memory, network I/O, and disk I/O with parallel streaming collection
- **Container control** — Start, stop, pause, restart, exec shell, remove, and recreate (with docker-compose support)
- **Advanced log viewer** — Search, filter (AND/OR/NOT expressions), follow mode, time-range filtering, normalization, and export
- **Container inspector** — Tree and JSON views with search, expand/collapse, and path/value copy
- **Keyboard-first** — Every action has a shortcut; mouse is fully supported too
- **Customizable columns** — Adjust widths, set min/max, reorder via config or the built-in editor
- **Dark/light themes** — Toggle with a single key
- **Responsive layout** — Columns auto-size to terminal width based on weight
- **Persistent config** — Column settings saved to `~/.docker_tui.json`
- **Legacy mode** — Falls back to a curses interface with `--legacy`

## Installation

**Requirements:** Python 3.8+, Docker daemon running, access to `/var/run/docker.sock`

```bash
# PyPI (recommended)
pip install dtop

# Latest from GitHub
pip install git+https://github.com/StakeSquid/dtop.git

# Quick install script
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/StakeSquid/dtop/main/scripts/install.sh)"

# Development
git clone https://github.com/StakeSquid/dtop && cd dtop && pip install -e .
```

### Upgrading

If you have a previous version installed, make sure to upgrade:

```bash
pip install --upgrade dtop
```

## Usage

```bash
dtop              # Textual UI (default)
dtop --legacy     # Curses interface
dtop --debug      # Debug mode with full tracebacks
```

## Keyboard Shortcuts

### Main View

| Key | Action |
|-----|--------|
| `Enter` | Open actions menu for selected container |
| `L` | View logs |
| `I` | Inspect container |
| `S` | Stop / Start (toggle) |
| `P` | Pause / Unpause (toggle) |
| `R` | Restart |
| `E` | Exec shell |
| `F` | Recreate |
| `/` | Search containers |
| `\` | Filter containers |
| `N` | Next search match |
| `Escape` | Clear search/filter |
| `C` | Column settings |
| `D` | Toggle dark/light theme |
| `?` | Help |
| `Q` | Quit |

Click any column header to sort. Click again to reverse.

### Container Actions Menu

When the modal is open, press any shortcut key directly:

| Key | Action |
|-----|--------|
| `L` | View logs |
| `I` | Inspect |
| `S` | Stop / Start |
| `P` | Pause / Unpause |
| `R` | Restart |
| `E` | Exec shell |
| `F` | Recreate |
| `Escape` / `Q` | Close menu |

### Log Viewer

| Key | Action |
|-----|--------|
| `F` | Toggle follow mode (auto-scroll) |
| `/` | Search |
| `\` | Filter (supports AND/OR/NOT expressions) |
| `N` / `P` | Next / previous match |
| `S` | Toggle case-sensitive search |
| `Shift+N` | Toggle log normalization |
| `W` | Toggle line wrapping |
| `T` | Set tail line count |
| `Shift+T` | Toggle Docker timestamps |
| `R` | Time-range filter |
| `E` | Export logs to file |
| `G` / `Shift+G` | Jump to top / bottom |
| `C` | Clear log display |
| `Escape` | Back (clears active filter first) |

### Inspector

| Key | Action |
|-----|--------|
| `/` | Search keys and values |
| `\` | Filter |
| `N` / `P` | Next / previous match |
| `C` | Copy current match path |
| `V` | Copy current match value |
| `E` / `Shift+E` | Expand / collapse all |
| `J` | JSON view |
| `T` | Tree view |
| `Escape` | Back |

## Log Filter Syntax

The log viewer supports complex filter expressions:

```
error                        # lines containing "error"
+error                       # explicit include
-error  or  !error           # exclude
"exact phrase"               # quoted multi-word term
error AND warning            # both terms required
error OR warning             # either term
(error OR warning) AND -debug  # grouped with exclusion
```

## Configuration

Settings are stored in `~/.docker_tui.json`. Press `C` in the main view to open the column editor.

Each column has: `name`, `width`, `min_width`, `max_width`, `weight`, and `align`.

```json
{
  "columns": [
    { "name": "NAME",    "width": 25, "min_width": 15, "max_width": null, "weight": 3, "align": "left" },
    { "name": "IMAGE",   "width": 30, "min_width": 15, "max_width": 50,   "weight": 2, "align": "left" },
    { "name": "STATUS",  "width": 12, "min_width": 8,  "max_width": 20,   "weight": 1, "align": "left" },
    { "name": "CPU%",    "width": 8,  "min_width": 7,  "max_width": 10,   "weight": 0, "align": "right" },
    { "name": "MEM%",    "width": 8,  "min_width": 7,  "max_width": 10,   "weight": 0, "align": "right" },
    { "name": "NET I/O", "width": 20, "min_width": 16, "max_width": 26,   "weight": 0, "align": "right" },
    { "name": "DISK I/O","width": 20, "min_width": 16, "max_width": 26,   "weight": 0, "align": "right" },
    { "name": "CREATED AT","width": 21,"min_width": 19, "max_width": 30,   "weight": 0, "align": "left" },
    { "name": "UPTIME",  "width": 12, "min_width": 8,  "max_width": 16,   "weight": 0, "align": "right" }
  ]
}
```

Columns with a higher `weight` expand first when the terminal is wide. Columns with `weight: 0` stay at their minimum unless extra space allows growth.

## Troubleshooting

```bash
# Docker not connecting
sudo systemctl status docker
ls -la /var/run/docker.sock
sudo usermod -aG docker $USER   # then logout/login

# Terminal not restoring after exit
reset

# Textual UI issues — fall back to curses
dtop --legacy
```

---

## Detailed Documentation

### Container Recreate

The recreate feature supports two modes:

**Docker-Compose mode** — Automatically detects compose metadata from container labels (`com.docker.compose.project`, `com.docker.compose.service`, `com.docker.compose.project.working_dir`). Opens a file browser to select or confirm the compose file, then runs `docker compose up -d --force-recreate --no-deps <service>`.

**Simple mode** — For standalone containers without compose. Extracts the full container config (image, env vars, volumes, ports, network mode, restart policy, user, working directory, entrypoint) and recreates with identical settings.

### Stats Collection

Stats are collected via the Docker API using streaming mode (primary) with polling fallback. Up to 30 concurrent connections are maintained. Streams auto-refresh every 60 seconds and reconnect up to 3 times on failure. Stale data is cleaned up after 5 minutes. Rates (network, disk) are calculated from deltas between samples.

### Status Colors

| Status | Color |
|--------|-------|
| Running | Green |
| Exited / Stopped | Red |
| Paused | Yellow |

### Log Viewer Status Bar

The log header shows compact indicators:

- `N:Y/N` — Normalization on/off
- `W:Y/N` — Wrap on/off
- `F:ON/OFF` — Follow mode
- `L:nnn` — Total raw log lines
- `T:nnn` — Tail limit
- `F:nnn` — Filtered line count
- `M:x/y` — Search match position
- `[CS]` — Case-sensitive search active
- `[TIME]` — Time filter active

### Log Export

Press `E` in the log viewer to export. The output file includes a metadata header (container name, export timestamp, active filters, total lines) followed by the log content. Files are saved as `<container>_logs_<timestamp>.txt`.

### Project Structure

```
dtop/
├── dtop/
│   ├── __main__.py                # Package entry point
│   ├── main.py                    # CLI entry point (--legacy, --debug)
│   ├── core/
│   │   ├── textual_docker_tui.py  # Main Textual UI, table, modals, footer
│   │   ├── textual_stats.py       # Async stats streaming/polling
│   │   ├── docker_tui.py          # Legacy curses interface
│   │   └── stats.py               # Legacy stats collection
│   ├── views/
│   │   ├── textual_log_view.py    # Log viewer (search, filter, follow, export)
│   │   ├── textual_inspect_view.py # Container inspector (tree + JSON)
│   │   ├── log_view.py            # Legacy log viewer
│   │   └── inspect_view.py        # Legacy inspector
│   ├── actions/
│   │   └── container_actions.py   # Legacy container operations
│   └── utils/
│       ├── config.py              # Column config load/save
│       ├── utils.py               # Formatting helpers
│       └── normalize_logs.py      # Log normalization script
├── scripts/
│   ├── install.sh
│   └── uninstall.sh
├── pyproject.toml
└── requirements.txt
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `docker` | >= 6.0.0 | Docker SDK |
| `textual` | >= 0.47.0 | TUI framework |
| `rich` | >= 13.0.0 | Terminal formatting |
| `aiohttp` | >= 3.8.0 | Async stats collection |

## License

MIT — see [LICENSE](LICENSE).

## Author

[StakeSquid](https://github.com/StakeSquid)
