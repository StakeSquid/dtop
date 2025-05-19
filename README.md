# dtop

A high-performance, interactive Terminal User Interface (TUI) for managing Docker containers, featuring real-time container monitoring, responsive interactions, dynamic resizing, detailed logs, and customizable configurations.

## Features

* **Real-time Container Monitoring:** Fast and efficient parallel fetching of CPU, memory, network, and status data for containers.
* **Interactive Controls:** Navigate and manage containers easily with keyboard shortcuts and mouse support.
* **Detailed Log Viewer:** Reliable log display with normalization, line wrapping, and follow mode.
* **Resizable Columns:** Dynamic column widths adjustable via mouse drag.
* **Persistent Configuration:** Saves user preferences (such as column layout) across sessions.

## Dependencies

Ensure you have Python 3.8+ installed and Docker daemon running.

### Python Dependencies:

```bash
pip install docker
```

## Installation

1. Save the main application script as `docker_tui.py` and ensure it's executable:

```bash
chmod +x docker_tui.py
```

2. Save the log normalization script as `normalize_logs.py` in the same directory and make it executable:

```bash
chmod +x normalize_logs.py
```

## Running the Application

Execute the Docker TUI application directly from the terminal:

```bash
./docker_tui.py
```

## Usage

### Main Interface Controls

* **Navigation:**

  * `↑` / `↓` or **Mouse Click**: Navigate through container list.
* **Container Actions:**

  * `Enter` / **Mouse Click**: Open container action menu.
  * `L`: View container logs.
* **Logs View Toggles:**

  * `F`: Toggle log follow mode (real-time updates).
  * `N`: Toggle log normalization.
  * `W`: Toggle log line wrapping.
* **Interface:**

  * **Mouse Drag**: Resize column widths.
  * `Q`: Quit the application.

### Container Action Menu

When a container is selected, pressing `Enter` or clicking it opens an action menu:

* **Logs**: View detailed container logs.
* **Start/Stop**: Start or stop the selected container.
* **Pause/Unpause**: Temporarily pause or resume container execution.
* **Restart**: Restart the selected container.
* **Recreate**: Remove and recreate the container based on the original image.
* **Exec Shell**: Launch an interactive shell (`/bin/bash`) inside the running container.
* **Cancel**: Exit the menu without action.

### Log Viewer Controls

* **Navigation:**

  * `↑` / `↓`: Scroll through logs.
  * `PgUp` / `PgDn`: Scroll pages.
  * `Home` / `End`: Go to start or end of logs.
* **Horizontal Scroll (unwrapped logs only):**

  * `←` / `→`: Scroll horizontally.
* **View Toggles:**

  * `F`: Toggle follow mode.
  * `N`: Toggle normalization.
  * `W`: Toggle line wrapping.
* **Exit Logs:**

  * `ESC` / `Q`: Return to main container list.

## Configuration

Configuration settings, such as column widths and visibility, are automatically saved to the user's home directory:

```
~/.docker_tui.json
```

Modify this file directly to adjust default settings or simply resize columns within the application interface.

## Log Normalization (`normalize_logs.py`)

This script processes various Docker log formats, removing ANSI color codes, formatting timestamps, and structuring logs for improved readability.

* **Supported Log Formats:**

  * JSON-based logs from common Dockerized services (e.g., Geth, IndexerAgent, Walrus).
  * Key-value structured logs.

## Troubleshooting

* **Docker Daemon Errors:**
  If the application fails to connect to Docker, ensure your user has permissions for Docker socket (`/var/run/docker.sock`).

  ```bash
  sudo usermod -aG docker $USER
  newgrp docker
  ```
* **Terminal Display Issues:**
  If your terminal behaves strangely after exiting:

  ```bash
  reset
  ```

## License

MIT License

---

Developed for efficient Docker container management directly from the terminal.
