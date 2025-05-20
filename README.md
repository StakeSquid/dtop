# Docker TUI

A high-performance, interactive Terminal User Interface (TUI) for managing Docker containers with real-time monitoring, responsive interactions, and powerful log management capabilities.

## Features

- **Real-time Container Monitoring**: View live CPU, memory, and network statistics for all running containers with fast parallel data collection
- **Interactive Controls**: Navigate containers and perform actions using keyboard shortcuts or mouse
- **Advanced Log Viewer**: 
  - Log normalization for consistent formatting across different container types
  - Text search with highlighted results
  - Log filtering (grep-like functionality)
  - Line wrapping toggle for viewing long log lines
  - Follow mode for real-time log updates
- **Customizable Interface**:
  - Resizable columns with persistent configuration
  - Dynamic layout that adapts to terminal size
- **Container Management**:
  - Start/stop containers
  - Pause/unpause containers
  - Restart containers
  - Execute interactive shells
  - View detailed logs
  - Recreate containers

## Screenshots

<img width="2168" alt="Container list view showing stats for multiple containers" src="https://github.com/user-attachments/assets/1fabacfa-ff14-4792-9997-55d22f06f8f2" />
<img width="385" alt="Container action menu with available operations" src="https://github.com/user-attachments/assets/bd436854-c6b4-4bbe-898f-fd7b37f179e6" />
<img width="2168" alt="Log viewer with normalized logs and search functionality" src="https://github.com/user-attachments/assets/32ee2625-9390-43fe-ad59-1fac6bd93d12" />

## Prerequisites

- Python 3.8 or higher
- Docker daemon running and accessible
- Terminal with support for mouse events and colors

## Installation

1. Clone the repository or download the source files:

```bash
git clone https://github.com/StakeSquid/dtop
cd dtop
```

2. Install the required Python dependency:

```bash
pip install docker
```

3. Make the main script and log normalizer executable:

```bash
chmod +x main.py normalize_logs.py
```

## Quick Start

Run the application:

```bash
./main.py
```

The application will connect to your local Docker daemon and display all containers.

# Installing Docker TUI as a System Command

There are two main ways to install the Docker TUI application as a system command that can be run from anywhere:

## Option 1: Using the Installer Script (Recommended)

The included installer script will:
- Copy all necessary files to `/usr/local/bin`
- Make them executable
- Create a simple command `dtop` to launch the application from anywhere

### Installation Steps

1. Make the installer script executable:

```bash
chmod +x install.sh
```

2. Run the installer with sudo:

```bash
sudo ./install.sh
```

3. Once installed, you can run Docker TUI from anywhere by simply typing:

```bash
dtop
```

### Uninstallation

To uninstall Docker TUI, use the included uninstaller script:

```bash
chmod +x uninstall.sh
sudo ./uninstall.sh
```

## Option 2: Manual Installation

If you prefer to install manually, follow these steps:

1. Create a directory for Docker TUI in `/usr/local/bin`:

```bash
sudo mkdir -p /usr/local/bin/docker-tui
```

2. Copy all required files to the installation directory:

```bash
sudo cp main.py docker_tui.py log_view.py container_actions.py \
       stats.py config.py utils.py normalize_logs.py \
       /usr/local/bin/docker-tui/
```

3. Make all Python files executable:

```bash
sudo chmod +x /usr/local/bin/docker-tui/*.py
```

4. Create a launcher script:

```bash
sudo tee /usr/local/bin/dtop > /dev/null << 'EOF'
#!/bin/bash
exec python3 /usr/local/bin/docker-tui/main.py "$@"
EOF
```

5. Make the launcher executable:

```bash
sudo chmod +x /usr/local/bin/dtop
```

6. Test the installation by running:

```bash
dtop
```

### Manual Uninstallation

To uninstall manually:

```bash
sudo rm -rf /usr/local/bin/docker-tui /usr/local/bin/dtop
```

## Configuration File

Regardless of installation method, the configuration file will be stored at:

```
~/.docker_tui.json
```

This file contains your saved column settings and preferences. It will be created automatically when you first run the application.

## Dependencies

The installer script automatically checks for and installs the Docker Python package. If you're installing manually, make sure to install it:

```bash
pip install docker
```

## Troubleshooting

### "Command not found" Error

If you get a "command not found" error after installation:

1. Make sure `/usr/local/bin` is in your PATH:
   ```bash
   echo $PATH
   ```

2. If it's not, add it to your shell configuration file:
   ```bash
   echo 'export PATH=$PATH:/usr/local/bin' >> ~/.bashrc
   source ~/.bashrc
   ```

### Permission Issues

