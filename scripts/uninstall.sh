#!/bin/bash
# uninstall.sh - Docker TUI uninstaller script

set -e  # Exit immediately if a command exits with a non-zero status

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Banner
echo -e "${GREEN}"
echo "╔════════════════════════════════════════════╗"
echo "║        Docker TUI Uninstaller              ║"
echo "╚════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if script is run with sudo/root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: This script needs to be run with sudo or as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Paths
INSTALL_DIR="/usr/local/bin"
CONFIG_FILE="$HOME/.docker_tui.json"

# Confirm uninstallation
echo -e "${YELLOW}This will uninstall Docker TUI from your system.${NC}"
echo -n "Do you want to continue? [y/N] "
read -r response
if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo "Uninstallation cancelled."
    exit 0
fi

# Remove installation files
echo -e "${YELLOW}Removing Docker TUI files...${NC}"
if [ -d "$INSTALL_DIR/docker-tui" ]; then
    rm -rf "$INSTALL_DIR/docker-tui"
    echo "Removed $INSTALL_DIR/docker-tui"
fi

if [ -f "$INSTALL_DIR/dtop" ]; then
    rm -f "$INSTALL_DIR/dtop"
    echo "Removed $INSTALL_DIR/dtop"
fi

# Ask about configuration
echo -e "${YELLOW}Do you want to remove the configuration file ($CONFIG_FILE)?${NC}"
echo -n "This will delete your saved settings. [y/N] "
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    if [ -f "$CONFIG_FILE" ]; then
        rm -f "$CONFIG_FILE"
        echo "Removed configuration file: $CONFIG_FILE"
    else
        echo "Configuration file not found. Skipping."
    fi
else
    echo "Keeping configuration file."
fi

echo -e "${GREEN}Docker TUI has been successfully uninstalled!${NC}"
