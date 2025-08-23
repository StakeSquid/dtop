# dtop v2 - Docker Terminal UI

[![PyPI version](https://badge.fury.io/py/dtop.svg)](https://badge.fury.io/py/dtop)
[![Python versions](https://img.shields.io/pypi/pyversions/dtop.svg)](https://pypi.org/project/dtop/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A high-performance terminal UI for Docker container management, built with Python and the Textual framework. Features real-time monitoring, advanced log viewing, and comprehensive container operations.

<img width="1611" alt="Screenshot 2025-05-24 at 6 39 12 PM" src="https://github.com/user-attachments/assets/e5697f99-fdd4-4d41-bd69-02072db5385c" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 39 21 PM" src="https://github.com/user-attachments/assets/0694304e-f256-47b5-923b-5c05ed0035b7" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 39 48 PM" src="https://github.com/user-attachments/assets/df379064-9f33-48f7-9e8b-635723df6572" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 40 01 PM" src="https://github.com/user-attachments/assets/aeb20e8e-202c-49f8-bd09-7b563964bb9e" />

## Features

### Core Functionality
- **Real-time Monitoring** - Live CPU, memory, network, and disk I/O statistics with parallel collection
- **Container Management** - Complete lifecycle control (start, stop, pause, restart, remove, recreate)
- **Dual Interface Modes** - Modern Textual UI (default) or legacy curses interface
- **Responsive UI** - Automatically adjusts column widths to terminal size with configurable min/max constraints

### Advanced Log Viewer
- **Powerful Search** - Real-time search with regex support and match highlighting
- **Complex Filtering** - Advanced filter expressions with AND/OR/NOT operators and parentheses
- **Log Normalization** - Automatic parsing and standardization of log formats
- **Time-based Filtering** - Filter logs by date/time range
- **Export Functionality** - Save filtered logs with metadata
- **Syntax Highlighting** - Color-coded log levels (ERROR, WARN, INFO, DEBUG)
- **Follow Mode** - Auto-scroll to new log entries
- **Tail Control** - Configurable number of lines to display

### Container Inspection
- **Tree View** - Hierarchical display of container configuration
- **JSON View** - Formatted JSON with syntax highlighting
- **Search** - Find keys and values in container metadata
- **Navigation** - Expand/collapse tree nodes, jump between matches

### UI Features
- **Customizable Columns** - Adjust min/max widths for each column (shortcut: C)
- **Sortable Columns** - Click headers or use keyboard to sort by any field
- **Container Filtering** - Real-time filtering by name, image, status, or ID
- **Dark/Light Theme** - Toggle between themes (shortcut: D)
- **Auto-refresh** - Configurable automatic refresh with toggle control
- **Persistent Configuration** - Settings saved to `~/.docker_tui.json`

## Installation

### Requirements
- Python 3.8 or higher
- Docker daemon running
- Access to Docker socket (`/var/run/docker.sock`)

### Install via pip (Recommended)
```bash
pip install dtop
```

### Install from GitHub (Latest)
```bash
pip install git+https://github.com/StakeSquid/dtop.git
```

### Quick Install Script
```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/StakeSquid/dtop/main/scripts/install.sh)"
```

### Development Installation
```bash
git clone https://github.com/StakeSquid/dtop
cd dtop
pip install -e .
```

## Quick Start

```bash
# Launch with modern Textual UI (default)
dtop

# Use legacy curses interface
dtop --legacy

# Enable debug mode
dtop --debug

# Force legacy mode via environment variable
export DTOP_LEGACY=true
dtop
```

## Keyboard Shortcuts

### Main Interface

#### Navigation
| Key | Action |
|-----|--------|
| `↑/↓` | Select container |
| `Enter` | Show actions menu |
| `Tab` | Switch between UI elements |
| `PageUp/PageDown` | Scroll container list |

#### Container Actions
| Key | Action |
|-----|--------|
| `L` | View logs |
| `I` | Inspect container |
| `Enter` | Actions menu |

#### Filtering & Search
| Key | Action |
|-----|--------|
| `\` | Focus filter input |
| `Escape` | Clear filter |

#### View Controls
| Key | Action |
|-----|--------|
| `R` | Refresh |
| `D` | Toggle dark/light theme |
| `C` | Column settings |
| `S` | Sort dialog |
| `?` | Help |
| `Q` | Quit |

### Log View

#### Navigation & Search
| Key | Action |
|-----|--------|
| `/` | Search in logs |
| `N` | Next match / Toggle normalization |
| `Shift+N` | Previous match |
| `\` | Filter logs |
| `Escape` | Clear search/filter or exit |

#### Display Controls
| Key | Action |
|-----|--------|
| `W` | Toggle line wrap |
| `F` | Toggle follow mode |
| `T` | Set tail lines |
| `Shift+T` | Toggle timestamps |
| `C` | Clear logs |
| `S` | Toggle case-sensitive search |

#### Advanced Features
| Key | Action |
|-----|--------|
| `R` | Time range filter |
| `E` | Export logs |
| `G` | Go to top |
| `Shift+G` | Go to bottom |
| `PageUp/PageDown` | Page up/down |

### Container Actions Menu

When you press Enter on a container, you can:
- **View Logs** - Advanced log viewer with filtering
- **Inspect** - Detailed container configuration
- **Stop/Start** - Control container state
- **Pause/Unpause** - Suspend container
- **Restart** - Restart container
- **Remove** - Delete container
- **Recreate** - Remove and recreate from image

## Log Filter Syntax

The log viewer supports complex filter expressions:

### Basic Filters
- `error` - Show lines containing "error"
- `+error` - Explicitly include lines with "error"
- `-error` or `!error` - Exclude lines with "error"
- `"exact phrase"` - Search for exact phrase

### Complex Expressions
- `error AND warning` - Lines with both terms
- `error OR warning` - Lines with either term
- `(error OR warning) AND -debug` - Combine with parentheses
- `error -verbose +info` - Mixed include/exclude

### Time Filtering
Press `R` in log view to filter by timestamp range. Supports various formats:
- `2024-01-01` - Date only
- `2024-01-01 14:30:00` - Full timestamp
- Leave empty for start/end of logs

## Configuration

Configuration is stored in `~/.docker_tui.json` and includes customizable column settings.

### Column Configuration

Each column supports:
- `min_width` - Minimum width in characters
- `max_width` - Maximum width (null for unlimited)
- `weight` - Relative weight for width distribution
- `align` - Text alignment (left/right)

Example configuration:
```json
{
  "columns": [
    {
      "name": "NAME",
      "min_width": 15,
      "max_width": null,
      "weight": 3,
      "align": "left"
    },
    {
      "name": "CPU%",
      "min_width": 7,
      "max_width": 10,
      "weight": 0,
      "align": "right"
    }
  ]
}
```

### Column Settings Dialog
Press `C` in the main view to open the column settings dialog where you can:
- Adjust minimum widths for each column
- Set maximum width constraints
- Changes are saved automatically

### Responsive Sizing
The table automatically adjusts to terminal width:
- Columns expand based on their weight values
- Respects min/max constraints
- NAME and IMAGE columns prioritized for expansion

## Project Structure

```
dtop/
├── dtop/
│   ├── __main__.py               # Package entry point
│   ├── main.py                   # Application entry point
│   ├── core/
│   │   ├── docker_tui.py         # Legacy curses interface
│   │   ├── textual_docker_tui.py # Modern Textual interface
│   │   └── stats.py              # Statistics collection
│   ├── views/
│   │   ├── textual_log_view.py   # Advanced log viewer
│   │   └── textual_inspect_view.py # Container inspector
│   ├── utils/
│   │   ├── config.py             # Configuration management
│   │   ├── utils.py              # Utility functions
│   │   └── normalize_logs.py     # Log normalization script
│   └── actions/
│       └── container_actions.py  # Container operations
├── pyproject.toml                # Package configuration
├── requirements.txt              # Dependencies
└── scripts/
    ├── install.sh                # Installation script
    └── uninstall.sh              # Uninstallation script
```

## Performance

dtop is optimized for efficiency:

- **Parallel Stats Collection** - Uses ThreadPoolExecutor for concurrent stats gathering
- **Smart Refresh** - Only updates changed data, throttles refresh to prevent overload
- **Memory Management** - Automatic log rotation (25,000 line limit)
- **Non-blocking UI** - Async operations keep UI responsive
- **Efficient Rendering** - Textual framework handles optimal screen updates

## Dependencies

### Core Requirements
- `docker>=6.0.0` - Docker SDK for Python
- `textual>=0.47.0` - Modern TUI framework
- `rich>=13.0.0` - Rich text formatting

### Optional
- `aiohttp>=3.8.0` - Enhanced async stats collection

## Troubleshooting

### Docker Connection Issues
```bash
# Check Docker daemon status
sudo systemctl status docker

# Verify socket permissions
ls -la /var/run/docker.sock

# Add user to docker group (logout/login required)
sudo usermod -aG docker $USER
```

### Screen Restoration Issues
If the terminal doesn't restore properly after exit:
```bash
reset
```

### Performance Issues
- Use filter to reduce number of displayed containers
- Disable auto-refresh when not actively monitoring
- Close unnecessary log viewers

### Legacy Interface
If you experience issues with the Textual interface:
```bash
# Use the legacy curses interface
dtop --legacy

# Or set environment variable
export DTOP_LEGACY=true
```

## Development

### Building from Source
```bash
# Clone repository
git clone https://github.com/StakeSquid/dtop
cd dtop

# Install in development mode
pip install -e .

# Run tests
pytest tests/

# Build distribution
python -m build
```

### Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues, questions, or feature requests:
- Open an issue on [GitHub](https://github.com/StakeSquid/dtop/issues)
- Check existing issues for solutions

## License

MIT License - see LICENSE file for details.

## Author

StakeSquid

---

**Note**: dtop requires an active Docker daemon and appropriate permissions to access the Docker socket. Ensure Docker is running and your user has the necessary permissions before launching the application.
