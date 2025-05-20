#!/bin/bash
# install.sh - Docker TUI installer script
# This script installs Docker TUI to /usr/local/bin

set -e  # Exit immediately if a command exits with a non-zero status

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Banner
echo -e "${GREEN}"
echo "╔════════════════════════════════════════════╗"
echo "║        Docker TUI Installer                ║"
echo "╚════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if script is run with sudo/root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: This script needs to be run with sudo or as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Set installation directory
INSTALL_DIR="/usr/local/bin"
TMP_DIR="/tmp/docker-tui-install"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Create temporary directory
mkdir -p "$TMP_DIR"
echo -e "${YELLOW}Preparing installation...${NC}"

# Check for required files
required_files=(
    "main.py"
    "docker_tui.py"
    "log_view.py"
    "container_actions.py"
    "stats.py"
    "config.py"
    "utils.py"
    "normalize_logs.py"
)

for file in "${required_files[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$file" ]; then
        echo -e "${RED}Error: Required file $file not found in $SCRIPT_DIR${NC}"
        echo "Please run this installer from the Docker TUI directory"
        exit 1
    fi
done

# Check for python3 installation
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    echo "Please install Python 3 and try again"
    exit 1
fi

# Check for docker module
if ! python3 -c "import docker" &> /dev/null; then
    echo -e "${YELLOW}Docker Python module not found. Installing...${NC}"
    pip3 install docker || {
        echo -e "${RED}Failed to install Docker Python module${NC}"
        echo "Please install manually with: pip3 install docker"
        exit 1
    }
    echo -e "${GREEN}Docker Python module installed successfully${NC}"
fi

# Create the installation package
echo -e "${YELLOW}Creating installation package...${NC}"
for file in "${required_files[@]}"; do
    cp "$SCRIPT_DIR/$file" "$TMP_DIR/"
    chmod +x "$TMP_DIR/$file"
done

# Create the main executable
cat > "$TMP_DIR/dtop" << 'EOF'
#!/bin/bash
# dtop - Docker TUI launcher

# Find the installation directory
EXEC_PATH=$(readlink -f "$0")
INSTALL_DIR=$(dirname "$EXEC_PATH")

# Add shebang to Python files if not already present
for pyfile in "$INSTALL_DIR"/*.py; do
    if [ -f "$pyfile" ]; then
        if ! grep -q "^#!/usr/bin/env python3" "$pyfile"; then
            sed -i '1i#!/usr/bin/env python3' "$pyfile"
        fi
        chmod +x "$pyfile"
    fi
done

# Launch the application
exec python3 "$INSTALL_DIR/docker-tui/main.py" "$@"
EOF

chmod +x "$TMP_DIR/dtop"

# Install to /usr/local/bin
echo -e "${YELLOW}Installing to $INSTALL_DIR...${NC}"
mkdir -p "$INSTALL_DIR/docker-tui"

# Copy all files to the installation directory
cp "$TMP_DIR"/*.py "$INSTALL_DIR/docker-tui/"
cp "$TMP_DIR/dtop" "$INSTALL_DIR/"

# Create symbolic link
ln -sf "$INSTALL_DIR/docker-tui/main.py" "$INSTALL_DIR/docker-tui/main"
chmod +x "$INSTALL_DIR/docker-tui/main"

# Clean up
rm -rf "$TMP_DIR"

echo -e "${GREEN}Docker TUI has been successfully installed!${NC}"
echo "You can now run Docker TUI by typing 'dtop' in your terminal."
echo 
echo -e "${YELLOW}Note: If you want to uninstall Docker TUI, run:${NC}"
echo "sudo rm -rf $INSTALL_DIR/docker-tui $INSTALL_DIR/dtop"
echo 
echo -e "${GREEN}Enjoy using Docker TUI!${NC}"
