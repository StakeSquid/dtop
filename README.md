# dtop - Docker Terminal UI

A high-performance terminal UI for Docker container management with real-time monitoring and advanced log viewing.

<img width="1611" alt="Screenshot 2025-05-24 at 6 39 12 PM" src="https://github.com/user-attachments/assets/e5697f99-fdd4-4d41-bd69-02072db5385c" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 39 21 PM" src="https://github.com/user-attachments/assets/0694304e-f256-47b5-923b-5c05ed0035b7" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 39 48 PM" src="https://github.com/user-attachments/assets/df379064-9f33-48f7-9e8b-635723df6572" />
<img width="1611" alt="Screenshot 2025-05-24 at 6 40 01 PM" src="https://github.com/user-attachments/assets/aeb20e8e-202c-49f8-bd09-7b563964bb9e" />



## Features

- **Real-time Stats**: Live CPU, memory, and network monitoring with parallel stats collection
- **Log Management**: 
  - Advanced normalization for consistent log formatting
  - Text search with highlighted results
  - Powerful filtering with inclusion/exclusion support
  - Follow mode for real-time updates
- **Container Controls**: Start/stop, pause/unpause, restart, exec shell, force recreate
- **Mouse Support**: Click navigation, scrolling, and menu interaction
- **Customizable Interface**: Resizable columns with persistent configuration

## Installation

### One-Line Install

```bash
# Install directly from GitHub
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/StakeSquid/dtop/main/install.sh)"
```

### Manual Install

```bash
# 1. Clone repository
git clone https://github.com/StakeSquid/dtop
cd dtop

# 2. Install dependency
pip install docker

# 3. Run directly
chmod +x main.py
./main.py

# 4. Or install system-wide
sudo mkdir -p /usr/local/bin/docker-tui
sudo cp *.py /usr/local/bin/docker-tui/
sudo chmod +x /usr/local/bin/docker-tui/*.py
sudo tee /usr/local/bin/dtop > /dev/null << 'EOF'
#!/bin/bash
exec python3 /usr/local/bin/docker-tui/main.py "$@"
EOF
sudo chmod +x /usr/local/bin/dtop
```

### Uninstall

```bash
sudo rm -rf /usr/local/bin/docker-tui /usr/local/bin/dtop
```

## Quick Reference

### Controls

| View | Key | Action |
|------|-----|--------|
| **Main** | ↑/↓, Click | Navigate containers |
| | Enter/Click | Show container menu |
| | L | View container logs |
| | Q | Quit |
| **Logs** | ↑/↓, PgUp/PgDn | Scroll logs |
| | / | Search in logs |
| | \\ | Filter logs (grep) |
| | F | Toggle follow mode |
| | N | Toggle log normalization |
| | W | Toggle line wrapping |
| | n/N | Next/previous search hit |
| | ESC | Clear filter or return to container list |

### Container Actions

- **Logs**: View detailed container logs
- **Start/Stop**: Toggle container running state
- **Pause/Unpause**: Temporarily pause execution
- **Restart**: Restart the container
- **Recreate**: Recreate container from image
- **Exec Shell**: Open interactive shell in container

## Advanced Log Filtering

The log viewer supports powerful filtering with both inclusion and exclusion patterns:

### Filter Syntax

- **Include**: `word` or `+word` - Show only lines containing "word"
- **Exclude**: `-word` or `!word` - Hide lines containing "word"
- **Multiple filters**: Space-separated, all conditions must match
- **Multi-word**: Use quotes for phrases: `"error message" -"debug"`

### Examples

```
error                    # Show only lines with "error"
+error -debug           # Show lines with "error" but not "debug"
error warning -verbose  # Show lines with "error" OR "warning", but not "verbose"
"connection failed"     # Show lines with exact phrase
+ERROR -"DEBUG:" -INFO  # Case-sensitive: ERROR lines without DEBUG: or INFO
```

### Filter Behavior

- Multiple inclusion filters work as OR (any match includes the line)
- Exclusion filters always take precedence (any match excludes the line)
- Press Tab to toggle case sensitivity
- Press ESC to clear active filter
- Press \\ to modify current filter

## Configuration

- Settings automatically saved to `~/.docker_tui.json`
- Columns auto-adjust to terminal width
- Resizable columns (drag separators with mouse)

## Requirements

- Python 3.8+
- Docker daemon 
- `docker` Python package
- Terminal with mouse support and colors

## License

MIT License - See LICENSE file for details.
