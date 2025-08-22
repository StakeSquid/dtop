# Docker TUI - Textual Migration

## Overview

The Docker TUI application has been successfully ported from curses to Textual, providing a modern, feature-rich terminal user interface with improved usability and maintainability.

## New Features in Textual Version

### Enhanced UI Components
- **Modern DataTable Widget**: Better scrolling, selection, and rendering
- **Modal Dialogs**: Clean action menus with keyboard and mouse support
- **Reactive Properties**: Automatic UI updates without manual redraws
- **CSS Styling**: Customizable themes and better visual hierarchy
- **Built-in Notifications**: Non-intrusive status messages
- **Tree View for Inspect**: Hierarchical JSON navigation

### Improved Functionality
- **Better Performance**: Efficient async operations and rendering
- **Enhanced Search**: Real-time highlighting in logs and inspect views
- **Advanced Filtering**: Support for complex filter expressions
- **Column Sorting**: Click headers to sort by any column
- **Responsive Layout**: Adapts to terminal size changes
- **Dark/Light Themes**: Toggle with keyboard shortcut

## Usage

### Default (Textual Interface)
```bash
dtop
```

### Legacy (Curses Interface)
```bash
dtop --legacy
# or
export DTOP_LEGACY=true
dtop
```

### Debug Mode
```bash
dtop --debug
```

## Keyboard Shortcuts

### Global
- `q` - Quit application
- `r` - Refresh containers
- `?` - Show help
- `d` - Toggle dark/light theme

### Navigation
- `↑/↓` - Navigate containers
- `Enter` - Show actions menu
- `Tab` - Focus next element
- `Shift+Tab` - Focus previous element

### Container Actions
- `l` - View container logs
- `i` - Inspect container
- `s` - Start/Stop container

### Filtering & Search
- `\` - Focus filter input
- `Escape` - Clear filter
- `/` - Search (in logs/inspect views)

### Settings
- `n` - Toggle log normalization
- `w` - Toggle line wrapping

## Architecture Changes

### Component Mapping

| Curses Component | Textual Component | Benefits |
|-----------------|-------------------|----------|
| Manual drawing | Automatic rendering | Less code, better performance |
| Character-based UI | Widget-based UI | Reusable components |
| Polling updates | Reactive properties | Automatic updates |
| Custom scrolling | Built-in scrolling | Smoother experience |
| Raw key handling | Event system | Cleaner code |

### File Structure

```
dtop/
├── core/
│   ├── docker_tui.py          # Legacy curses implementation
│   ├── textual_docker_tui.py  # New Textual main app
│   ├── textual_app.py         # Initial Textual prototype
│   └── stats.py                # Shared stats collection
├── views/
│   ├── log_view.py             # Legacy log viewer
│   ├── textual_log_view.py    # Textual log viewer
│   ├── inspect_view.py         # Legacy inspect viewer
│   └── textual_inspect_view.py # Textual inspect viewer
└── main.py                      # Entry point with mode selection
```

## Key Improvements

### 1. Better Async Handling
- Textual's built-in async support eliminates manual threading
- Background workers for non-blocking operations
- Efficient timer system for periodic updates

### 2. Enhanced User Experience
- Smooth scrolling and navigation
- Visual feedback for all actions
- Consistent keyboard shortcuts
- Mouse support throughout

### 3. Maintainability
- Cleaner separation of concerns
- Reusable widget components
- CSS-based styling
- Type hints and better structure

### 4. Performance
- Efficient rendering pipeline
- Smart update batching
- Reduced CPU usage
- Better memory management

## Migration Considerations

### Preserved Features
✅ All container operations (start, stop, restart, etc.)
✅ Real-time stats monitoring
✅ Log viewing with normalization
✅ Container inspection
✅ Filtering and search
✅ Column configuration
✅ Keyboard shortcuts

### Enhanced Features
⭐ Better visual feedback
⭐ Smoother animations
⭐ More intuitive navigation
⭐ Richer formatting options
⭐ Theme support

### Known Differences
- Exec shell requires external terminal (security consideration)
- Some visual elements may render differently
- Mouse behavior is more consistent

## Testing

The Textual version has been designed to handle:
- Large numbers of containers (100+)
- Rapid updates and refreshes
- Terminal resizing
- Various terminal emulators
- SSH sessions
- Screen/tmux compatibility

## Future Enhancements

Potential improvements for future versions:
- Container log streaming
- Multi-container selection
- Batch operations
- Custom themes
- Plugin system
- Export functionality
- Metrics graphing

## Compatibility

- Python 3.8+
- Docker API 6.0+
- Textual 0.47+
- Rich 13.0+

## Fallback Support

The legacy curses interface remains available for:
- Systems without Textual
- Compatibility requirements
- User preference
- Minimal dependencies

Use `--legacy` flag or set `DTOP_LEGACY=true` environment variable.

## Conclusion

The Textual migration provides a significant upgrade to the Docker TUI, offering a modern, maintainable, and feature-rich interface while preserving all original functionality. Users can seamlessly transition to the new interface or continue using the legacy version as needed.