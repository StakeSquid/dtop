# dtop - Docker Terminal UI

A high-performance terminal UI for Docker container management with real-time monitoring and advanced log viewing.

![Container list view](https://github.com/user-attachments/assets/1fabacfa-ff14-4792-9997-55d22f06f8f2)
![Container action menu](https://github.com/user-attachments/assets/bd436854-c6b4-4bbe-898f-fd7b37f179e6)
![Log viewer](https://github.com/user-attachments/assets/32ee2625-9390-43fe-ad59-1fac6bd93d12)

## Features

- **Real-time Stats**: Live CPU, memory, and network monitoring with parallel stats collection
- **Log Management**: 
  - Advanced normalization for consistent log formatting
  - Text search with highlighted results
  - Grep-like filtering
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
| | ESC | Return to container list |

### Container Actions

- **Logs**: View detailed container logs
- **Start/Stop**: Toggle container running state
- **Pause/Unpause**: Temporarily pause execution
- **Restart**: Restart the container
- **Recreate**: Recreate container from image
- **Exec Shell**: Open interactive shell in container

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