If you encounter permission issues:

```bash
sudo chown -R root:root /usr/local/bin/docker-tui
sudo chmod -R 755 /usr/local/bin/docker-tui
```

### Docker Connection Issues

Ensure your user is in the docker group:

```bash
sudo usermod -aG docker $USER
# Log out and back in, or run:
newgrp docker
```

## Keyboard Controls

### Main Container View

| Key | Function |
|-----|----------|
| ↑/↓ | Navigate through container list |
| Enter | Show action menu for selected container |
| L | View logs for selected container |
| F | Toggle log follow mode |
| N | Toggle log normalization |
| W | Toggle log line wrapping |
| Click | Select container or interact with interface |
| Q | Quit application |

### Container Action Menu

| Key | Function |
|-----|----------|
| ↑/↓ | Navigate menu options |
| Enter | Select action |
| L | View logs |
| S | Start/Stop container |
| P | Pause/Unpause container |
| R | Restart container |
| F | Force recreate container |
| E | Execute interactive shell |
| C or ESC | Cancel/close menu |

### Log Viewer

| Key | Function |
|-----|----------|
| ↑/↓ | Scroll logs vertically |
| PgUp/PgDn | Page up/down through logs |
| Home/g | Go to beginning of logs |
| End/G | Go to end of logs |
| ←/→ | Scroll logs horizontally (when wrapping disabled) |
| / | Search in logs |
| \\ | Filter logs (grep-like functionality) |
| n | Next search result |
| N | Previous search result |
| F | Toggle follow mode |
| N | Toggle log normalization |
| W | Toggle line wrapping |
| ESC/Q | Return to container list |

### Search/Filter Mode

| Key | Function |
|-----|----------|
| Enter | Apply search/filter |
| Tab | Toggle case sensitivity |
| ESC | Exit search/filter mode |
| Backspace | Delete character |

## Mouse Support

The application supports comprehensive mouse interaction:

- **Click** on a container to select it
- **Double-click** a container to open its action menu
- **Wheel** to scroll through containers or logs
- **Click** on menu items to select them
- **Click** on the scrollbar to jump to a position

## Log Normalization

The application includes a powerful log normalization feature (`normalize_logs.py`) that standardizes different log formats for better readability:

- Formats timestamps consistently (`MM-DD|HH:MM:SS.mmm`)
- Removes ANSI color codes
- Structures JSON logs with consistent field ordering
- Normalizes key-value style logs
- Handles various log formats (Geth-style, IndexerAgent-style, Walrus-style, etc.)

## Configuration

The application automatically saves your column configuration to `~/.docker_tui.json`. This includes column widths, visibility, and other display preferences.

Default columns include:
- NAME
- IMAGE
- STATUS
- CPU%
- MEM%
- NET I/O
- CREATED AT
- UPTIME

## Component Architecture

The application is structured with the following modules:

- `main.py` - Entry point and launcher
- `docker_tui.py` - Core TUI implementation
- `log_view.py` - Log viewer functionality
- `container_actions.py` - Container action menu and operations
- `stats.py` - Container statistics collection
- `config.py` - Configuration management
- `utils.py` - Utility functions
- `normalize_logs.py` - Log normalization script

## Advanced Usage

### Column Customization

The application supports dynamic column resizing. The configuration is saved automatically and persists between sessions.

### Log Filtering Example

When viewing logs, press `\` to enter filter mode:
1. Type your filter text (e.g., `error`)
2. Press Tab to toggle case sensitivity if needed
3. Press Enter to apply the filter
4. Only matching lines will be displayed
5. To clear the filter, press `\` again and press Enter with an empty filter

### Log Searching Example

When viewing logs, press `/` to enter search mode:
1. Type your search term (e.g., `connection`)
2. Press Enter to search
3. Use `n` and `N` to navigate between matches
4. Matches will be highlighted in the logs
5. To clear search, press `/` again and press Enter with an empty search term

## Troubleshooting

### Screen Display Issues

If your terminal displays incorrectly after exiting the application:

```bash
reset
```

### Docker Connection Issues

Ensure your user has permissions to access the Docker socket:

```bash
sudo usermod -aG docker $USER
# Then log out and back in, or run:
newgrp docker
```

### Log Normalization Not Working

If log normalization doesn't work:

1. Ensure `normalize_logs.py` is executable:
   ```bash
   chmod +x normalize_logs.py
   ```
2. Verify it's in the same directory as the main application
3. Check for any error messages at the top of the log view

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests.

## Acknowledgements

- Built with Python and the curses library
- Uses the Docker Python SDK for container interaction
- Inspiration from tools like htop and Docker CLI
