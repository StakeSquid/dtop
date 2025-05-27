# dtop - Docker Terminal UI

[![PyPI version](https://badge.fury.io/py/dtop.svg)](https://badge.fury.io/py/dtop)
[![Python versions](https://img.shields.io/pypi/pyversions/dtop.svg)](https://pypi.org/project/dtop/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A high-performance terminal UI for Docker container management with real-time monitoring, advanced log viewing, and comprehensive container operations.

<img width="1611" alt="Screenshot 2025-05-24 at 6 39 12 PM" src="https://github.com/user-attachments/assets/e5697f99-fdd4-4d41-bd69-02072db5385c" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 39 21 PM" src="https://github.com/user-attachments/assets/0694304e-f256-47b5-923b-5c05ed0035b7" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 39 48 PM" src="https://github.com/user-attachments/assets/df379064-9f33-48f7-9e8b-635723df6572" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 40 01 PM" src="https://github.com/user-attachments/assets/aeb20e8e-202c-49f8-bd09-7b563964bb9e" />

## Features

### 🚀 Core Functionality
- **Real-time Monitoring**: Live CPU, memory, network, and disk I/O stats with parallel collection
- **Container Management**: Complete lifecycle control (start, stop, pause, restart, recreate)
- **Interactive Shell Access**: Direct exec into containers with terminal support
- **Resource Monitoring**: Real-time performance metrics with color-coded indicators

### 📋 Advanced Log Management
- **Smart Log Normalization**: Automatic parsing and formatting of JSON, structured logs
- **Powerful Search**: Full-text search with regex support and result highlighting
- **Advanced Filtering**: Include/exclude patterns with complex boolean logic
- **Time-based Filtering**: Filter logs by date/time ranges with export capabilities
- **Follow Mode**: Real-time log streaming with auto-scroll
- **Export Functionality**: Save filtered logs to files

### 🎯 User Experience
- **Mouse Support**: Full mouse interaction for navigation, scrolling, and selection
- **Responsive Design**: Auto-adjusting columns with manual resize capability
- **Persistent Configuration**: Settings saved automatically between sessions
- **Keyboard Shortcuts**: Comprehensive hotkey support for power users
- **Visual Indicators**: Color-coded status, performance metrics, and alerts

## Installation

### PyPI Installation (Recommended)

```bash
pip install dtop
```

### Alternative Installation Methods

#### From GitHub (Latest)
```bash
pip install git+https://github.com/StakeSquid/dtop.git
```

#### One-Line Install Script
```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/StakeSquid/dtop/main/scripts/install.sh)"
```

#### Development Installation
```bash
# Clone repository
git clone https://github.com/StakeSquid/dtop
cd dtop

# Install in development mode
pip install -e .

# Or install dependencies manually
pip install docker
python -m dtop.main
```

## Quick Start

After installation, simply run:
```bash
dtop
```

Make sure Docker is running and accessible to your user account.

## Usage Guide

### Main Interface Controls

| Key | Action |
|-----|--------|
| ↑/↓ or Mouse | Navigate containers |
| Enter or Click | Show container action menu |
| L | View container logs |
| I | Inspect container details |
| Q | Quit application |
| R | Refresh container list |
| / | Search/filter containers |

### Container Actions

When you select a container (Enter or Click), you can:

- **📋 Logs**: View real-time and historical logs with advanced features
- **🔍 Inspect**: View detailed container configuration and state
- **▶️ Start/Stop**: Control container execution state
- **⏸️ Pause/Unpause**: Temporarily suspend container processes
- **🔄 Restart**: Restart the container
- **🔨 Recreate**: Remove and recreate container from image
- **💻 Exec Shell**: Open interactive shell session

### Advanced Log Viewing

#### Search and Navigation
| Key | Action |
|-----|--------|
| / | Search in logs (supports regex) |
| n/N | Next/previous search result |
| \\ | Advanced filter mode |
| ↑/↓, PgUp/PgDn | Scroll through logs |
| Home/End | Jump to beginning/end |

#### Log Controls
| Key | Action |
|-----|--------|
| F | Toggle follow mode (real-time streaming) |
| N | Toggle log normalization |
| W | Toggle line wrapping |
| R | Time range filter |
| E | Export logs to file |
| ESC | Clear filters/return to main |

#### Filter Syntax

The log viewer supports sophisticated filtering:

**Basic Filters:**
- `error` - Show lines containing "error"
- `+error` - Include lines with "error" (explicit include)
- `-warning` - Exclude lines with "warning"
- `!debug` - Exclude lines with "debug" (alternative syntax)

**Advanced Filters:**
```bash
error -debug                    # Lines with "error" but not "debug"
+error +warning -verbose       # Lines with "error" OR "warning", but not "verbose"  
"connection failed" -timeout   # Exact phrase matching with exclusion
```

**Filter Features:**
- Multiple inclusion filters work as OR logic
- Exclusion filters always take precedence
- Use quotes for multi-word phrases
- Press Tab to toggle case sensitivity
- Supports complex boolean combinations

#### Time-based Filtering

Press `R` in log view to filter by time range:
- Select start and end dates/times
- Export filtered results
- Combine with text filters
- Navigate through time ranges

#### Log Normalization

Press `N` to toggle automatic log normalization:
- Parses JSON logs into readable format
- Standardizes timestamp formats
- Extracts structured data fields
- Maintains original raw logs option

## Configuration

dtop automatically saves your preferences to `~/.docker_tui.json`:

```json
{
  "columns": {
    "widths": [20, 15, 10, 8, 8, 12, 12, 15, 15],
    "visible": ["NAME", "IMAGE", "STATUS", "CPU%", "MEM%", "NET I/O", "DISK I/O", "CREATED", "UPTIME"]
  },
  "log_settings": {
    "normalize": true,
    "wrap_lines": false,
    "follow_mode": false
  },
  "ui_settings": {
    "mouse_enabled": true,
    "show_separators": true
  }
}
```

### Customization Options

- **Column Resize**: Drag column separators with mouse
- **Column Visibility**: Configure which metrics to display
- **Performance Tuning**: Adjust refresh rates and collection intervals
- **Color Themes**: Customize status and performance indicators

## Architecture

dtop is built with a modular architecture:

```
dtop/
├── core/           # Core TUI engine and stats collection
├── views/          # Log viewer and inspection interfaces  
├── actions/        # Container operation handlers
├── utils/          # Configuration, utilities, and log processing
└── scripts/        # Installation and maintenance scripts
```

### Key Components

- **Async Stats Collection**: Parallel collection using aiohttp for performance
- **Real-time Log Streaming**: Efficient Docker API integration
- **Responsive UI**: Curses-based interface with mouse support
- **Extensible Actions**: Plugin-ready container operation system

## Performance Features

- **Parallel Processing**: Concurrent stats collection for multiple containers
- **Efficient Caching**: Smart caching of container metadata and logs
- **Memory Management**: Automatic garbage collection and resource cleanup
- **Optimized Rendering**: Minimal screen updates and efficient drawing

## Requirements

- **Python**: 3.8 or higher
- **Docker**: Docker daemon running and accessible
- **Terminal**: Mouse support and color capability recommended
- **Dependencies**: `docker>=6.0.0` (automatically installed)

### Optional Dependencies

- `aiohttp>=3.8.0` - For enhanced async performance (install with `pip install dtop[full]`)

## Troubleshooting

### Common Issues

**Docker Connection Error:**
```bash
# Ensure Docker is running
sudo systemctl start docker

# Check Docker socket permissions
sudo usermod -aG docker $USER
# Then logout and login again
```

**Terminal Display Issues:**
```bash
# Reset terminal if display is corrupted
reset

# Ensure terminal supports colors and mouse
echo $TERM
```

**Performance Issues:**
- Reduce number of containers being monitored
- Disable mouse support if experiencing lag
- Adjust refresh intervals in configuration

### Getting Help

- **GitHub Issues**: [Report bugs and feature requests](https://github.com/StakeSquid/dtop/issues)
- **Discussions**: [Community discussions and questions](https://github.com/StakeSquid/dtop/discussions)

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/StakeSquid/dtop
cd dtop

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Install development dependencies
pip install -e .[dev]

# Run tests
python -m pytest tests/
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with Python's `curses` library for terminal UI
- Uses the official Docker Python SDK
- Inspired by htop and similar system monitoring tools

---

**⭐ Star this repository if dtop helps you manage Docker containers more efficiently!**